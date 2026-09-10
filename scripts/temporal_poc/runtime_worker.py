"""Launch one localhost-only Temporal POC Worker from an immutable build identity."""
from __future__ import annotations

import argparse
import asyncio
import json
import os

from temporalio.client import Client
from temporalio.common import VersioningBehavior, WorkerDeploymentVersion
from temporalio.worker import Worker, WorkerDeploymentConfig

from scripts.temporal_poc.contracts import TASK_QUEUE
from scripts.temporal_poc.runtime_activities import RuntimeActivities
from scripts.temporal_poc.temporal_workflow import AutonomousResearchToCIOWorkflow


async def run_worker(args: argparse.Namespace) -> None:
    client = await Client.connect(args.address, namespace=args.namespace)
    activities = RuntimeActivities(args.build_id)
    kwargs = {}
    if args.versioned:
        kwargs["deployment_config"] = WorkerDeploymentConfig(
            version=WorkerDeploymentVersion(
                deployment_name=args.deployment_name,
                build_id=args.build_id,
            ),
            use_worker_versioning=True,
            default_versioning_behavior=VersioningBehavior.PINNED,
        )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AutonomousResearchToCIOWorkflow],
        activities=activities.all(),
        identity=f"tradeai-temporal-poc:{args.build_id}:{os.getpid()}",
        max_concurrent_activities=4,
        max_concurrent_workflow_tasks=4,
        **kwargs,
    )
    print(
        json.dumps(
            {
                "event": "worker_started",
                "pid": os.getpid(),
                "build_id": args.build_id,
                "deployment_name": args.deployment_name if args.versioned else None,
                "task_queue": TASK_QUEUE,
                "namespace": args.namespace,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="127.0.0.1:17233")
    parser.add_argument("--namespace", default="tradeai-temporal-poc")
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--deployment-name", default="tradeai-temporal-poc")
    parser.add_argument("--versioned", action="store_true")
    asyncio.run(run_worker(parser.parse_args()))


if __name__ == "__main__":
    main()
