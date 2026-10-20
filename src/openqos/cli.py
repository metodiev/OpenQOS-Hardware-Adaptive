"""Command-line interface for OpenQOS tooling."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openqos import __version__
from openqos.errors import ImageBuildError, OpenQOSError
from openqos.hardware.scanner import scan
from openqos.hardware.validate import load_document, validate_document
from openqos.imagebuilder.build import build_image
from openqos.imagebuilder.manifest import build_manifest, verify_iso
from openqos.imagebuilder.plan import build_plan as build_image_plan
from openqos.imagebuilder.plan import render_plan as render_image_plan
from openqos.imagebuilder.preflight import required_failures, run_preflight
from openqos.optimizer.engine import build_plan as build_optimization_plan
from openqos.optimizer.engine import render_plan as render_optimization_plan
from openqos.optimizer.validate import (
    load_json,
    validate_plan_or_raise,
    validate_profile_document,
    validate_profile_or_raise,
)
from openqos.profiles.model import build_profile
from openqos.profiles.rules import load_ruleset, match_profile
from openqos.schemas import available_hardware_schema_versions, hardware_schema_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openqos",
        description="Hardware-adaptive Linux operating system tooling.",
    )
    parser.add_argument("--version", action="version", version=f"openqos {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    hardware = subparsers.add_parser("hardware", help="hardware discovery commands")
    hardware_sub = hardware.add_subparsers(dest="hardware_command", required=True)

    scan_parser = hardware_sub.add_parser("scan", help="produce a hardware inventory")
    scan_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="write the inventory to this file instead of standard output",
    )
    scan_parser.add_argument(
        "--privacy",
        action="store_true",
        help="omit hostnames, serial numbers, and MAC addresses",
    )
    scan_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    scan_parser.add_argument(
        "--no-validate",
        action="store_true",
        help="skip validation of the produced inventory",
    )

    validate_parser = hardware_sub.add_parser("validate", help="validate an inventory file")
    validate_parser.add_argument("file", type=Path)
    validate_parser.add_argument("--quiet", action="store_true", help="only report problems")

    schema_parser = hardware_sub.add_parser("schema", help="show or export the inventory schema")
    schema_parser.add_argument("--version", dest="schema_version", default=None)
    schema_parser.add_argument("--output", "-o", type=Path, default=None)

    image = subparsers.add_parser("image", help="ISO image build planning and execution")
    image_sub = image.add_subparsers(dest="image_command", required=True)
    plan_parser = image_sub.add_parser("plan", help="describe the pinned ISO build plan")
    plan_parser.add_argument("--profile", default="generic", help="image profile name")
    plan_parser.add_argument("--output", "-o", type=Path, default=None)
    plan_parser.add_argument("--format", choices=("json", "text"), default="text")

    build_parser_ = image_sub.add_parser("build", help="run the ISO build on a Fedora host")
    build_parser_.add_argument("--profile", default="generic", help="image profile name")
    build_parser_.add_argument(
        "--work-directory",
        type=Path,
        default=Path(".work/iso"),
        help="scratch directory for the kiwi checkout and build output",
    )
    build_parser_.add_argument(
        "--releases-directory",
        type=Path,
        default=Path("releases"),
        help="directory for the ISO, checksum, and manifest",
    )
    build_parser_.add_argument(
        "--execute",
        action="store_true",
        help="actually build; without this flag only the preflight and plan are shown",
    )

    verify_parser = image_sub.add_parser(
        "verify", help="verify an existing ISO and write a manifest"
    )
    verify_parser.add_argument("iso", type=Path)
    verify_parser.add_argument("--profile", default="generic")
    verify_parser.add_argument("--output", "-o", type=Path, default=None)

    profile = subparsers.add_parser("profile", help="hardware profile commands")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)

    profile_build = profile_sub.add_parser("build", help="build a normalised profile")
    profile_build.add_argument("--inventory", "-i", type=Path, required=True)
    profile_build.add_argument("--output", "-o", type=Path, default=None)

    profile_explain = profile_sub.add_parser(
        "explain", help="show which profile rules matched and why"
    )
    profile_explain.add_argument("--inventory", "-i", type=Path, required=True)
    profile_explain.add_argument("--output", "-o", type=Path, default=None)

    profile_validate = profile_sub.add_parser("validate", help="validate a profile file")
    profile_validate.add_argument("file", type=Path)

    optimize = subparsers.add_parser("optimize", help="produce an optimization plan")
    optimize.add_argument("--inventory", "-i", type=Path, required=True)
    optimize.add_argument(
        "--policy",
        default="balanced",
        choices=("balanced", "performance", "power-saving"),
        help="optimization policy (default: balanced)",
    )
    optimize.add_argument("--output", "-o", type=Path, default=None)
    optimize.add_argument("--format", choices=("json", "text"), default="text")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "hardware":
            return _run_hardware(args)
        if args.command == "image":
            return _run_image(args)
        if args.command == "profile":
            return _run_profile(args)
        if args.command == "optimize":
            return _run_optimize(args)
    except OpenQOSError as error:
        print(f"openqos: error: {error}", file=sys.stderr)
        return 2
    raise AssertionError("unreachable")  # pragma: no cover


def _run_hardware(args: argparse.Namespace) -> int:
    if args.hardware_command == "scan":
        return _hardware_scan(args)
    if args.hardware_command == "validate":
        return _hardware_validate(args)
    if args.hardware_command == "schema":
        return _hardware_schema(args)
    raise OpenQOSError(f"unknown hardware command {args.hardware_command!r}")


def _hardware_scan(args: argparse.Namespace) -> int:
    if args.root is None and sys.platform != "linux":
        print(
            "openqos: warning: not running on Linux; most collectors will report "
            "'unavailable' because /sys and /proc are absent",
            file=sys.stderr,
        )
    document = scan(args.root, privacy=args.privacy)
    if not args.no_validate:
        problems = validate_document(document)
        if problems:
            joined = "\n".join(f"  - {problem}" for problem in problems)
            print(f"openqos: warning: inventory failed validation:\n{joined}", file=sys.stderr)
    payload = json.dumps(document, indent=2, sort_keys=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        summary = _inventory_summary(document)
        print(f"wrote {args.output}")
        print(summary)
    else:
        sys.stdout.write(payload)
    return 0


def _hardware_validate(args: argparse.Namespace) -> int:
    document = load_document(args.file)
    problems = validate_document(document)
    if not problems:
        if not args.quiet:
            print(f"{args.file}: valid hardware inventory ({document['schema_version']})")
        return 0
    for problem in problems:
        print(f"{args.file}: {problem}", file=sys.stderr)
    return 1


def _hardware_schema(args: argparse.Namespace) -> int:
    path = hardware_schema_path(args.schema_version)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"wrote {args.output}")
        return 0
    print(f"schema version(s): {', '.join(available_hardware_schema_versions())}")
    print(path.read_text(encoding="utf-8"))
    return 0


def _run_image(args: argparse.Namespace) -> int:
    if args.image_command == "plan":
        return _image_plan(args)
    if args.image_command == "build":
        return _image_build(args)
    if args.image_command == "verify":
        return _image_verify(args)
    raise OpenQOSError(f"unknown image command {args.image_command!r}")


def _image_plan(args: argparse.Namespace) -> int:
    plan = build_image_plan(profile=args.profile)
    payload = (
        json.dumps(plan, indent=2) + "\n"
        if args.format == "json"
        else render_image_plan(plan)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"wrote {args.output}")
        return 0
    sys.stdout.write(payload)
    return 0


def _image_build(args: argparse.Namespace) -> int:
    plan = build_image_plan(profile=args.profile, work_directory=str(args.work_directory))
    args.work_directory.mkdir(parents=True, exist_ok=True)

    print("preflight:")
    checks = run_preflight(work_directory=args.work_directory)
    for check in checks:
        status = "ok" if check.ok else ("FAIL" if check.required else "warn")
        print(f"  [{status:4}] {check.name}: {check.detail}")

    failures = required_failures(checks)
    if not args.execute:
        sys.stdout.write("\n" + render_image_plan(plan))
        if failures:
            print(
                "not ready to build: resolve the failing checks above, then re-run with --execute",
                file=sys.stderr,
            )
        else:
            print("host is ready; re-run with --execute to build", file=sys.stderr)
        return 0

    if failures:
        raise ImageBuildError(
            "required preflight checks failed: " + ", ".join(check.name for check in failures)
        )

    project_root = Path(__file__).resolve().parents[2]
    manifest = build_image(
        plan,
        project_root=project_root,
        releases_directory=args.releases_directory,
    )
    artifact = manifest["artifact"]
    print(f"built {manifest['released_iso']}")
    print(f"  sha256 : {artifact['sha256']}")
    print(f"  size   : {artifact['size_mib']} MiB")
    print(f"  manifest: {manifest['manifest_path']}")
    return 0


def _image_verify(args: argparse.Namespace) -> int:
    artifact = verify_iso(args.iso)
    manifest = build_manifest(artifact, plan=build_image_plan(profile=args.profile))
    payload = json.dumps(manifest, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(payload)
    return 0


def _run_profile(args: argparse.Namespace) -> int:
    if args.profile_command == "build":
        inventory = load_document(args.inventory)
        profile = build_profile(inventory)
        validate_profile_or_raise(profile)
        payload = json.dumps(profile, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
            print(f"wrote {args.output}")
        else:
            sys.stdout.write(payload)
        return 0

    if args.profile_command == "explain":
        inventory = load_document(args.inventory)
        profile = build_profile(inventory)
        matched = match_profile(profile, load_ruleset())
        text = _render_match(profile, matched)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"wrote {args.output}")
        else:
            sys.stdout.write(text)
        return 0

    if args.profile_command == "validate":
        document = load_json(args.file)
        problems = validate_profile_document(document)
        if problems:
            for problem in problems:
                print(f"{args.file}: {problem}", file=sys.stderr)
            return 1
        print(f"{args.file}: valid hardware profile ({document['schema_version']})")
        return 0
    raise OpenQOSError(f"unknown profile command {args.profile_command!r}")


def _render_match(profile: dict[str, Any], matched: dict[str, Any]) -> str:
    machine = profile.get("machine") or {}
    cpu = profile.get("cpu") or {}
    lines = [
        f"profile      : {matched['profile_id']} (priority {matched['priority']}"
        f"{', fallback' if matched['fallback'] else ''})",
        f"description  : {matched['description']}",
        f"machine      : {machine.get('form_factor')} / {cpu.get('vendor')} "
        f"/ {cpu.get('model') or 'unknown cpu'}",
        f"rules        : revision {matched['rules_revision']}",
        "",
        "matched conditions:",
    ]
    lines.extend(
        f"  + {condition}" for condition in (matched["matched_conditions"] or ["(none)"])
    )
    rejected = [
        entry for entry in matched["evaluated_rules"] if not entry["matched"]
    ]
    if rejected:
        lines.append("")
        lines.append("not matched:")
        for entry in rejected:
            failed = entry["conditions"][-1] if entry["conditions"] else "no conditions"
            lines.append(f"  - {entry['rule']}: {failed}")
    if matched["package_sets"]:
        lines.append("")
        lines.append("package sets: " + ", ".join(matched["package_sets"]))
    if matched["notes"]:
        lines.append("")
        lines.append("notes:")
        lines.extend(f"  - {note}" for note in matched["notes"])
    return "\n".join(lines) + "\n"


def _run_optimize(args: argparse.Namespace) -> int:
    inventory = load_document(args.inventory)
    profile = build_profile(inventory)
    validate_profile_or_raise(profile)
    plan = build_optimization_plan(profile, policy=args.policy)
    validate_plan_or_raise(plan)
    payload = (
        json.dumps(plan, indent=2) + "\n"
        if args.format == "json"
        else render_optimization_plan(plan)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(payload)
    return 0


def _inventory_summary(document: dict[str, Any]) -> str:
    cpu = document.get("cpu") or {}
    memory = document.get("memory") or {}
    graphics = document.get("graphics") or {}
    storage = document.get("storage") or []
    host = document.get("host") or {}
    os_info = host.get("os") or {}
    firmware = host.get("firmware") or {}
    kernel = host.get("kernel") or {}
    lines = [
        "hardware summary",
        f"  os           : {os_info.get('pretty_name') or 'unknown'}",
        f"  kernel       : {kernel.get('release') or 'unknown'}",
        f"  firmware     : {firmware.get('boot_mode')} / secure boot {firmware.get('secure_boot')}",
        f"  cpu          : {cpu.get('model_name') or 'unknown'} "
        f"({cpu.get('logical_cpus', 0)} logical, {cpu.get('physical_cores') or '?'} physical)",
        f"  memory       : {memory.get('total_mib', 0)} MiB",
        f"  graphics     : {graphics.get('adapter_count', 0)} adapter(s), "
        f"primary={graphics.get('primary_adapter')}, hybrid={graphics.get('hybrid_graphics')}",
        f"  storage      : {len(storage)} device(s): "
        f"{', '.join(device.get('name', '?') for device in storage) or 'none'}",
        f"  warnings     : {len(document.get('warnings') or [])}",
        f"  unavailable  : {len(document.get('unavailable') or [])} entry(ies)",
    ]
    return "\n".join(lines)


def entrypoint() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
