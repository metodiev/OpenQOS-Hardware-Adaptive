"""Tests for overlay application, ISO verification, and manifests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openqos.errors import ImageBuildError
from openqos.imagebuilder.manifest import build_manifest, sha256_file, verify_iso, write_manifest
from openqos.imagebuilder.plan import KIWI_DESCRIPTIONS_COMMIT, build_plan
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

    kiwi_text = (description / "Fedora.kiwi").read_text(encoding="utf-8")
    assert kiwi_text.count("components/openqos.xml") == 1
    config_text = (description / "config.sh").read_text(encoding="utf-8")
    assert config_text.count("OpenQOS overlay") == 1

    apply_overlay(description, overlay, _PROJECT_ROOT)
    assert (description / "Fedora.kiwi").read_text(encoding="utf-8").count("openqos.xml") == 1
    assert (description / "config.sh").read_text(encoding="utf-8").count("OpenQOS overlay") == 1


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
    assert any(check.name.startswith("tool:") for check in checks)
    # The Fedora and Linux checks must pass for the synthetic host release file.
    failed_names = {check.name for check in required_failures(checks)}
    assert "linux-host" not in failed_names
    assert "fedora-host" not in failed_names


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
    assert any(command[0] == "git" for command in commands)
