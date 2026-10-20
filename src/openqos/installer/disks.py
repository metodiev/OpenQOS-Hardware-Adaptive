"""Read-only disk enumeration and target validation for the installer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openqos.hardware.readers import FsRoot

#: Refuse targets smaller than this; Fedora KDE needs roughly 12 GiB.
MINIMUM_DISK_GIB = 20

_LIVE_MOUNT_PREFIXES = ("/run/initramfs/live", "/run/rootfsbase", "/run/install/repo")


@dataclass
class DiskCandidate:
    name: str
    path: str
    size_gib: float
    model: str | None
    removable: bool
    rotational: bool | None
    transport: str
    partitions: list[str] = field(default_factory=list)
    mounted: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.reasons

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "size_gib": self.size_gib,
            "model": self.model,
            "removable": self.removable,
            "rotational": self.rotational,
            "transport": self.transport,
            "partitions": list(self.partitions),
            "mounted": dict(self.mounted),
            "eligible": self.eligible,
            "reasons": list(self.reasons),
        }


def enumerate_disks(
    root: Path | None = None, *, mount_table: Path | None = None
) -> list[DiskCandidate]:
    """List block devices with the reasons they may or may not be installed to."""
    fs = FsRoot(root if root is not None else Path("/"))
    mounts = _read_mounts(fs, mount_table)
    live_devices = {
        _device_base(device)
        for device, mountpoint in mounts.items()
        if mountpoint.startswith(_LIVE_MOUNT_PREFIXES)
    }
    root_device = next(
        (_device_base(device) for device, mountpoint in mounts.items() if mountpoint == "/"),
        "",
    )

    candidates: list[DiskCandidate] = []
    for entry in fs.subdirectories("sys", "block"):
        name = entry.name
        if name.startswith(("loop", "ram", "zram", "fd")):
            continue
        sectors = fs.integer(*entry.parts, "size")
        if not sectors:
            continue
        partitions = [
            child.name
            for child in fs.subdirectories(*entry.parts)
            if child.name.startswith(name) and fs.integer(*child.parts, "size")
        ]
        mapped = {
            device: mountpoint
            for device, mountpoint in mounts.items()
            if device == f"/dev/{name}" or device.startswith(f"/dev/{name}")
        }
        candidate = DiskCandidate(
            name=name,
            path=f"/dev/{name}",
            size_gib=round(sectors * 512 / (1024**3), 2),
            model=fs.text(*entry.parts, "device", "model") or None,
            removable=fs.text(*entry.parts, "removable") == "1",
            rotational=_optional_bool(fs.text(*entry.parts, "queue", "rotational")),
            transport=_transport(fs, entry),
            partitions=partitions,
            mounted=mapped,
        )
        candidate.reasons = _reasons_for(candidate, live_devices, root_device)
        candidates.append(candidate)

    return sorted(candidates, key=lambda candidate: candidate.name)


def _reasons_for(
    candidate: DiskCandidate, live_devices: set[str], root_device: str
) -> list[str]:
    reasons: list[str] = []
    if candidate.name.startswith("sr"):
        reasons.append("optical drive")
    if candidate.removable:
        reasons.append("removable media")
    if candidate.size_gib < MINIMUM_DISK_GIB:
        reasons.append(f"smaller than {MINIMUM_DISK_GIB} GiB")
    if candidate.name in live_devices:
        reasons.append("hosts the running live medium")
    if candidate.name == root_device:
        reasons.append("hosts the running root filesystem")
    if candidate.mounted and not reasons:
        reasons.append("has mounted filesystems")
    if candidate.partitions and not reasons:
        reasons.append("contains existing partitions")
    return sorted(set(reasons))


def _read_mounts(fs: FsRoot, mount_table: Path | None) -> dict[str, str]:
    if mount_table is not None:
        try:
            content = mount_table.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
    else:
        content = fs.text("proc", "mounts") or ""
    mounts: dict[str, str] = {}
    for line in content.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        device, mountpoint = parts[0], parts[1]
        if not device.startswith("/dev/"):
            continue
        mounts[device] = mountpoint
    return mounts


def _device_base(device: str) -> str:
    """Map /dev/nvme0n1p1 or /dev/sda2 to the disk name it belongs to."""
    name = Path(device).name
    if not name:
        return ""
    if name.startswith("nvme"):
        return name.split("p")[0]
    if name.startswith("mmcblk"):
        return name.split("p")[0]
    index = 0
    while index < len(name) and not name[index].isdigit():
        index += 1
    return name[:index] or name


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "1"


def _transport(fs: FsRoot, entry: Path) -> str:
    relative = entry.relative_to(fs.root)
    name = entry.name
    if name.startswith("nvme"):
        return "nvme"
    if name.startswith("mmcblk"):
        return "mmc"
    uevent = fs.key_values(*relative.parts, "device", "uevent")
    driver = uevent.get("DRIVER") or fs.link_name(*relative.parts, "device", "driver") or ""
    if driver in {"usb-storage", "uas"}:
        return "usb"
    if driver in {"ahci", "ata_piix", "libata"}:
        return "sata"
    if driver.startswith("virtio"):
        return "virtio"
    return "unknown"
