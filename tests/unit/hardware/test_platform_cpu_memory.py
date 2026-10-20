"""Tests for platform, CPU, and memory collection."""

from __future__ import annotations

from pathlib import Path

from openqos.hardware.collectors.cpu import collect_cpu
from openqos.hardware.collectors.memory import collect_memory
from openqos.hardware.collectors.platform_info import collect_platform
from openqos.hardware.context import CollectionContext


def _ctx(root: Path, *, privacy: bool = False) -> CollectionContext:
    return CollectionContext.create(root, privacy=privacy)


def test_platform_uefi_secure_boot_enabled(intel_laptop_tree: Path) -> None:
    platform = collect_platform(_ctx(intel_laptop_tree))
    assert platform["os"]["id"] == "fedora"
    assert platform["os"]["version_id"] == "44"
    assert platform["os"]["id_like"] == []
    assert platform["kernel"]["release"] == "6.16.3-200.fc44.x86_64"
    assert platform["firmware"] == {
        "boot_mode": "uefi",
        "secure_boot": "enabled",
        "setup_mode": "disabled",
    }
    assert platform["virtualization"]["is_virtual_machine"] is False


def test_platform_bios_machine(amd_desktop_tree: Path) -> None:
    platform = collect_platform(_ctx(amd_desktop_tree))
    assert platform["firmware"]["boot_mode"] == "bios"
    assert platform["firmware"]["secure_boot"] == "unknown"


def test_platform_privacy_omits_identifiers(intel_laptop_tree: Path) -> None:
    visible = collect_platform(_ctx(intel_laptop_tree))
    hidden = collect_platform(_ctx(intel_laptop_tree, privacy=True))
    assert visible["hostname"] is not None
    assert hidden["hostname"] is None
    assert visible["virtualization"]["vendor"] == "LENOVO"
    assert hidden["virtualization"]["vendor"] is None


def test_platform_missing_os_release_is_reported(minimal_tree: Path) -> None:
    ctx = _ctx(minimal_tree)
    platform = collect_platform(ctx)
    assert platform["os"] is None
    assert any(entry["collector"] == "platform.os" for entry in ctx.unavailable)


def test_cpu_topology(intel_laptop_tree: Path) -> None:
    cpu = collect_cpu(_ctx(intel_laptop_tree))
    assert cpu is not None
    assert cpu["vendors"] == ["GenuineIntel"]
    assert cpu["model_name"] == "12th Gen Intel(R) Core(TM) i7-1260P"
    assert cpu["logical_cpus"] == 8
    assert cpu["physical_cores"] == 4
    assert cpu["threads_per_core"] == 2
    assert cpu["sockets"] == 1
    assert cpu["microcode"] == "0x191"
    assert cpu["frequency_mhz"] == {"min": 400, "max": 4700}
    assert cpu["cache"] == {
        "l1d_kib": 48,
        "l1i_kib": 32,
        "l2u_kib": 1280,
        "l3u_kib": 24576,
    }
    assert "avx512f" in cpu["flags"]
    assert cpu["cpufreq_driver"] == "intel_pstate"


def test_cpu_amd_flags(amd_desktop_tree: Path) -> None:
    cpu = collect_cpu(_ctx(amd_desktop_tree))
    assert cpu is not None
    assert cpu["logical_cpus"] == 32
    assert cpu["physical_cores"] == 16
    assert "svm" in cpu["flags"]


def test_cpu_absent_is_none_and_reported(minimal_tree: Path) -> None:
    ctx = _ctx(minimal_tree)
    assert collect_cpu(ctx) is None
    assert any(entry["collector"] == "cpu" for entry in ctx.unavailable)


def test_memory_values(intel_laptop_tree: Path) -> None:
    memory = collect_memory(_ctx(intel_laptop_tree))
    assert memory is not None
    assert memory["total_kib"] == 15_728_640
    assert memory["total_mib"] == 15_360
    assert memory["swap_total_kib"] == 8_388_608
    assert memory["modules"] == []


def test_memory_missing_total_reports_warning(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "meminfo").write_text("MemFree: 100 kB\n", encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert collect_memory(ctx) is None
    assert ctx.warnings[0]["code"] == "memory.missing-total"
