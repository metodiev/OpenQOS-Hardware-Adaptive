"""Block device and storage controller detection."""

from __future__ import annotations

from typing import Any

from openqos.hardware.collectors.common import driver_name
from openqos.hardware.context import CollectionContext

_BLOCK_ROOT = ("sys", "block")
_VIRTUAL_PREFIXES = ("loop", "ram", "zram", "fd")
_OPTICAL_PREFIXES = ("sr",)


def collect_storage(ctx: CollectionContext) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for entry in ctx.fs.subdirectories(*_BLOCK_ROOT):
        name = entry.name
        if name.startswith(_VIRTUAL_PREFIXES):
            continue
        record = _block_record(ctx, entry)
        if record is not None:
            devices.append(record)

    if not devices:
        ctx.unavailable_reason("storage", "no physical block devices were found under /sys/block")
    return devices


def _block_record(ctx: CollectionContext, entry: Any) -> dict[str, Any] | None:
    name = entry.name
    sectors = ctx.fs.integer(*entry.parts, "size")
    if sectors is None:
        ctx.warn(
            "storage.unreadable",
            f"block device {name} does not expose a size attribute",
            "storage",
        )
        return None

    rotational = ctx.fs.text(*entry.parts, "queue", "rotational")
    removable = ctx.fs.text(*entry.parts, "removable")
    transport = _transport(ctx, entry)
    size_bytes = sectors * 512
    return {
        "name": name,
        "path": f"/dev/{name}",
        "size_bytes": size_bytes,
        "size_gib": round(size_bytes / (1024**3), 2),
        "model": ctx.fs.text(*entry.parts, "device", "model")
        or ctx.fs.text(*entry.parts, "device", "name"),
        "serial": ctx.redact(ctx.fs.text(*entry.parts, "device", "serial")),
        "rotational": None if rotational is None else rotational == "1",
        "removable": None if removable is None else removable == "1",
        "optical": name.startswith(_OPTICAL_PREFIXES),
        "transport": transport,
        "driver": driver_name(ctx, ctx.fs.path(*entry.parts), root=ctx.fs.root)
        or ctx.fs.key_values(*entry.parts, "device", "uevent").get("DRIVER"),
        "partitions": _partitions(ctx, entry),
    }


def _transport(ctx: CollectionContext, entry: Any) -> str:
    name = entry.name
    if name.startswith("nvme"):
        return "nvme"
    if name.startswith("mmcblk"):
        return "mmc"
    device_uevent = ctx.fs.key_values(*entry.parts, "device", "uevent")
    driver = ctx.fs.link_name(*entry.parts, "device", "driver") or device_uevent.get("DRIVER") or ""
    if driver in {"usb-storage", "uas"}:
        return "usb"
    if driver in {"ata_piix", "ahci", "libata"}:
        return "sata"
    if driver.startswith("virtio"):
        return "virtio"
    return "unknown"


def _partitions(ctx: CollectionContext, entry: Any) -> list[dict[str, Any]]:
    partitions: list[dict[str, Any]] = []
    for child in ctx.fs.subdirectories(*entry.parts):
        if not child.name.startswith(entry.name):
            continue
        sectors = ctx.fs.integer(*child.parts, "size")
        if sectors is None:
            continue
        partitions.append(
            {
                "name": child.name,
                "path": f"/dev/{child.name}",
                "size_bytes": sectors * 512,
            }
        )
    return partitions
