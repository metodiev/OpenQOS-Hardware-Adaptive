"""Memory information from ``/proc/meminfo``."""

from __future__ import annotations

from typing import Any

from openqos.hardware.context import CollectionContext

_KEYS = {
    "MemTotal": "total_kib",
    "MemFree": "free_kib",
    "MemAvailable": "available_kib",
    "Buffers": "buffers_kib",
    "Cached": "cached_kib",
    "SwapTotal": "swap_total_kib",
    "SwapFree": "swap_free_kib",
}


def collect_memory(ctx: CollectionContext) -> dict[str, Any] | None:
    raw = ctx.fs.text("proc", "meminfo")
    if raw is None:
        ctx.unavailable_reason("memory", "/proc/meminfo is not readable")
        return None

    values: dict[str, Any] = dict.fromkeys(_KEYS.values())
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        field = _KEYS.get(key.strip())
        if field is None:
            continue
        amount = rest.strip().split()
        if not amount:
            continue
        try:
            values[field] = int(amount[0])
        except ValueError:
            continue

    if values["total_kib"] is None:
        ctx.warn("memory.missing-total", "MemTotal is missing from /proc/meminfo", "memory")
        return None

    total = values["total_kib"]
    values["total_mib"] = total // 1024
    # DMI-based module detail needs root and a helper binary; report it honestly
    # instead of guessing.
    values["modules"] = []
    ctx.unavailable_reason(
        "memory.modules",
        "per-module type/speed requires DMI access (dmidecode) which is not used "
        "during a read-only unprivileged scan",
    )
    return values
