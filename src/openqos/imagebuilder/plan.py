"""Pinned, reviewable ISO build plan.

Everything that identifies the build inputs lives here so a build can be
reproduced exactly and reviewed without reading shell scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openqos.errors import ImageBuildError

#: Fedora release used by OpenQOS. Verified against
#: https://dl.fedoraproject.org/pub/fedora/linux/releases/ (2026-10-20).
FEDORA_RELEASE = "44"

#: Branch of the official Fedora KIWI descriptions used for the live image.
KIWI_DESCRIPTIONS_REPOSITORY = "https://forge.fedoraproject.org/releng/kiwi-descriptions.git"
KIWI_DESCRIPTIONS_BRANCH = "f44"
KIWI_DESCRIPTIONS_COMMIT = "dfc49a5a10f69941179fdadd96aa6a5984f7c677"

#: Image profile from VARIANTS.md ("KDE Plasma Desktop Edition", type ``iso``).
BASE_KIWI_FILE = "Fedora.kiwi"
BASE_IMAGE_TYPE = "iso"
BASE_IMAGE_PROFILE = "KDE-Desktop-Live"

#: Host packages required to run the build. Versions observed in Fedora 44
#: repositories; the build records the actual installed versions in its manifest.
HOST_PACKAGES = {
    "kiwi-cli": "11.1.1",
    "kiwi-systemdeps": "11.1.1",
    "distribution-gpg-keys": "1.123",
    "git": None,
    "xorriso": None,
    "qemu-img": None,
}


@dataclass(frozen=True)
class HostRequirement:
    """A package or binary that must exist on the build host."""

    name: str
    kind: str  # "rpm" or "command"
    provides: str | None = None


HOST_REQUIREMENTS = (
    HostRequirement("kiwi-cli", "rpm", "kiwi-ng"),
    HostRequirement("kiwi-systemdeps", "rpm"),
    HostRequirement("distribution-gpg-keys", "rpm"),
    HostRequirement("git", "command"),
    HostRequirement("xorriso", "command"),
    HostRequirement("qemu-img", "command"),
)

#: Packages that make up the OpenQOS live environment layer.
LIVE_PACKAGES = [
    "python3",
    "lshw",
    "pciutils",
    "usbutils",
    "util-linux",
    "dmidecode",
    "kernel-modules",
]

#: Profiles exposed by ``openqos image plan --profile``.
PROFILES: dict[str, str] = {
    "generic": "Hardware-agnostic OpenQOS live image for any supported x86-64 machine.",
}


@dataclass
class BuildPlan:
    """A fully resolved description of what an ISO build will do."""

    profile: str
    description: str
    steps: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)
    overlay_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "description": self.description,
            "environment": self.environment,
            "steps": self.steps,
            "commands": self.commands,
            "overlay_files": self.overlay_files,
            "notes": self.notes,
        }


def build_plan(profile: str = "generic", *, work_directory: str = ".work/iso") -> dict[str, Any]:
    """Return the JSON-serialisable build plan for ``profile``."""
    if profile not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise ImageBuildError(f"unknown image profile {profile!r}; known profiles: {known}")

    description_dir = f"{work_directory}/kiwi-descriptions"
    output_dir = f"{work_directory}/out"
    plan = BuildPlan(
        profile=profile,
        description=PROFILES[profile],
        environment={
            "base_distribution": f"fedora-{FEDORA_RELEASE}",
            "architecture": "x86_64",
            "kiwi_descriptions": {
                "repository": KIWI_DESCRIPTIONS_REPOSITORY,
                "branch": KIWI_DESCRIPTIONS_BRANCH,
                "commit": KIWI_DESCRIPTIONS_COMMIT,
                "kiwi_file": BASE_KIWI_FILE,
                "image_type": BASE_IMAGE_TYPE,
                "image_profile": BASE_IMAGE_PROFILE,
            },
            "host_packages": HOST_PACKAGES,
            "live_packages": LIVE_PACKAGES,
            "work_directory": work_directory,
            "description_directory": description_dir,
            "output_directory": output_dir,
        },
        steps=[
            "Verify the host is a supported Fedora Linux release with KVM available.",
            "Verify kiwi-cli, kiwi-systemdeps, distribution-gpg-keys, git, xorriso, and qemu-img.",
            f"Clone kiwi-descriptions and check out {KIWI_DESCRIPTIONS_COMMIT}.",
            "Apply the OpenQOS overlay (package list, CLI, live-environment hooks).",
            "Run kiwi-build for the iso/KDE-Desktop-Live profile.",
            "Verify the produced ISO is non-empty and carries a valid ISO 9660 signature.",
            "Write a manifest with SHA-256, sizes, package versions, and source revisions.",
            "Optionally boot-test the ISO with QEMU/KVM (separate, explicitly requested step).",
        ],
        commands=[
            [
                "git",
                "clone",
                "--branch",
                KIWI_DESCRIPTIONS_BRANCH,
                KIWI_DESCRIPTIONS_REPOSITORY,
                description_dir,
            ],
            ["git", "-C", description_dir, "checkout", "--detach", KIWI_DESCRIPTIONS_COMMIT],
            [
                "./kiwi-build",
                f"--kiwi-description-dir={description_dir}",
                f"--kiwi-file={BASE_KIWI_FILE}",
                f"--image-type={BASE_IMAGE_TYPE}",
                f"--image-profile={BASE_IMAGE_PROFILE}",
                f"--output-dir={output_dir}",
            ],
        ],
        overlay_files=[
            "image/overlay/components/openqos.xml",
            "image/overlay/root/usr/local/bin/openqos",
        ],
        notes=[
            "The build must run on Fedora Linux; kiwi is not packaged for Windows.",
            "Only signed Fedora repositories are used; distribution-gpg-keys supplies the keys.",
            "The generic profile makes no hardware-specific assumptions.",
            "A hardware-specific ISO is not produced in Phase 1.",
        ],
    )
    return plan.to_dict()


def render_plan(plan: dict[str, Any]) -> str:
    """Render a plan as human readable text."""
    environment = plan["environment"]
    kiwi = environment["kiwi_descriptions"]
    lines = [
        f"OpenQOS image build plan ({plan['profile']})",
        f"  description : {plan['description']}",
        f"  base        : {environment['base_distribution']} {environment['architecture']}",
        f"  kiwi source : {kiwi['repository']}",
        f"  kiwi branch : {kiwi['branch']} at {kiwi['commit']}",
        f"  kiwi target : {kiwi['image_type']}/{kiwi['image_profile']} ({kiwi['kiwi_file']})",
        "",
        "host packages:",
    ]
    for name, version in environment["host_packages"].items():
        lines.append(f"  - {name}{' >= ' + version if version else ''}")
    lines.append("")
    lines.append("steps:")
    for index, step in enumerate(plan["steps"], start=1):
        lines.append(f"  {index}. {step}")
    lines.append("")
    lines.append("commands:")
    for command in plan["commands"]:
        lines.append("  " + " ".join(command))
    lines.append("")
    lines.append("notes:")
    for note in plan["notes"]:
        lines.append(f"  - {note}")
    return "\n".join(lines) + "\n"
