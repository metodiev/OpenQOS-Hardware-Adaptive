"""Tests for disk enumeration, install planning, Kickstart rendering, and execution."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openqos.cli import main
from openqos.errors import InstallError
from openqos.hardware.scanner import scan
from openqos.installer.disks import enumerate_disks
from openqos.installer.plan import (
    build_install_plan,
    render_kickstart,
    validate_install_plan,
)
from openqos.installer.runner import confirm_target, run_installer
from openqos.optimizer.engine import build_plan
from openqos.profiles.model import build_profile


def _add_disk(
    root: Path,
    name: str,
    *,
    gib: int,
    removable: bool = False,
    rotational: bool = False,
    model: str = "Test Disk",
) -> None:
    base = root / "sys" / "block" / name
    (base / "queue").mkdir(parents=True, exist_ok=True)
    (base / "device").mkdir(parents=True, exist_ok=True)
    (base / "size").write_text(str(gib * 1024 * 1024 * 2), encoding="utf-8")
    (base / "removable").write_text("1" if removable else "0", encoding="utf-8")
    (base / "queue" / "rotational").write_text("1" if rotational else "0", encoding="utf-8")
    (base / "device" / "model").write_text(model, encoding="utf-8")


def _mount_table(tmp_path: Path) -> Path:
    path = tmp_path / "mounts"
    path.write_text(
        "/dev/nvme0n1p2 / btrfs rw,relatime 0 0\n"
        "/dev/sr0 /run/initramfs/live iso9660 ro 0 0\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def disk_tree(amd_desktop_tree: Path) -> Path:
    _add_disk(amd_desktop_tree, "sdb", gib=500, model="Samsung SSD 870")
    _add_disk(amd_desktop_tree, "sr0", gib=2, removable=True, model="QEMU DVD-ROM")
    return amd_desktop_tree


def _candidates(tree: Path, tmp_path: Path) -> dict[str, object]:
    return {
        candidate.name: candidate
        for candidate in enumerate_disks(tree, mount_table=_mount_table(tmp_path))
    }


def test_enumeration_marks_refusal_reasons(disk_tree: Path, tmp_path: Path) -> None:
    candidates = _candidates(disk_tree, tmp_path)
    assert set(candidates) == {"nvme0n1", "sda", "sdb", "sr0"}
    assert candidates["sdb"].eligible is True
    assert "contains existing partitions" in candidates["sda"].reasons
    assert "hosts the running root filesystem" in candidates["nvme0n1"].reasons
    assert "removable media" in candidates["sr0"].reasons
    assert "optical drive" in candidates["sr0"].reasons


def test_small_disk_is_refused(disk_tree: Path, tmp_path: Path) -> None:
    _add_disk(disk_tree, "sdc", gib=8)
    candidates = _candidates(disk_tree, tmp_path)
    assert any("smaller than" in reason for reason in candidates["sdc"].reasons)


def test_live_medium_is_refused(amd_desktop_tree: Path, tmp_path: Path) -> None:
    _add_disk(amd_desktop_tree, "sdz", gib=64)
    table = tmp_path / "mounts"
    table.write_text(
        "/dev/sdz1 /run/initramfs/live vfat ro 0 0\n", encoding="utf-8"
    )
    candidates = {c.name: c for c in enumerate_disks(amd_desktop_tree, mount_table=table)}
    assert "hosts the running live medium" in candidates["sdz"].reasons


def _install_plan(disk_tree: Path, tmp_path: Path) -> dict:
    inventory = scan(disk_tree)
    profile = build_profile(inventory)
    optimization = build_plan(profile)
    disk = next(
        candidate
        for candidate in enumerate_disks(disk_tree, mount_table=_mount_table(tmp_path))
        if candidate.name == "sdb"
    )
    return build_install_plan(profile, optimization, disk.to_dict())


def test_install_plan_requires_explicit_eligible_disk(disk_tree: Path, tmp_path: Path) -> None:
    inventory = scan(disk_tree)
    profile = build_profile(inventory)
    optimization = build_plan(profile)
    disk = next(
        candidate
        for candidate in enumerate_disks(disk_tree, mount_table=_mount_table(tmp_path))
        if candidate.name == "sda"
    )
    with pytest.raises(InstallError, match="refusing to install"):
        build_install_plan(profile, optimization, disk.to_dict())


def test_install_plan_contents(disk_tree: Path, tmp_path: Path) -> None:
    plan = _install_plan(disk_tree, tmp_path)
    assert validate_install_plan(plan) == []
    assert plan["target"]["disk"] == "/dev/sdb"
    assert plan["target"]["confirmation_token"] == "sdb"  # noqa: S105
    assert plan["safety"]["requires_confirmation"] is True
    assert plan["layout"]["esp"]["size_mib"] == 600
    assert plan["layout"]["swap"]["strategy"] == "zram"
    assert plan["packages"]["groups"] == ["kde-desktop-environment"]
    assert "zram-generator" in plan["packages"]["packages"]
    assert "storage-trim" in plan["decisions_at_install"]
    assert plan["user"]["locked"] is True


def test_kickstart_rendering(disk_tree: Path, tmp_path: Path) -> None:
    text = render_kickstart(_install_plan(disk_tree, tmp_path))
    assert "ignoredisk --only-use=sdb" in text
    assert "clearpart --all --initlabel --drives=sdb" in text
    assert "part /boot/efi --fstype=efi --size=600 --ondisk=sdb" in text
    assert "part / --fstype=btrfs --grow --size=4096 --ondisk=sdb" in text
    assert "@kde-desktop-environment" in text
    assert "systemctl enable openqos-scan.service" in text
    assert "systemctl enable fstrim.timer" in text
    assert "cp -a /opt/openqos/. \"$ANA_INSTALL_PATH/opt/openqos/\"" in text
    assert "reboot" in text


def test_rotational_target_skips_trim(tmp_path: Path, amd_desktop_tree: Path) -> None:
    for device in (amd_desktop_tree / "sys" / "block").iterdir():
        rotational = device / "queue" / "rotational"
        if rotational.is_file():
            rotational.write_text("1", encoding="utf-8")
    _add_disk(amd_desktop_tree, "sdb", gib=500, rotational=True)
    inventory = scan(amd_desktop_tree)
    profile = build_profile(inventory)
    optimization = build_plan(profile)
    disk = next(
        candidate
        for candidate in enumerate_disks(amd_desktop_tree, mount_table=_mount_table(tmp_path))
        if candidate.name == "sdb"
    )
    plan = build_install_plan(profile, optimization, disk.to_dict())
    assert "storage-trim" not in plan["decisions_at_install"]
    assert "systemctl enable fstrim.timer" not in render_kickstart(plan)


def test_confirmation_must_match_token(disk_tree: Path, tmp_path: Path) -> None:
    plan = _install_plan(disk_tree, tmp_path)
    with pytest.raises(InstallError, match="target confirmation required"):
        confirm_target(plan, "sda")
    with pytest.raises(InstallError, match="target confirmation required"):
        confirm_target(plan, None)
    confirm_target(plan, "sdb")


def test_dry_run_writes_no_report(disk_tree: Path, tmp_path: Path) -> None:
    plan = _install_plan(disk_tree, tmp_path)
    result = run_installer(
        plan,
        confirmation="sdb",
        execute=False,
        kickstart_path=tmp_path / "install.ks",
        log_path=tmp_path / "install.log",
        report_path=tmp_path / "report.json",
    )
    assert result["executed"] is False
    assert result["command"][0] == "anaconda"
    assert (tmp_path / "install.ks").is_file()
    assert not (tmp_path / "report.json").exists()


def test_execute_writes_report(disk_tree: Path, tmp_path: Path) -> None:
    plan = _install_plan(disk_tree, tmp_path)

    def fake_runner(command, **kwargs):
        return SimpleNamespace(returncode=0)

    report = run_installer(
        plan,
        confirmation="sdb",
        execute=True,
        kickstart_path=tmp_path / "install.ks",
        log_path=tmp_path / "install.log",
        report_path=tmp_path / "report.json",
        runner=fake_runner,
    )
    assert report["status"] == "succeeded"
    written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert written["target"] == "/dev/sdb"
    assert written["exit_code"] == 0


def test_failed_install_is_reported(disk_tree: Path, tmp_path: Path) -> None:
    plan = _install_plan(disk_tree, tmp_path)

    def fake_runner(command, **kwargs):
        return SimpleNamespace(returncode=1)

    with pytest.raises(InstallError, match="Anaconda failed"):
        run_installer(
            plan,
            confirmation="sdb",
            execute=True,
            kickstart_path=tmp_path / "install.ks",
            log_path=tmp_path / "install.log",
            report_path=tmp_path / "report.json",
            runner=fake_runner,
        )


def test_cli_install_disks_and_plan(
    disk_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(scan(disk_tree, privacy=True)), encoding="utf-8")

    assert main(["install", "disks", "--root", str(disk_tree)]) == 0
    listing = capsys.readouterr().out
    assert "/dev/sdb" in listing
    assert "eligible" in listing
    assert "refused" in listing

    assert (
        main(
            [
                "install",
                "plan",
                "--inventory",
                str(inventory),
                "--disk",
                "/dev/sdb",
                "--root",
                str(disk_tree),
                "--format",
                "kickstart",
            ]
        )
        == 0
    )
    assert "clearpart --all --initlabel --drives=sdb" in capsys.readouterr().out


def test_cli_install_plan_rejects_unknown_disk(
    disk_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(scan(disk_tree, privacy=True)), encoding="utf-8")
    assert (
        main(
            [
                "install",
                "plan",
                "--inventory",
                str(inventory),
                "--disk",
                "/dev/nope",
                "--root",
                str(disk_tree),
            ]
        )
        == 2
    )
    assert "no disk" in capsys.readouterr().err
