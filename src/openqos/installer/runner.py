"""Execution wrapper for Anaconda, plus the machine-readable install report."""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path
from typing import Any

from openqos.errors import InstallError
from openqos.installer.plan import render_kickstart, validate_install_plan

DEFAULT_KICKSTART = Path("/var/lib/openqos/install.ks")
DEFAULT_LOG = Path("/var/log/openqos/install.log")
DEFAULT_REPORT = Path("/var/lib/openqos/install-report.json")


def write_kickstart(plan: dict[str, Any], path: Path = DEFAULT_KICKSTART) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_kickstart(plan), encoding="utf-8")
    return path


def confirm_target(plan: dict[str, Any], confirmation: str | None) -> None:
    """Require the operator to type the exact disk name before anything is erased."""
    problems = validate_install_plan(plan)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise InstallError(f"install plan is invalid:\n{joined}")
    token = plan["target"]["confirmation_token"]
    if confirmation != token:
        raise InstallError(
            f"target confirmation required: pass --confirm {token} "
            f"to erase {plan['target']['disk']}"
        )


def run_installer(
    plan: dict[str, Any],
    *,
    confirmation: str | None,
    execute: bool = False,
    kickstart_path: Path = DEFAULT_KICKSTART,
    log_path: Path = DEFAULT_LOG,
    report_path: Path = DEFAULT_REPORT,
    runner: Any = None,
) -> dict[str, Any]:
    """Write the Kickstart and, only when ``execute`` is set, run Anaconda."""
    confirm_target(plan, confirmation)
    runner = runner or subprocess.run
    kickstart = write_kickstart(plan, kickstart_path)
    command = ["anaconda", "--kickstart", str(kickstart), "--text"]

    if not execute:
        return {
            "executed": False,
            "command": command,
            "kickstart_path": str(kickstart),
            "target": plan["target"]["disk"],
            "message": "dry run: re-run with --execute to start Anaconda",
        }

    started = _now()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = runner(
            command,
            check=False,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    report = {
        "report_version": "1.0.0",
        "started_at": started,
        "finished_at": _now(),
        "target": plan["target"]["disk"],
        "profile": plan.get("source_profile"),
        "policy": plan.get("policy"),
        "status": "succeeded" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "kickstart_path": str(kickstart),
        "log_path": str(log_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if completed.returncode != 0:
        raise InstallError(
            f"Anaconda failed with exit code {completed.returncode}; see {log_path}"
        )
    return report


def _now() -> str:
    return _dt.datetime.now(tz=_dt.UTC).replace(microsecond=0).isoformat()
