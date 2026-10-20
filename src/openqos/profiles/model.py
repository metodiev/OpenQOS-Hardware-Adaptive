"""Normalised hardware profiles.

A profile converts the raw inventory into the small, stable vocabulary the rule
engine and optimizer operate on. It never invents data: anything that could not
be detected is either ``None`` or listed in ``unavailable``.
"""

from __future__ import annotations

from typing import Any

from openqos import HARDWARE_SCHEMA_VERSION
from openqos.errors import ProfileError

PROFILE_SCHEMA_VERSION = "1.0.0"

_LOW_MEMORY_MIB = 4096
_HIGH_MEMORY_MIB = 16384

_CPU_VENDORS = {
    "GenuineIntel": "intel",
    "AuthenticAMD": "amd",
}

_INTEGRATED_GPU_VENDORS = {"8086"}
_DISCRETE_GPU_VENDORS = {"10de"}


def build_profile(inventory: dict[str, Any]) -> dict[str, Any]:
    """Build a normalised profile from a hardware inventory document."""
    if not isinstance(inventory, dict):
        raise ProfileError("hardware inventory must be a JSON object")
    version = inventory.get("schema_version")
    if version != HARDWARE_SCHEMA_VERSION:
        raise ProfileError(
            f"unsupported inventory schema_version {version!r}; "
            f"expected {HARDWARE_SCHEMA_VERSION!r}"
        )
    for key in ("host", "graphics", "storage", "network", "power", "memory"):
        if key not in inventory:
            raise ProfileError(f"hardware inventory is missing {key!r}")

    host = _mapping(inventory.get("host"))
    cpu = _mapping(inventory.get("cpu"))
    memory = _mapping(inventory.get("memory"))
    graphics = _mapping(inventory.get("graphics"))
    storage_devices = _list(inventory.get("storage"))
    network_interfaces = _list(inventory.get("network"))
    power = _mapping(inventory.get("power"))

    batteries = power.get("batteries") or []
    has_battery = bool(batteries)

    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source_inventory": {
            "schema_version": version,
            "generated_at": inventory.get("generated_at"),
            "privacy_mode": bool(inventory.get("privacy_mode")),
        },
        "machine": {
            "form_factor": "laptop"
            if has_battery
            else ("desktop" if storage_devices else "unknown"),
            "is_virtual_machine": bool(
                _mapping(host.get("virtualization")).get("is_virtual_machine")
            ),
            "firmware": {
                "boot_mode": _mapping(host.get("firmware")).get("boot_mode") or "unknown",
                "secure_boot": _mapping(host.get("firmware")).get("secure_boot") or "unknown",
            },
            "os": {
                "id": _mapping(host.get("os")).get("id"),
                "version_id": _mapping(host.get("os")).get("version_id"),
            },
            "architecture": cpu.get("architecture"),
        },
        "cpu": _cpu_section(cpu),
        "memory": _memory_section(memory),
        "graphics": _graphics_section(graphics),
        "storage": _storage_section(storage_devices),
        "network": _network_section(network_interfaces),
        "power": _power_section(power, has_battery),
        "audio": {"card_count": len(_list(_mapping(inventory.get("audio")).get("cards")))},
        "peripherals": {
            "bluetooth_adapters": len(_list(inventory.get("bluetooth"))),
            "cameras": len(_list(inventory.get("cameras"))),
            "input_devices": len(_list(inventory.get("input_devices"))),
        },
        "unavailable": sorted(
            {
                entry.get("collector", "")
                for entry in _list(inventory.get("unavailable"))
                if isinstance(entry, dict)
            }
        ),
        "warning_count": len(_list(inventory.get("warnings"))),
    }
    return profile


def _cpu_section(cpu: dict[str, Any]) -> dict[str, Any]:
    vendors = [_str(value) for value in _list(cpu.get("vendors"))]
    vendor = next(
        (_CPU_VENDORS[name] for name in vendors if name in _CPU_VENDORS),
        "other" if vendors else "unknown",
    )
    flags = {_str(flag) for flag in _list(cpu.get("flags"))}
    return {
        "vendor": vendor,
        "vendors_raw": vendors,
        "model": cpu.get("model_name"),
        "logical_cpus": int(cpu.get("logical_cpus") or 0),
        "physical_cores": cpu.get("physical_cores"),
        "threads_per_core": cpu.get("threads_per_core"),
        "sockets": cpu.get("sockets"),
        "cpufreq_driver": cpu.get("cpufreq_driver"),
        "numa_nodes": cpu.get("numa_nodes"),
        "features": {
            "avx2": "avx2" in flags,
            "avx512f": "avx512f" in flags,
            "aes": "aes" in flags,
            "virt_host": bool({"vmx", "svm"} & flags),
        },
    }


