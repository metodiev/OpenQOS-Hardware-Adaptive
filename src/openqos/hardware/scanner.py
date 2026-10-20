"""Hardware inventory orchestration."""

from __future__ import annotations

import datetime as _dt
import platform as _platform
from pathlib import Path
from typing import Any

from openqos import HARDWARE_SCHEMA_VERSION, __version__
from openqos.hardware.collectors.cpu import collect_cpu
from openqos.hardware.collectors.memory import collect_memory
from openqos.hardware.collectors.network import collect_network
from openqos.hardware.collectors.pci import collect_graphics, collect_pci
from openqos.hardware.collectors.peripherals import (
    collect_audio,
    collect_bluetooth,
    collect_cameras,
    collect_input_devices,
)
from openqos.hardware.collectors.platform_info import collect_platform
from openqos.hardware.collectors.power import collect_power
from openqos.hardware.collectors.storage import collect_storage
from openqos.hardware.collectors.usb import collect_usb
from openqos.hardware.context import CollectionContext


def scan(root: Path | None = None, *, privacy: bool = False) -> dict[str, Any]:
    """Run a complete read-only hardware scan and return a JSON-serialisable document."""
    ctx = CollectionContext.create(root, privacy=privacy)

    pci_devices = collect_pci(ctx)
    document: dict[str, Any] = {
        "schema_version": HARDWARE_SCHEMA_VERSION,
        "generated_at": _dt.datetime.now(tz=_dt.UTC).replace(microsecond=0).isoformat(),
        "privacy_mode": privacy,
        "tool": {
            "name": "openqos",
            "version": __version__,
            "python": _platform.python_version(),
        },
        "host": collect_platform(ctx),
        "cpu": collect_cpu(ctx),
        "memory": collect_memory(ctx),
        "graphics": collect_graphics(ctx, pci_devices),
        "pci_devices": pci_devices,
        "usb_devices": collect_usb(ctx),
        "storage": collect_storage(ctx),
        "network": collect_network(ctx),
        "audio": collect_audio(ctx),
        "bluetooth": collect_bluetooth(ctx),
        "cameras": collect_cameras(ctx),
        "input_devices": collect_input_devices(ctx),
        "power": collect_power(ctx),
        "kernel_modules": _kernel_modules(ctx),
        "warnings": sorted(ctx.warnings, key=lambda item: (item["source"], item["code"])),
        "unavailable": sorted(ctx.unavailable, key=lambda item: item["collector"]),
    }
    return document


def _kernel_modules(ctx: CollectionContext) -> list[str]:
    raw = ctx.fs.text("proc", "modules")
    if raw is None:
        ctx.unavailable_reason("kernel_modules", "/proc/modules is not readable")
        return []
    modules = []
    for line in raw.splitlines():
        parts = line.split()
        if parts:
            modules.append(parts[0])
    return sorted(modules)
