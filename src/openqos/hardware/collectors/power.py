"""Battery, CPU frequency policy, and platform profile detection."""

from __future__ import annotations

from typing import Any

from openqos.hardware.context import CollectionContext
from openqos.hardware.readers import split_list

_POWER_SUPPLY = ("sys", "class", "power_supply")
_CPU0_CPUFREQ = ("sys", "devices", "system", "cpu", "cpu0", "cpufreq")


def collect_power(ctx: CollectionContext) -> dict[str, Any]:
    batteries = _collect_batteries(ctx)
    cpufreq = {
        "driver": ctx.fs.text(*_CPU0_CPUFREQ, "scaling_driver"),
        "governor": ctx.fs.text(*_CPU0_CPUFREQ, "scaling_governor"),
        "available_governors": split_list(
            ctx.fs.text(*_CPU0_CPUFREQ, "scaling_available_governors")
        ),
        "energy_performance_preference": ctx.fs.text(
            *_CPU0_CPUFREQ, "energy_performance_preference"
        ),
        "available_energy_performance_preferences": split_list(
            ctx.fs.text(*_CPU0_CPUFREQ, "energy_performance_available_preferences")
        ),
        "platform_profile": ctx.fs.text("sys", "firmware", "acpi", "platform_profile"),
        "platform_profile_choices": split_list(
            ctx.fs.text("sys", "firmware", "acpi", "platform_profile_choices")
        ),
    }
    if cpufreq["driver"] is None:
        ctx.unavailable_reason("power.cpufreq", "cpufreq scaling driver is not exposed in sysfs")
    if cpufreq["platform_profile"] is None:
        ctx.unavailable_reason(
            "power.platform_profile", "ACPI platform profile is not supported by this firmware"
        )
    return {"batteries": batteries, "cpufreq": cpufreq}


def _collect_batteries(ctx: CollectionContext) -> list[dict[str, Any]]:
    batteries: list[dict[str, Any]] = []
    for entry in ctx.fs.subdirectories(*_POWER_SUPPLY):
        if ctx.fs.text(*entry.parts, "type") != "Battery":
            continue
        energy_full = ctx.fs.integer(*entry.parts, "energy_full")
        energy_now = ctx.fs.integer(*entry.parts, "energy_now")
        charge_full = ctx.fs.integer(*entry.parts, "charge_full")
        charge_now = ctx.fs.integer(*entry.parts, "charge_now")
        batteries.append(
            {
                "name": entry.name,
                "status": ctx.fs.text(*entry.parts, "status"),
                "capacity_percent": ctx.fs.integer(*entry.parts, "capacity"),
                "design_capacity_mwh": _micro(energy_full)
                or _micro(charge_full, voltage=ctx.fs.integer(*entry.parts, "voltage_min_design")),
                "current_capacity_mwh": _micro(energy_now)
                or _micro(charge_now, voltage=ctx.fs.integer(*entry.parts, "voltage_now")),
                "power_now_mw": _micro(ctx.fs.integer(*entry.parts, "power_now")),
                "cycle_count": ctx.fs.integer(*entry.parts, "cycle_count"),
                "charge_control_end_threshold": ctx.fs.integer(
                    *entry.parts, "charge_control_end_threshold"
                ),
            }
        )
    return batteries


def _micro(value: int | None, *, voltage: int | None = None) -> int | None:
    """Convert microwatt-hours (or microvolts*microwatt-hours) to milliwatt-hours."""
    if value is None:
        return None
    if voltage is None:
        return value // 1000
    return value * voltage // 1_000_000_000
