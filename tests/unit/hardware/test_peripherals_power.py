"""Tests for audio, input, camera, Bluetooth, battery, and power policy."""

from __future__ import annotations

from pathlib import Path

from openqos.hardware.collectors.peripherals import (
    collect_audio,
    collect_bluetooth,
    collect_cameras,
    collect_input_devices,
)
from openqos.hardware.collectors.power import collect_power
from openqos.hardware.context import CollectionContext


def _ctx(root: Path, *, privacy: bool = False) -> CollectionContext:
    return CollectionContext.create(root, privacy=privacy)


def test_audio_cards(intel_laptop_tree: Path) -> None:
    audio = collect_audio(_ctx(intel_laptop_tree))
    assert [card["id"] for card in audio["cards"]] == ["sofhdadsp"]


def test_cameras_and_input(intel_laptop_tree: Path) -> None:
    ctx = _ctx(intel_laptop_tree)
    cameras = collect_cameras(ctx)
    assert cameras[0]["id"] == "video0"
    assert "Integrated Camera" in (cameras[0]["name"] or "")

    devices = collect_input_devices(ctx)
    names = {device["name"] for device in devices}
    assert "AT Translated Set 2 keyboard" in names
    assert any("Touchpad" in name for name in names)
    touchpad = next(device for device in devices if "Touchpad" in device["name"])
    assert touchpad["vendor_id"] == "06cb"
    assert touchpad["handlers"] == ["mouse0", "event5"]


def test_bluetooth_privacy(intel_laptop_tree: Path) -> None:
    assert collect_bluetooth(_ctx(intel_laptop_tree))[0]["address"] == "a4:bb:6d:11:22:34"
    assert collect_bluetooth(_ctx(intel_laptop_tree, privacy=True))[0]["address"] is None


def test_battery_and_power_policy(intel_laptop_tree: Path) -> None:
    power = collect_power(_ctx(intel_laptop_tree))
    battery = power["batteries"][0]
    assert battery["name"] == "BAT0"
    assert battery["capacity_percent"] == 76
    assert battery["design_capacity_mwh"] == 57_000
    assert battery["current_capacity_mwh"] == 43_000
    assert battery["power_now_mw"] == 8_100
    assert battery["cycle_count"] == 122

    cpufreq = power["cpufreq"]
    assert cpufreq["driver"] == "intel_pstate"
    assert cpufreq["governor"] == "powersave"
    assert cpufreq["available_governors"] == ["performance", "powersave"]
    assert cpufreq["energy_performance_preference"] == "balance_performance"
    assert "power" in cpufreq["available_energy_performance_preferences"]
    assert cpufreq["platform_profile"] == "balanced"
    assert cpufreq["platform_profile_choices"] == ["low-power", "balanced", "performance"]


def test_desktop_without_battery(amd_desktop_tree: Path) -> None:
    ctx = _ctx(amd_desktop_tree)
    power = collect_power(ctx)
    assert power["batteries"] == []
    assert power["cpufreq"]["driver"] == "amd-pstate-epp"
    assert power["cpufreq"]["platform_profile"] is None
    assert any(entry["collector"] == "power.platform_profile" for entry in ctx.unavailable)
