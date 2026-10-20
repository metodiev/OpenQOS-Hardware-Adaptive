"""PCI device enumeration, including graphics and audio devices."""

from __future__ import annotations

from typing import Any

from openqos.hardware.collectors.common import pci_category, pci_class_code
from openqos.hardware.context import CollectionContext

_PCI_ROOT = ("sys", "bus", "pci", "devices")


def collect_pci(ctx: CollectionContext) -> list[dict[str, Any]]:
    return _collect_pci_devices(ctx)


def _collect_pci_devices(ctx: CollectionContext) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for device_dir in ctx.fs.subdirectories(*_PCI_ROOT):
        uevent = ctx.fs.key_values(*device_dir.parts, "uevent")
        class_code = pci_class_code(uevent, ctx.fs.text(*device_dir.parts, "class"))
        vendor = uevent.get("PCI_ID", "").split(":")[0] or ctx.fs.text(*device_dir.parts, "vendor")
        device = uevent.get("PCI_ID", "").split(":")[-1] or ctx.fs.text(*device_dir.parts, "device")
        driver = ctx.fs.link_name(*device_dir.parts, "driver") or uevent.get("DRIVER")
        record: dict[str, Any] = {
            "id": f"pci:{device_dir.name}",
            "slot": uevent.get("PCI_SLOT_NAME", device_dir.name),
            "vendor_id": _normalise_hex(vendor),
            "device_id": _normalise_hex(device),
            "subsystem_vendor_id": _normalise_hex(
                uevent.get("PCI_SUBSYS_ID", "").split(":")[0]
                or ctx.fs.text(*device_dir.parts, "subsystem_vendor")
            ),
            "subsystem_device_id": _normalise_hex(
                uevent.get("PCI_SUBSYS_ID", "").split(":")[-1]
                or ctx.fs.text(*device_dir.parts, "subsystem_device")
            ),
            "class_code": class_code,
            "category": pci_category(class_code),
            "driver": driver,
            "driver_version": _driver_version(ctx, driver),
            "kernel_modules": [driver] if driver else [],
        }
        if record["vendor_id"] is None and record["device_id"] is None:
            ctx.warn(
                "pci.unidentified",
                f"PCI device {device_dir.name} exposes no vendor/device identifiers",
                "pci",
            )
        devices.append(record)
    if not devices:
        ctx.unavailable_reason("pci", "no PCI devices were found under /sys/bus/pci/devices")
    return devices


def _driver_version(ctx: CollectionContext, driver: str | None) -> str | None:
    if not driver:
        return None
    return ctx.fs.text("sys", "module", driver, "version")


def _normalise_hex(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    return cleaned or None


def collect_graphics(
    ctx: CollectionContext, pci_devices: list[dict[str, Any]]
) -> dict[str, Any]:
    """Describe graphics adapters, including integrated/discrete/hybrid detection."""
    graphics: list[dict[str, Any]] = []
    for device in pci_devices:
        class_code = device.get("class_code") or ""
        if not class_code.startswith("03"):
            continue
        record = {
            "id": device["id"],
            "slot": device["slot"],
            "vendor_id": device["vendor_id"],
            "device_id": device["device_id"],
            "class_code": class_code,
            "category": device["category"],
            "driver": device["driver"],
            "kernel_modules": device["kernel_modules"],
            "memory_mib": _vram_mib(ctx, device),
        }
        graphics.append(record)

    if graphics:
        drivers = {gpu["driver"] for gpu in graphics if gpu["driver"]}
        vendors = {gpu["vendor_id"] for gpu in graphics if gpu["vendor_id"]}
        primary = _pick_primary(graphics, drivers)
        summary = {
            "adapter_count": len(graphics),
            "vendor_count": len(vendors),
            "hybrid_graphics": len(vendors) > 1,
            "primary_adapter": primary,
            "adapters": graphics,
        }
    else:
        ctx.unavailable_reason("graphics", "no PCI display-class device was detected")
        summary = {
            "adapter_count": 0,
            "vendor_count": 0,
            "hybrid_graphics": False,
            "primary_adapter": None,
            "adapters": [],
        }
    return summary


def _pick_primary(graphics: list[dict[str, Any]], drivers: set[str]) -> str | None:
    # Integrated adapters normally drive the internal panel; prefer them.
    for preferred in ("i915", "xe", "amdgpu", "radeon", "nouveau", "nvidia"):
        if preferred in drivers:
            return preferred
    return next((gpu["driver"] for gpu in graphics if gpu["driver"]), None)


def _vram_mib(ctx: CollectionContext, device: dict[str, Any]) -> int | None:
    """Read VRAM size for AMD devices; other vendors do not expose it in sysfs."""
    slot = device.get("slot")
    if not slot:
        return None
    for card in ctx.fs.subdirectories("sys", "class", "drm"):
        uevent = ctx.fs.key_values(*card.parts, "device", "uevent")
        if uevent.get("PCI_SLOT_NAME") != slot:
            continue
        total = ctx.fs.integer(*card.parts, "device", "mem_info_vram_total")
        if total:
            return total // (1024 * 1024)
    return None
