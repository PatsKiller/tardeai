"""End-to-end localhost Temporal failure-injection acceptance for the NOC POC."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import socket
import sqlite3
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.worker import Replayer

from scripts.temporal_poc.contracts import TASK_QUEUE
from scripts.temporal_poc.runtime_store import RuntimeStore
from scripts.temporal_poc.temporal_workflow import AutonomousResearchToCIOWorkflow


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AcceptanceHarness:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root = Path(args.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs = self.root / "logs"
        self.logs.mkdir(exist_ok=True)
        self.temporal_db = self.root / "temporal.sqlite3"
        self.server: subprocess.Popen[str] | None = None
        self.workers: dict[str, subprocess.Popen[str]] = {}
        self.log_handles: list[Any] = []
        self.server_starts: list[dict[str, Any]] = []
        self.worker_starts: list[dict[str, Any]] = []
        self.scenarios: list[dict[str, Any]] = []
        self.histories: dict[str, Any] = {}
        self.v1 = f"{args.source_sha}-poc-v1"
        self.v2 = f"{args.source_sha}-poc-v2"

    def _open_log(self, name: str):
        handle = (self.logs / name).open("a", encoding="utf-8")
        self.log_handles.append(handle)
        return handle

    @staticmethod
    def _wait_port(port: int, timeout: float = 30.0) -> float:
        started = time.perf_counter()
        deadline = started + timeout
        while time.perf_counter() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return time.perf_counter() - started
            except OSError:
                time.sleep(0.1)
        raise TimeoutError(f"Temporal service did not bind 127.0.0.1:{port}")

    def start_server(self) -> None:
        log = self._open_log("temporal-server.log")
        command = [
            self.args.temporal_cli,
            "server",
            "start-dev",
            "--ip",
            "127.0.0.1",
            "--port",
            str(self.args.port),
            "--headless",
            "--namespace",
            self.args.namespace,
            "--db-filename",
            str(self.temporal_db),
            "--log-level",
            "warn",
        ]
        started = time.perf_counter()
        self.server = subprocess.Popen(
            command,
            cwd=self.args.repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        ready_seconds = self._wait_port(self.args.port)
        self.server_starts.append(
            {
                "pid": self.server.pid,
                "started_monotonic_seconds": round(time.perf_counter() - started, 6),
                "ready_seconds": round(ready_seconds, 6),
            }
        )

    def stop_server(self, *, kill: bool = True) -> None:
        if not self.server or self.server.poll() is not None:
            return
        if kill:
            self.server.kill()
        else:
            self.server.terminate()
        self.server.wait(timeout=15)

    def _cli(self, *parts: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.args.temporal_cli,
                *parts,
                "--address",
                self.args.address,
                "--namespace",
                self.args.namespace,
            ],
            cwd=self.args.repo,
            text=True,
            capture_output=True,
            timeout=30,
            check=check,
        )

    def start_worker(self, build_id: str) -> subprocess.Popen[str]:
        log = self._open_log(f"worker-{build_id[-6:]}.log")
        command = [
            self.args.python,
            "-m",
            "scripts.temporal_poc.runtime_worker",
            "--address",
            self.args.address,
            "--namespace",
            self.args.namespace,
            "--build-id",
            build_id,
            "--deployment-name",
            self.args.deployment,
            "--versioned",
        ]
        started = time.perf_counter()
        process = subprocess.Popen(
            command,
            cwd=self.args.repo,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.workers[build_id] = process
        deadline = time.perf_counter() + 30
        while time.perf_counter() < deadline:
            described = self._cli(
                "worker",
                "deployment",
                "describe-version",
                "--deployment-name",
                self.args.deployment,
                "--build-id",
                build_id,
                check=False,
            )
            if described.returncode == 0:
                self.worker_starts.append(
                    {
                        "pid": process.pid,
                        "build_id": build_id,
                        "deployment_visible_seconds": round(time.perf_counter() - started, 6),
                    }
                )
                return process
            if process.poll() is not None:
                raise RuntimeError(f"worker {build_id} exited {process.returncode}; see {log.name}")
            time.sleep(0.2)
        raise TimeoutError(f"worker deployment version {build_id} was not visible")

    def stop_worker(self, build_id: str, *, kill: bool = True) -> None:
        process = self.workers.get(build_id)
        if not process or process.poll() is not None:
            return
        if kill:
            process.kill()
        else:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=15)

    def set_current(self, build_id: str) -> None:
        self._cli(
            "worker",
            "deployment",
            "set-current-version",
            "--deployment-name",
            self.args.deployment,
            "--build-id",
            build_id,
            "--ignore-missing-task-queues",
            "--yes",
        )

    async def client(self) -> Client:
        return await Client.connect(self.args.address, namespace=self.args.namespace)

    def scenario_root(self, name: str) -> Path:
        root = self.root / "scenarios" / name
        root.mkdir(parents=True, exist_ok=True)
        return root

    async def start_workflow(
        self,
        name: str,
        *,
        fault: dict[str, Any] | None = None,
        stage_delay_seconds: float = 0,
    ) -> tuple[WorkflowHandle, float]:
        client = await self.client()
        workflow_id = f"tradeai-temporal-poc-{name}"
        request = {
            "run_id": name,
            "symbol": "NOC",
            "root": str(self.scenario_root(name)),
            "fault": fault,
            "stage_delay_seconds": stage_delay_seconds,
        }
        started = time.perf_counter()
        handle = await client.start_workflow(
            AutonomousResearchToCIOWorkflow.run,
            request,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
        return handle, time.perf_counter() - started

    async def wait_marker(self, name: str, boundary: str, timeout: float = 30) -> None:
        store = RuntimeStore(self.scenario_root(name))
        workflow_id = f"tradeai-temporal-poc-{name}"
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if store.has_marker(workflow_id, boundary):
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(f"marker {name}:{boundary} not observed")

    async def capture_history(self, name: str, handle: WorkflowHandle) -> dict[str, Any]:
        history = await handle.fetch_history()
        payload = history.to_json().encode("utf-8")
        self.histories[name] = history
        path = self.root / "histories" / f"{name}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(payload)
        schedule_to_start_ms: list[float] = []
        execution_ms: list[float] = []
        scheduled: dict[int, Any] = {}
        started: dict[int, Any] = {}
        for event in history.events:
            if event.HasField("activity_task_scheduled_event_attributes"):
                scheduled[event.event_id] = event.event_time.ToDatetime()
            elif event.HasField("activity_task_started_event_attributes"):
                attrs = event.activity_task_started_event_attributes
                started[event.event_id] = event.event_time.ToDatetime()
                if attrs.scheduled_event_id in scheduled:
                    delta = event.event_time.ToDatetime() - scheduled[attrs.scheduled_event_id]
                    schedule_to_start_ms.append(delta.total_seconds() * 1000)
            elif event.HasField("activity_task_completed_event_attributes"):
                attrs = event.activity_task_completed_event_attributes
                if attrs.started_event_id in started:
                    delta = event.event_time.ToDatetime() - started[attrs.started_event_id]
                    execution_ms.append(delta.total_seconds() * 1000)
        return {
            "event_count": len(history.events),
            "history_bytes": len(payload),
            "history_sha256": sha256_bytes(payload),
            "activity_schedule_to_start_ms": schedule_to_start_ms,
            "activity_execution_ms": execution_ms,
        }

    async def successful(self, name: str, **kwargs: Any) -> dict[str, Any]:
        handle, submit = await self.start_workflow(name, **kwargs)
        started = time.perf_counter()
        result = await handle.result()
        elapsed = time.perf_counter() - started
        history = await self.capture_history(name, handle)
        return {
            "name": name,
            "status": "POC_PASS",
            "workflow_id": handle.id,
            "submission_ms": round(submit * 1000, 3),
            "result_wait_ms": round(elapsed * 1000, 3),
            "result": result,
            "history": history,
            "store": RuntimeStore(self.scenario_root(name)).evidence(),
        }

    async def crash_resume(
        self,
        name: str,
        *,
        stage: str,
        boundary: str,
        graceful: bool = False,
        restart_server: bool = False,
    ) -> dict[str, Any]:
        handle, submit = await self.start_workflow(
            name,
            fault={"stage": stage, "boundary": boundary, "mode": "pause"},
        )
        await self.wait_marker(name, f"{stage}:{boundary}")
        recovery_started = time.perf_counter()
        self.stop_worker(self.v1, kill=not graceful)
        if restart_server:
            self.stop_server(kill=True)
            self.start_server()
        self.start_worker(self.v1)
        if restart_server:
            self.set_current(self.v1)
            client = await self.client()
            handle = client.get_workflow_handle(handle.id)
        result = await handle.result()
        recovery = time.perf_counter() - recovery_started
        history = await self.capture_history(name, handle)
        store = RuntimeStore(self.scenario_root(name)).evidence()
        return {
            "name": name,
            "status": "POC_PASS",
            "workflow_id": handle.id,
            "submission_ms": round(submit * 1000, 3),
            "recovery_ms": round(recovery * 1000, 3),
            "result": result,
            "history": history,
            "store": store,
        }

    async def expected_failure(
        self,
        name: str,
        *,
        stage: str,
        failure_type: str,
        failures: int,
    ) -> dict[str, Any]:
        handle, submit = await self.start_workflow(
            name,
            fault={
                "stage": stage,
                "boundary": "before",
                "mode": "error",
                "type": failure_type,
                "failures": failures,
            },
        )
        error = None
        try:
            await handle.result()
        except WorkflowFailureError as exc:
            error = type(exc.cause).__name__ + ":" + str(exc.cause)
        if error is None:
            raise AssertionError(f"{name} unexpectedly succeeded")
        history = await self.capture_history(name, handle)
        return {
            "name": name,
            "status": "POC_PASS",
            "workflow_id": handle.id,
            "submission_ms": round(submit * 1000, 3),
            "expected_failure_type": failure_type,
            "observed_error": error,
            "history": history,
            "store": RuntimeStore(self.scenario_root(name)).evidence(),
        }

    async def versioning(self) -> dict[str, Any]:
        v1_handle, _ = await self.start_workflow("version-pinned-v1", stage_delay_seconds=0.5)
        await asyncio.sleep(0.8)
        self.start_worker(self.v2)
        self.set_current(self.v2)
        v2_handle, _ = await self.start_workflow("version-current-v2", stage_delay_seconds=0.1)
        v1_result, v2_result = await asyncio.gather(v1_handle.result(), v2_handle.result())
        v1_builds = sorted(
            {value.get("worker_build_id") for value in v1_result["lineage"].values() if value}
        )
        v2_builds = sorted(
            {value.get("worker_build_id") for value in v2_result["lineage"].values() if value}
        )
        if v1_builds != [self.v1] or v2_builds != [self.v2]:
            raise AssertionError({"v1_builds": v1_builds, "v2_builds": v2_builds})
        return {
            "name": "worker_versioning",
            "status": "POC_PASS",
            "v1_workflow_id": v1_handle.id,
            "v2_workflow_id": v2_handle.id,
            "v1_activity_builds": v1_builds,
            "v2_activity_builds": v2_builds,
            "scope": "same Workflow code; deployment routing and PINNED continuity only",
        }

    async def benchmark(self) -> dict[str, Any]:
        samples = []
        for index in range(3):
            await self.successful(f"warmup-{index}")
        for index in range(20):
            sample = await self.successful(f"benchmark-{index}")
            samples.append(sample)
        totals = [row["result_wait_ms"] + row["submission_ms"] for row in samples]
        scheduling = [
            value for row in samples for value in row["history"]["activity_schedule_to_start_ms"]
        ]
        execution = [value for row in samples for value in row["history"]["activity_execution_ms"]]
        return {
            "warmups": 3,
            "measured_workflows": 20,
            "end_to_end_ms": {
                "p50": round(percentile(totals, 0.50), 3),
                "p95": round(percentile(totals, 0.95), 3),
                "max": round(max(totals), 3),
            },
            "activity_schedule_to_start_ms": {
                "p50": round(percentile(scheduling, 0.50), 3),
                "p95": round(percentile(scheduling, 0.95), 3),
                "max": round(max(scheduling), 3),
            },
            "activity_execution_ms": {
                "p50": round(percentile(execution, 0.50), 3),
                "p95": round(percentile(execution, 0.95), 3),
                "max": round(max(execution), 3),
            },
            "history_events": {
                "p50": percentile([row["history"]["event_count"] for row in samples], 0.5),
                "max": max(row["history"]["event_count"] for row in samples),
            },
            "history_bytes": {
                "p50": percentile([row["history"]["history_bytes"] for row in samples], 0.5),
                "max": max(row["history"]["history_bytes"] for row in samples),
            },
        }

    def command_latency(self) -> dict[str, Any]:
        samples = []
        for _ in range(10):
            started = time.perf_counter()
            self._cli("operator", "namespace", "describe")
            samples.append((time.perf_counter() - started) * 1000)
        return {
            "samples": len(samples),
            "p50_ms": round(percentile(samples, 0.5), 3),
            "p95_ms": round(percentile(samples, 0.95), 3),
            "max_ms": round(max(samples), 3),
        }

    def db_latency(self) -> dict[str, Any]:
        path = RuntimeStore(self.scenario_root("baseline")).path
        samples = []
        with sqlite3.connect(path) as db:
            for _ in range(100):
                started = time.perf_counter()
                db.execute("SELECT COUNT(*) FROM activity_attempts").fetchone()
                samples.append((time.perf_counter() - started) * 1000)
        return {
            "samples": len(samples),
            "p50_ms": round(statistics.median(samples), 4),
            "p95_ms": round(percentile(samples, 0.95), 4),
            "max_ms": round(max(samples), 4),
        }

    async def run(self) -> dict[str, Any]:
        self.start_server()
        self.start_worker(self.v1)
        self.set_current(self.v1)
        baseline = await self.successful("baseline")
        self.scenarios.append(baseline)
        await Replayer(workflows=[AutonomousResearchToCIOWorkflow]).replay_workflow(
            self.histories["baseline"]
        )
        self.scenarios.append(
            await self.crash_resume(
                "rag-worker-sigkill",
                stage="retrieve_supporting_rag",
                boundary="during",
            )
        )
        self.scenarios.append(
            await self.crash_resume(
                "provider-before-response",
                stage="acquire_research",
                boundary="before",
            )
        )
        self.scenarios.append(
            await self.crash_resume(
                "provider-ambiguous-response",
                stage="acquire_research",
                boundary="after_provider",
            )
        )
        self.scenarios.append(
            await self.crash_resume(
                "thesis-ambiguous-write",
                stage="reconcile_thesis",
                boundary="after_domain_write",
            )
        )
        self.scenarios.append(
            await self.crash_resume(
                "worker-graceful-restart",
                stage="retrieve_supporting_rag",
                boundary="during",
                graceful=True,
            )
        )
        self.scenarios.append(
            await self.successful(
                "transient-db",
                fault={"stage": "reconcile_thesis", "boundary": "before", "mode": "error", "type": "DB_UNAVAILABLE", "failures": 2},
            )
        )
        self.scenarios.append(
            await self.successful(
                "deepseek-http-500",
                fault={"stage": "acquire_research", "boundary": "before", "mode": "error", "type": "HTTP_500", "failures": 2},
            )
        )
        self.scenarios.append(
            await self.successful(
                "reconciliation-exception",
                fault={"stage": "reconcile_thesis", "boundary": "before", "mode": "error", "type": "RECONCILIATION_EXCEPTION", "failures": 1},
            )
        )
        self.scenarios.append(
            await self.successful(
                "telegram-unavailable",
                fault={"stage": "enqueue_notification", "boundary": "before", "mode": "error", "type": "TELEGRAM_UNAVAILABLE", "failures": 2},
            )
        )
        for name, failure_type, stage in (
            ("cost-cap", "COST_CAP_EXCEEDED", "acquire_research"),
            ("policy-rejection", "POLICY_NOT_ALLOWED", "acquire_research"),
            ("malformed-response", "MALFORMED_RESEARCH", "acquire_research"),
            ("permanent-db", "DB_UNAVAILABLE", "reconcile_thesis"),
        ):
            self.scenarios.append(
                await self.expected_failure(
                    name,
                    stage=stage,
                    failure_type=failure_type,
                    failures=3,
                )
            )
        replay_root = self.scenario_root("identical-replay-first")
        first_handle, _ = await self.start_workflow("identical-replay-first")
        first_result = await first_handle.result()
        second_name = "identical-replay-second"
        second_root = self.scenario_root(second_name)
        if second_root != replay_root:
            second_root.rmdir()
            second_root.symlink_to(replay_root, target_is_directory=True)
        second_handle, _ = await self.start_workflow(second_name)
        second_result = await second_handle.result()
        replay_store = RuntimeStore(replay_root).evidence()
        if second_result["classification"] != "NO_NEW_INFO" or second_result["decision_emitted"]:
            raise AssertionError(second_result)
        self.scenarios.append(
            {
                "name": "identical-replay",
                "status": "POC_PASS",
                "first": first_result,
                "second": second_result,
                "store": replay_store,
            }
        )
        self.scenarios.append(
            await self.crash_resume(
                "service-restart",
                stage="retrieve_supporting_rag",
                boundary="during",
                restart_server=True,
            )
        )
        self.scenarios.append(
            {
                **await self.crash_resume(
                    "host-reboot-simulation",
                    stage="acquire_research",
                    boundary="after_provider",
                    restart_server=True,
                ),
                "scope": "isolated server+Worker process restart; no physical host reboot",
            }
        )
        self.scenarios.append(await self.versioning())
        benchmark = await self.benchmark()
        command_latency = self.command_latency()
        db_latency = self.db_latency()
        deployment = self._cli(
            "worker",
            "deployment",
            "describe",
            "--name",
            self.args.deployment,
            "--output",
            "json",
        ).stdout
        all_passed = all(row["status"] == "POC_PASS" for row in self.scenarios)
        return {
            "schema": "TemporalRuntimeAcceptance@v1",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_sha": self.args.source_sha,
            "authority": "READ_ONLY_ADVISORY",
            "memory_behavior_influence": 0,
            "deployment": {
                "mode": "LOCALHOST_TEMPORAL_CLI_DEVELOPMENT_SERVER",
                "address": self.args.address,
                "namespace": self.args.namespace,
                "task_queue": TASK_QUEUE,
                "deployment_name": self.args.deployment,
                "server_starts": self.server_starts,
                "worker_starts": self.worker_starts,
                "description": json.loads(deployment),
            },
            "scenarios": self.scenarios,
            "history_replay": "POC_PASS",
            "performance": {
                "benchmark": benchmark,
                "temporal_command": command_latency,
                "isolated_sqlite": db_latency,
            },
            "financial_writes": 0,
            "paid_provider_calls": 0,
            "live_database_writes": 0,
            "real_telegram_sends": 0,
            "all_executed_scenarios_passed": all_passed,
        }

    def cleanup(self) -> None:
        for build_id in list(self.workers):
            try:
                self.stop_worker(build_id, kill=True)
            except Exception:
                pass
        try:
            self.stop_server(kill=True)
        except Exception:
            pass
        for handle in self.log_handles:
            handle.close()


async def async_main(args: argparse.Namespace) -> None:
    harness = AcceptanceHarness(args)
    try:
        result = await harness.run()
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(output), "scenarios": len(result["scenarios"])}))
    finally:
        harness.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--temporal-cli", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--address", default="127.0.0.1:17233")
    parser.add_argument("--port", type=int, default=17233)
    parser.add_argument("--namespace", default="tradeai-temporal-poc")
    parser.add_argument("--deployment", default="tradeai-temporal-poc")
    asyncio.run(async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
