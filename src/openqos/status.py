"""Runtime status of the last discovery and optimization run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIRECTORY = Path("/var/lib/openqos")
INVENTORY_FILE = "inventory.json"
PROFILE_FILE = "profile.json"
PLAN_FILE = "plan.json"
SUMMARY_FILE = "summary.txt"


def load_state(state_directory: Path | None = None) -> dict[str, Any]:
    """Load whichever of the three documents exist, without failing on gaps."""
    directory = Path(state_directory) if state_directory else DEFAULT_STATE_DIRECTORY
    state: dict[str, Any] = {"state_directory": str(directory)}
    for key, name in (
        ("inventory", INVENTORY_FILE),
        ("profile", PROFILE_FILE),
        ("plan", PLAN_FILE),
    ):
        path = directory / name
        try:
            state[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state[key] = None
    return state


def build_status(state: dict[str, Any]) -> dict[str, Any]:
    """Reduce the stored documents to a compact, printable status."""
    inventory = state.get("inventory") or {}
    profile = state.get("profile") or {}
    plan = state.get("plan") or {}

    machine = profile.get("machine") or {}
    cpu = profile.get("cpu") or {}
    memory = profile.get("memory") or {}
    graphics = profile.get("graphics") or {}
    storage = profile.get("storage") or {}
    network = profile.get("network") or {}
    firmware = machine.get("firmware") or {}
    selected = plan.get("selected_profile") or {}
    summary = plan.get("summary") or {}

    issues: list[str] = list(plan.get("notices") or [])
    for decision in plan.get("decisions") or []:
        if decision.get("status") in {"skip", "manual"}:
            issues.append(f"{decision.get('title')}: {decision.get('rationale')}")

    return {
        "has_inventory": bool(inventory),
        "has_profile": bool(profile),
        "has_plan": bool(plan),
        "generated_at": inventory.get("generated_at"),
        "privacy_mode": inventory.get("privacy_mode"),
        "os": ((inventory.get("host") or {}).get("os") or {}).get("pretty_name"),
        "kernel": ((inventory.get("host") or {}).get("kernel") or {}).get("release"),
        "machine": {
            "form_factor": machine.get("form_factor"),
            "vendor": cpu.get("vendor"),
            "cpu": cpu.get("model"),
            "logical_cpus": cpu.get("logical_cpus"),
            "physical_cores": cpu.get("physical_cores"),
            "memory_mib": memory.get("total_mib"),
            "graphics": graphics.get("drivers") or [],
            "hybrid_graphics": bool(graphics.get("hybrid")),
            "storage_primary": storage.get("primary"),
            "storage_devices": [
                device.get("name") for device in storage.get("devices") or []
            ],
            "wired": bool(network.get("wired")),
            "wireless": bool(network.get("wireless")),
            "boot_mode": firmware.get("boot_mode"),
            "secure_boot": firmware.get("secure_boot"),
            "virtual_machine": bool(machine.get("is_virtual_machine")),
        },
        "profile_id": selected.get("profile_id"),
        "fallback": bool(selected.get("fallback")),
        "policy": plan.get("policy"),
        "decisions": summary.get("total"),
        "by_status": summary.get("by_status") or {},
        "packages": summary.get("packages") or [],
        "issues": issues,
        "unavailable": profile.get("unavailable") or [],
    }


def render_status(status: dict[str, Any]) -> str:
    """Render the status as the text shown in the live session and logs."""
    if not status["has_inventory"]:
        return (
            "OpenQOS: no hardware scan has run yet.\n"
            "Run 'openqos hardware scan --output /var/lib/openqos/inventory.json'.\n"
        )

    machine = status["machine"]
    lines = [
        "OpenQOS hardware report",
        "=======================",
        f"generated      : {status['generated_at']}",
        f"system         : {status['os'] or 'unknown'} (kernel {status['kernel'] or '?'})",
        f"machine        : {machine['form_factor']}"
        + (" (virtual machine)" if machine["virtual_machine"] else ""),
        f"cpu            : {machine['cpu'] or 'unknown'} [{machine['vendor']}], "
        f"{machine['logical_cpus']} logical / {machine['physical_cores']} cores",
        f"memory         : {machine['memory_mib']} MiB",
        f"graphics       : {', '.join(machine['graphics']) or 'none'}"
        + (" (hybrid)" if machine["hybrid_graphics"] else ""),
        f"storage        : {', '.join(machine['storage_devices']) or 'none'} "
        f"[{machine['storage_primary']}]",
        f"network        : wired={machine['wired']} wireless={machine['wireless']}",
        f"firmware       : {machine['boot_mode']}, secure boot {machine['secure_boot']}",
        "",
    ]
    if status["has_plan"]:
        counts = status["by_status"]
        lines.extend(
            [
                f"profile        : {status['profile_id']}"
                + (" (fallback)" if status["fallback"] else ""),
                f"policy         : {status['policy']}",
                f"decisions      : {status['decisions']} total, "
                f"plan={counts.get('plan', 0)} keep={counts.get('keep', 0)} "
                f"skip={counts.get('skip', 0)} manual={counts.get('manual', 0)}",
                f"packages       : {', '.join(status['packages']) or 'none'}",
                "",
            ]
        )
        if status["issues"]:
            lines.append("notes and compatibility issues:")
            lines.extend(f"  - {issue}" for issue in status["issues"])
            lines.append("")
    else:
        lines.extend(["profile        : not generated yet", ""])

    if status["unavailable"]:
        lines.append("not detected: " + ", ".join(status["unavailable"]))
        lines.append("")
    lines.append(
        "Full documents: inventory.json, profile.json and plan.json in "
        "/var/lib/openqos. Nothing has been changed on this system."
    )
    return "\n".join(lines) + "\n"


def write_summary(status: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_status(status), encoding="utf-8")
    return path
