# shellcheck shell=bash
# tradeai_venv_python [code_root] — print the interpreter a scheduled job should use.
# Release directories ship no .venv and cron `cd`s into the served CURRENT release, so a bare
# "$PROJ/.venv/bin/python" exists in no release (2026-10-09: rotation_autopilot fell back to system
# python3 and died on `import dotenv` every 15 min). Same order as lib/live_project_root.venv_python:
# TRADEAI_VENV_PYTHON, the crontab-exported $PY, the code root's .venv, the canonical dev venv, python3.
tradeai_venv_python() {
    local root="${1:-.}" c
    for c in "${TRADEAI_VENV_PYTHON:-}" "${PY:-}" "$root/.venv/bin/python" \
             "$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"; do
        case "$(basename -- "${c:-x}")" in
            python|python3|python3.*) [ -x "$c" ] && { printf '%s\n' "$c"; return 0; } ;;
        esac
    done
    command -v python3 || printf 'python3\n'
}