def _memory_section(memory: dict[str, Any]) -> dict[str, Any]:
    total_mib = int(memory.get("total_mib") or 0)
    if total_mib == 0:
        tier = "unknown"
    elif total_mib < _LOW_MEMORY_MIB:
        tier = "low"
    elif total_mib >= _HIGH_MEMORY_MIB:
        tier = "high"
    else:
        tier = "standard"
    swap_mib = int(memory.get("swap_total_kib") or 0) // 1024
    return {
        "total_mib": total_mib,
        "tier": tier,
        "swap_total_mib": swap_mib,
        "has_swap": swap_mib > 0,
    }


def _graphics_section(graphics: dict[str, Any]) -> dict[str, Any]:
    adapters = []
    for adapter in _list(graphics.get("adapters")):
        if not isinstance(adapter, dict):
            continue
        vendor_id = _str(adapter.get("vendor_id")) if adapter.get("vendor_id") else None
        adapters.append(
            {
                "vendor_id": vendor_id,
                "driver": adapter.get("driver"),
                "memory_mib": adapter.get("memory_mib"),
                "kind": _gpu_kind(vendor_id, _str(adapter.get("driver"))),
            }
        )
    drivers = sorted({str(adapter["driver"]) for adapter in adapters if adapter["driver"]})
    vendor_ids = sorted(
        {str(adapter["vendor_id"]) for adapter in adapters if adapter["vendor_id"]}
    )
    return {
        "adapter_count": len(adapters),
        "adapters": adapters,
        "hybrid": len(vendor_ids) > 1,
        "vendor_ids": vendor_ids,
        "drivers": drivers,
        "primary_driver": graphics.get("primary_adapter"),
        "requires_third_party_driver": "nvidia" in drivers,
    }


def _gpu_kind(vendor_id: str | None, driver: str) -> str:
    if vendor_id in _INTEGRATED_GPU_VENDORS:
        return "integrated"
    if vendor_id in _DISCRETE_GPU_VENDORS:
        return "discrete"
    if driver in {"amdgpu", "radeon", "i915", "xe"}:
        return "integrated"
    return "unknown"


def _storage_section(storage_devices: list[Any]) -> dict[str, Any]:
    devices = []
    for device in storage_devices:
        if not isinstance(device, dict):
            continue
        devices.append(
            {
                "name": device.get("name"),
                "transport": device.get("transport") or "unknown",
                "rotational": device.get("rotational"),
                "removable": device.get("removable"),
                "size_gib": device.get("size_gib"),
            }
        )
    transports = sorted({str(device["transport"]) for device in devices})
    rotational = [device["rotational"] for device in devices]
    if not devices:
        primary = "unknown"
    elif any(value is False for value in rotational):
        primary = "ssd"
    elif all(value is True for value in rotational):
        primary = "hdd"
    else:
        primary = "unknown"
    return {
        "devices": devices,
        "device_count": len(devices),
        "primary": primary,
        "transports": transports,
        "has_nvme": "nvme" in transports,
        "has_removable": any(device["removable"] for device in devices),
    }


def _network_section(interfaces: list[Any]) -> dict[str, Any]:
    valid = [entry for entry in interfaces if isinstance(entry, dict)]
    types = {entry.get("type") for entry in valid}
    return {
        "interface_count": len(valid),
        "wired": "ethernet" in types,
        "wireless": "wireless" in types,
        "drivers": sorted({entry["driver"] for entry in valid if entry.get("driver")}),
    }


def _power_section(power: dict[str, Any], has_battery: bool) -> dict[str, Any]:
    cpufreq = _mapping(power.get("cpufreq"))
    choices = [_str(choice) for choice in _list(cpufreq.get("platform_profile_choices"))]
    return {
        "has_battery": has_battery,
        "battery_count": len(_list(power.get("batteries"))),
        "governor": cpufreq.get("governor"),
        "energy_performance_preference": cpufreq.get("energy_performance_preference"),
        "platform_profile": cpufreq.get("platform_profile"),
        "platform_profile_supported": bool(choices),
        "platform_profile_choices": choices,
        "governors": [_str(value) for value in _list(cpufreq.get("available_governors"))],
        "energy_performance_preferences": [
            _str(value)
            for value in _list(cpufreq.get("available_energy_performance_preferences"))
        ],
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""
