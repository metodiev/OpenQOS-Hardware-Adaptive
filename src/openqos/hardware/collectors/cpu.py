"""CPU capability and topology collection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openqos.hardware.collectors.common import driver_name
from openqos.hardware.context import CollectionContext
from openqos.hardware.readers import read_flag_list

_CACHE_SIZE_UNITS = {"K": 1, "M": 1024, "G": 1024 * 1024}

_CPU_DIR_RE = re.compile(r"^cpu\d+$")


def collect_cpu(ctx: CollectionContext) -> dict[str, Any] | None:
    """Collect logical CPU records plus a normalised topology summary."""
    cpuinfo = _parse_cpuinfo(ctx.fs.text("proc", "cpuinfo"))
    cpu_root = ("sys", "devices", "system", "cpu")
    cpu_dirs = [
        entry
        for entry in ctx.fs.entries(*cpu_root)
        if entry.is_dir() and _CPU_DIR_RE.match(entry.name)
    ]

    if cpuinfo is None and not cpu_dirs:
        ctx.unavailable_reason("cpu", "/proc/cpuinfo and /sys/devices/system/cpu are missing")
        return None

    logical_cpus = len(cpu_dirs) or len(cpuinfo or {})
    cores: set[tuple[str, str]] = set()
    packages: set[str] = set()
    per_cpu: list[dict[str, Any]] = []

    for index, cpu_dir in enumerate(cpu_dirs):
        package_id = ctx.fs.text(*cpu_dir.parts, "topology", "physical_package_id")
        core_id = ctx.fs.text(*cpu_dir.parts, "topology", "core_id")
        if package_id is not None and core_id is not None:
            cores.add((package_id, core_id))
            packages.add(package_id)
        record: dict[str, Any] = {
            "id": f"cpu{index}",
            "package_id": _as_int(package_id),
            "core_id": _as_int(core_id),
            "max_mhz": _khz_to_mhz(ctx.fs.integer(*cpu_dir.parts, "cpufreq", "cpuinfo_max_freq")),
        }
        online = ctx.fs.text(*cpu_dir.parts, "online")
        record["online"] = online != "0"
        per_cpu.append(record)

    first = cpuinfo.get("0", {}) if cpuinfo else {}
    flags = read_flag_list(
        *(info.get("flags") for info in (cpuinfo or {}).values() if info),
        first.get("features"),
    )
    bugs = read_flag_list(*(info.get("bugs") for info in (cpuinfo or {}).values() if info))
    microcode = next(
        (info["microcode"] for info in (cpuinfo or {}).values() if info.get("microcode")), None
    )

    max_freq_khz = ctx.fs.integer(*cpu_root, "cpu0", "cpufreq", "cpuinfo_max_freq")
    min_freq_khz = ctx.fs.integer(*cpu_root, "cpu0", "cpufreq", "cpuinfo_min_freq")

    threads_per_core = None
    if cores and logical_cpus:
        threads_per_core = max(1, logical_cpus // len(cores))

    return {
        "architecture": first.get("architecture") or _machine_arch(),
        "vendors": _cpu_vendors(cpuinfo),
        "model_name": first.get("model name") or first.get("Processor") or first.get("cpu model"),
        "logical_cpus": logical_cpus,
        "physical_cores": len(cores) or None,
        "sockets": len(packages) or None,
        "threads_per_core": threads_per_core,
        "frequency_mhz": {
            "min": _khz_to_mhz(min_freq_khz),
            "max": _khz_to_mhz(max_freq_khz),
        },
        "cache": _collect_cache(ctx),
        "flags": flags,
        "bugs": bugs,
        "microcode": microcode,
        "numa_nodes": len(ctx.fs.subdirectories(*cpu_root, "cpu0", "node")) or None,
        "cpufreq_driver": ctx.fs.text(*cpu_root, "cpu0", "cpufreq", "scaling_driver")
        or driver_name(ctx, ctx.fs.path(*cpu_root, "cpu0", "cpufreq"), root=ctx.fs.root),
        "per_cpu": per_cpu,
    }


def _cpu_vendors(cpuinfo: dict[str, dict[str, str]] | None) -> list[str]:
    if not cpuinfo:
        return []
    vendors = {info["vendor_id"] for info in cpuinfo.values() if "vendor_id" in info}
    if not vendors:
        vendors = {
            info["CPU implementer"] for info in cpuinfo.values() if "CPU implementer" in info
        }
    return sorted(vendors)


def _parse_cpuinfo(raw: str | None) -> dict[str, dict[str, str]] | None:
    """Parse ``/proc/cpuinfo`` into ``{processor_id: {field: value}}``."""
    if raw is None:
        return None
    records: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                key = current.get("processor", str(len(records)))
                records[key] = current
                current = {}
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        current[key.strip()] = value.strip()
    if current:
        records[current.get("processor", str(len(records)))] = current
    return records or None


def _collect_cache(ctx: CollectionContext) -> dict[str, int]:
    cache: dict[str, int] = {}
    cache_root = ("sys", "devices", "system", "cpu", "cpu0", "cache")
    for index_dir in ctx.fs.subdirectories(*cache_root):
        level = ctx.fs.text(*index_dir.parts, "level")
        kind = ctx.fs.text(*index_dir.parts, "type")
        size = _parse_cache_size(ctx.fs.text(*index_dir.parts, "size"))
        if not level or not kind or size is None:
            continue
        cache[f"l{level}{_cache_suffix(kind)}_kib"] = size
    return cache


def _cache_suffix(kind: str) -> str:
    lowered = kind.lower()
    if "instruction" in lowered:
        return "i"
    if "unified" in lowered:
        return "u"
    return "d"


def _parse_cache_size(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^(\d+)([KMG])?$", value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "K"
    return amount * _CACHE_SIZE_UNITS[unit]


def _khz_to_mhz(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value // 1000


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _machine_arch() -> str:
    from platform import machine

    return machine()


def cpu_dir_of(root: Path, name: str) -> Path:  # pragma: no cover - convenience helper
    return root / "sys" / "devices" / "system" / "cpu" / name
