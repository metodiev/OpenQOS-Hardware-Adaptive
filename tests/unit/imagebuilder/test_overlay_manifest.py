"""Tests for overlay application, ISO verification, and manifests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from openqos.errors import ImageBuildError
from openqos.imagebuilder.manifest import build_manifest, sha256_file, verify_iso, write_manifest
from openqos.imagebuilder.plan import FEDORA_RELEASE, KIWI_DESCRIPTIONS_COMMIT, build_plan
from openqos.imagebuilder.runner import apply_overlay

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _description(tmp_path: Path) -> Path:
    description = tmp_path / "kiwi-descriptions"
    (description / "components").mkdir(parents=True)
    (description / "Fedora.kiwi").write_text(
        '<image schemaversion="7.4" name="Fedora">\n'
        '\t<packages type="bootstrap">\n\t\t<package name="filesystem"/>\n\t</packages>\n'
        "</image>\n",
        encoding="utf-8",
    )
    (description / "config.sh").write_text("#!/bin/bash\nset -e\n", encoding="utf-8")
    return description


def test_apply_overlay_copies_sources_and_is_idempotent(tmp_path: Path) -> None:
    description = _description(tmp_path)
    overlay = _PROJECT_ROOT / "image" / "overlay"

    changed = apply_overlay(description, overlay, _PROJECT_ROOT)
    assert any(path.endswith("openqos.xml") for path in changed)
    assert (description / "components" / "openqos.xml").is_file()
    assert (description / "root" / "usr" / "local" / "bin" / "openqos").is_file()
    assert (description / "root" / "opt" / "openqos" / "src" / "openqos" / "cli.py").is_file()
    assert (
        description / "root" / "usr" / "lib" / "systemd" / "system" / "openqos-scan.service"
    ).is_file()
    assert (
        description / "root" / "etc" / "xdg" / "autostart" / "openqos-summary.desktop"
    ).is_file()
    if os.name != "nt":
        link = (
            description
            / "root"
            / "etc"
            / "systemd"
            / "system"
            / "multi-user.target.wants"
            / "openqos-scan.service"
        )
        assert link.is_symlink()
        assert link.resolve().name == "openqos-scan.service"
    wrapper_bytes = (description / "root" / "usr" / "local" / "bin" / "openqos").read_bytes()
    assert b"\r" not in wrapper_bytes
    assert wrapper_bytes.startswith(b"#!/bin/sh\n")

    kiwi_text = (description / "Fedora.kiwi").read_text(encoding="utf-8")
    assert kiwi_text.count("components/openqos.xml") == 1
    release_marker = description / "root" / "etc" / "openqos-release"
    assert release_marker.read_text(encoding="utf-8").startswith("OpenQOS live environment")
    assert f"base=Fedora Linux {FEDORA_RELEASE}" in release_marker.read_text(encoding="utf-8")
    config_before = (description / "config.sh").read_text(encoding="utf-8")

    apply_overlay(description, overlay, _PROJECT_ROOT)
    assert (description / "Fedora.kiwi").read_text(encoding="utf-8").count("openqos.xml") == 1
    assert (description / "config.sh").read_text(encoding="utf-8") == config_before


def test_apply_overlay_normalises_line_endings(tmp_path: Path) -> None:
    description = _description(tmp_path)
    overlay = tmp_path / "overlay"
    (overlay / "components").mkdir(parents=True)
    (overlay / "components" / "openqos.xml").write_bytes(b"<image>\r\n</image>\r\n")
    (overlay / "root" / "usr" / "local" / "bin").mkdir(parents=True)
    (overlay / "root" / "usr" / "local" / "bin" / "openqos").write_bytes(
        b"#!/bin/sh\r\nexec true\r\n"
    )
    project = tmp_path / "project"
    (project / "src" / "openqos").mkdir(parents=True)
    (project / "src" / "openqos" / "__init__.py").write_bytes(b'"""x"""\r\n')

    apply_overlay(description, overlay, project)

    wrapper = description / "root" / "usr" / "local" / "bin" / "openqos"
    assert wrapper.read_bytes() == b"#!/bin/sh\nexec true\n"
    module = description / "root" / "opt" / "openqos" / "src" / "openqos" / "__init__.py"
    assert module.read_bytes() == b'"""x"""\n'
    assert b"\r\n" not in (description / "components" / "openqos.xml").read_bytes()


def test_apply_overlay_requires_description(tmp_path: Path) -> None:
    with pytest.raises(ImageBuildError):
        apply_overlay(tmp_path / "missing", _PROJECT_ROOT / "image" / "overlay", _PROJECT_ROOT)


def _fake_iso(path: Path, *, size: int = 2 * 1024 * 1024) -> Path:
    payload = bytearray(size)
    payload[0x8001 : 0x8001 + 5] = b"CD001"
    path.write_bytes(payload)
    return path


def test_verify_iso_accepts_image(tmp_path: Path) -> None:
    iso = _fake_iso(tmp_path / "openqos.iso")
    artifact = verify_iso(iso)
    assert artifact["size_bytes"] == iso.stat().st_size
    assert artifact["sha256"] == sha256_file(iso)
    assert len(artifact["sha256"]) == 64


def test_verify_iso_rejects_small_file(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.iso"
    tiny.write_bytes(b"CD001")
    with pytest.raises(ImageBuildError):
        verify_iso(tiny)


def test_verify_iso_rejects_non_iso(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.iso"
    bogus.write_bytes(bytearray(2 * 1024 * 1024))
    with pytest.raises(ImageBuildError):
        verify_iso(bogus)


def test_verify_iso_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ImageBuildError):
        verify_iso(tmp_path / "missing.iso")


def test_manifest_records_artifact_and_revisions(tmp_path: Path) -> None:
    iso = _fake_iso(tmp_path / "openqos.iso")
    artifact = verify_iso(iso)
    manifest = build_manifest(
        artifact,
        plan=build_plan(),
        package_versions={"kiwi-cli": "11.1.1"},
        source_revision="0" * 40,
    )
    assert manifest["artifact"]["sha256"] == artifact["sha256"]
    assert manifest["package_versions"] == {"kiwi-cli": "11.1.1"}
    assert manifest["environment"]["kiwi_descriptions"]["commit"] == KIWI_DESCRIPTIONS_COMMIT

    path = write_manifest(manifest, tmp_path / "releases" / "manifest.json")
    assert json.loads(path.read_text(encoding="utf-8"))["source_revision"] == "0" * 40


def test_apply_overlay_does_not_modify_host_sources(tmp_path: Path) -> None:
    before = (sorted(path.name for path in (_PROJECT_ROOT / "src" / "openqos").rglob("*")))
    apply_overlay(_description(tmp_path), _PROJECT_ROOT / "image" / "overlay", _PROJECT_ROOT)
    after = sorted(path.name for path in (_PROJECT_ROOT / "src" / "openqos").rglob("*"))
    assert before == after


def test_preflight_reports_fedora_and_tools(tmp_path: Path) -> None:
    from openqos.imagebuilder.preflight import required_failures, run_preflight

    release_file = tmp_path / "os-release"
    release_file.write_text('ID=fedora\nVERSION_ID=44\n', encoding="utf-8")
    checks = run_preflight(
        work_directory=tmp_path,
        release_file=release_file,
        system="Linux",
    )
    names = {check.name for check in checks}
    assert {"linux-host", "fedora-host", "fedora-release", "root-privileges"} <= names
    assert "package:kiwi-cli" in names
    assert "command:git" in names
    # The Fedora and Linux checks must pass for the synthetic host release file.
    failed_names = {check.name for check in required_failures(checks)}
    assert "linux-host" not in failed_names
    assert "fedora-host" not in failed_names


def test_preflight_uses_rpm_for_packages(tmp_path: Path) -> None:
    from openqos.imagebuilder.preflight import run_preflight

    release_file = tmp_path / "os-release"
    release_file.write_text('ID=fedora\nVERSION_ID=44\n', encoding="utf-8")
    checks = run_preflight(
        work_directory=tmp_path,
        release_file=release_file,
        system="Linux",
        which=lambda name: f"/usr/bin/{name}",
        rpm_query=lambda package: package == "kiwi-cli",
    )
    by_name = {check.name: check for check in checks}
    assert by_name["package:kiwi-cli"].ok is True
    assert by_name["package:kiwi-systemdeps"].ok is False
    assert by_name["command:xorriso"].ok is True


def test_installed_package_versions_parses_rpm_output() -> None:
    from openqos.imagebuilder.build import installed_package_versions

    def fake_runner(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="kiwi-cli 11.1.1-2.fc44\nkiwi-systemdeps 11.1.1-2.fc44\nnoise\n",
        )

    versions = installed_package_versions(runner=fake_runner)
    assert versions["kiwi-cli"] == "11.1.1-2.fc44"
    assert "noise" not in versions


def test_run_build_reports_failure(tmp_path: Path) -> None:
    from openqos.imagebuilder.runner import run_build

    def fake_runner(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="boom")

    with pytest.raises(ImageBuildError):
        run_build(tmp_path, tmp_path / "out", runner=fake_runner)


def test_run_build_returns_produced_iso(tmp_path: Path) -> None:
    from openqos.imagebuilder.runner import run_build

    output = tmp_path / "out"
    output.mkdir()
    _fake_iso(output / "Fedora-KDE-Desktop-Live.iso")

    def fake_runner(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok")

    assert run_build(tmp_path, output, runner=fake_runner).name == "Fedora-KDE-Desktop-Live.iso"


def test_run_build_finds_iso_in_kiwi_target_directory(tmp_path: Path) -> None:
    from openqos.imagebuilder.runner import run_build

    output = tmp_path / "out"
    target = tmp_path / "out-build"
    target.mkdir()
    _fake_iso(target / "Fedora.x86_64-44.iso")

    def fake_runner(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok")

    iso = run_build(tmp_path, output, runner=fake_runner)
    assert iso.name == "Fedora.x86_64-44.iso"


def test_source_revision_marks_dirty_tree(tmp_path: Path) -> None:
    from openqos.imagebuilder.build import source_revision

    def fake_runner(command, **kwargs):
        stdout = "b" * 40 + "\n" if "rev-parse" in command else " M src/openqos/cli.py\n"
        return SimpleNamespace(returncode=0, stdout=stdout)

    assert source_revision(tmp_path, runner=fake_runner) == "b" * 40 + "-dirty"


def test_build_image_captures_provenance_before_building(tmp_path: Path) -> None:
    from openqos.imagebuilder.build import build_image
    from openqos.imagebuilder.plan import build_plan

    work = tmp_path / "work"
    description = work / "kiwi-descriptions"
    (description / "components").mkdir(parents=True)
    (description / "Fedora.kiwi").write_text(
        '<image schemaversion="7.4" name="Fedora">\n'
        '\t<packages type="bootstrap">\n\t\t<package name="filesystem"/>\n\t</packages>\n'
        "</image>\n",
        encoding="utf-8",
    )
    order: list[str] = []

    def fake_runner(command, **kwargs):
        if "rev-parse" in command:
            order.append("rev-parse")
            return SimpleNamespace(returncode=0, stdout="c" * 40 + "\n")
        if command[0] == "./kiwi-build":
            order.append("build")
            output_arg = next(arg for arg in command if arg.startswith("--output-dir="))
            output = Path(output_arg.split("=", 1)[1])
            output.mkdir(parents=True, exist_ok=True)
            _fake_iso(output / "x.iso")
        if "status" in command:
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout="")

    manifest = build_image(
        build_plan(work_directory=str(work)),
        project_root=_PROJECT_ROOT,
        releases_directory=tmp_path / "releases",
        runner=fake_runner,
    )
    assert manifest["source_revision"] == "c" * 40
    assert order.index("rev-parse") < order.index("build")


def test_build_image_end_to_end_with_fake_runner(tmp_path: Path) -> None:
    from openqos.imagebuilder.build import build_image
    from openqos.imagebuilder.plan import build_plan

    work = tmp_path / "work"
    description = work / "kiwi-descriptions"
    (description / "components").mkdir(parents=True)
    (description / "Fedora.kiwi").write_text(
        '<image schemaversion="7.4" name="Fedora">\n'
        '\t<packages type="bootstrap">\n\t\t<package name="filesystem"/>\n\t</packages>\n'
        "</image>\n",
        encoding="utf-8",
    )
    (description / "config.sh").write_text("#!/bin/bash\nset -e\n", encoding="utf-8")

    commands: list[list[str]] = []

    def fake_runner(command, **kwargs):
        commands.append(list(command))
        if command[0] == "./kiwi-build":
            output_arg = next(arg for arg in command if arg.startswith("--output-dir="))
            output = Path(output_arg.split("=", 1)[1])
            output.mkdir(parents=True, exist_ok=True)
            _fake_iso(output / "Fedora-KDE-Desktop-Live.iso")
        if "rev-parse" in command:
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
        if "status" in command:
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout="ok")

    releases = tmp_path / "releases"
    manifest = build_image(
        build_plan(work_directory=str(work)),
        project_root=_PROJECT_ROOT,
        releases_directory=releases,
        runner=fake_runner,
    )

    assert manifest["artifact"]["sha256"]
    assert manifest["source_revision"] == "a" * 40
    assert Path(manifest["manifest_path"]).is_file()
    assert Path(manifest["checksum_path"]).read_text(encoding="utf-8").startswith(
        manifest["artifact"]["sha256"]
    )
    assert Path(manifest["released_iso"]).is_file()
    assert manifest["released_iso"].endswith("openqos-generic-44.iso")
    assert any(command[0] == "git" for command in commands)
