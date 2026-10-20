"""Installation planning and Kickstart generation.

The installer never partitions anything itself. It validates an explicitly
chosen disk, produces a Fedora Kickstart file, and hands execution to Anaconda.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from openqos.errors import InstallError

INSTALL_PLAN_SCHEMA_VERSION = "1.0.0"

ESP_MIB = 600
BOOT_MIB = 1024
MINIMUM_ROOT_MIB = 4096

#: Root filesystem written by the Kickstart. ``btrfs`` is deliberately not used:
#: Anaconda 44 accepts the ``part`` line but skips ``mkfs.btrfs`` on a freshly
#: initialised disk, leaving an unformatted root that cannot be mounted.
ROOT_FSTYPE = "ext4"

_KDE_GROUP = "kde-desktop-environment"

#: Decisions that the Kickstart can apply without running custom code at boot.
_INSTALL_STAGE_DECISIONS = {"storage-trim", "packages"}

_METALINK = "https://mirrors.fedoraproject.org/metalink?repo={repo}&arch=$basearch"
_GPG_KEY = "file:///etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-{release}-{suffix}"


def detect_release_version(root: Path | None = None) -> str | None:
    """Return the Fedora release of the running medium, if it is Fedora.

    Anaconda resolves repository URLs itself and can pick the wrong release,
    which then fails signature verification against the keys on the medium.
    """
    prefix = root or Path("/")
    for path in (prefix / "etc/os-release", prefix / "usr/lib/os-release"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        data = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                data[key.strip()] = value.strip().strip('"')
        if data.get("ID") != "fedora":
            return None
        return data.get("VERSION_ID") or None
    return None


def _repositories(release_version: str | None) -> list[dict[str, Any]]:
    if not release_version:
        return []
    keys = [
        _GPG_KEY.format(release=release_version, suffix="primary"),
        _GPG_KEY.format(release=release_version, suffix="$basearch"),
    ]
    return [
        {
            "name": "fedora",
            "metalink": _METALINK.format(repo=f"fedora-{release_version}"),
            "gpgkeys": keys,
        },
        {
            "name": "updates",
            "metalink": _METALINK.format(repo=f"updates-released-f{release_version}"),
            "gpgkeys": keys,
        },
    ]


def build_install_plan(
    profile: dict[str, Any],
    optimization_plan: dict[str, Any],
    disk: dict[str, Any],
    *,
    user_password: str | None = None,
    release_version: str | None = None,
) -> dict[str, Any]:
    """Build a validated installation plan for one explicit disk."""
    if not disk.get("eligible"):
        reasons = "; ".join(disk.get("reasons") or ["not eligible"])
        raise InstallError(f"refusing to install to {disk.get('path')}: {reasons}")
    if release_version is None:
        release_version = detect_release_version()
    name = disk["name"]
    machine = profile.get("machine") or {}
    firmware = machine.get("firmware") or {}
    policy_memory = _policy_memory(optimization_plan)

    install_decisions = [
        decision["id"]
        for decision in optimization_plan.get("decisions") or []
        if decision.get("status") == "plan" and decision["id"] in _INSTALL_STAGE_DECISIONS
    ]
    runtime_decisions = [
        decision["id"]
        for decision in optimization_plan.get("decisions") or []
        if decision.get("status") == "plan" and decision["id"] not in _INSTALL_STAGE_DECISIONS
    ]

    plan = {
        "schema_version": INSTALL_PLAN_SCHEMA_VERSION,
        "generated_at": _dt.datetime.now(tz=_dt.UTC).replace(microsecond=0).isoformat(),
        "source_profile": optimization_plan.get("selected_profile", {}).get("profile_id"),
        "policy": optimization_plan.get("policy"),
        "target": {
            "disk": disk["path"],
            "name": name,
            "size_gib": disk["size_gib"],
            "model": disk.get("model"),
            "transport": disk.get("transport"),
            "confirmation_token": name,
            "existing_partitions": list(disk.get("partitions") or []),
        },
        "layout": {
            "firmware": firmware.get("boot_mode"),
            "esp": {"mount": "/boot/efi", "fstype": "efi", "size_mib": ESP_MIB},
            "boot": {"mount": "/boot", "fstype": "ext4", "size_mib": BOOT_MIB},
            "root": {"mount": "/", "fstype": ROOT_FSTYPE, "minimum_mib": MINIMUM_ROOT_MIB},
            "swap": {
                "strategy": "zram",
                "zram_percent_of_ram": policy_memory.get("zram_percent_of_ram", 50),
            },
        },
        "packages": {
            "groups": [_KDE_GROUP],
            "packages": _packages(optimization_plan),
            "excluded": [],
        },
        "source": {
            "release_version": release_version,
            "repositories": _repositories(release_version),
        },
        "bootloader": {
            "loader": "grub2-efi" if firmware.get("boot_mode") == "uefi" else "grub2",
            "timeout_seconds": 5,
            "recovery": (
                "Fedora keeps the previous kernels (installonly_limit=3); the GRUB "
                "menu exposes them as a recovery boot path."
            ),
        },
        "include_openqos_payload": True,
        "user": {"name": "openqos", "groups": ["wheel"], "locked": user_password is None},
        "decisions_at_install": install_decisions,
        "decisions_at_runtime": runtime_decisions,
        "warnings": _warnings(profile, disk),
        "safety": {
            "destructive": True,
            "requires_confirmation": True,
            "confirmation_token": name,
            "erases": f"all partitions on {disk['path']}",
        },
    }
    if user_password is not None:
        plan["user"]["password_provided"] = True
    return plan


def _repo_lines(plan: dict[str, Any]) -> list[str]:
    source = plan.get("source") or {}
    lines = []
    for repository in source.get("repositories") or []:
        keys = ",".join(repository.get("gpgkeys") or [])
        line = f"repo --name={repository['name']} --metalink={repository['metalink']}"
        if keys:
            line += f" --gpgkey={keys}"
        lines.append(line)
    return lines


def _packages(optimization_plan: dict[str, Any]) -> list[str]:
    packages = set(optimization_plan.get("summary", {}).get("packages") or [])
    packages.update({"kernel", "dracut-config-rescue", "zram-generator"})
    return sorted(packages)


def _policy_memory(optimization_plan: dict[str, Any]) -> dict[str, Any]:
    zram_decision = next(
        (
            decision
            for decision in optimization_plan.get("decisions") or []
            if decision.get("id") == "memory-swap" and decision.get("status") == "plan"
        ),
        None,
    )
    if zram_decision:
        value = zram_decision.get("value")
        if isinstance(value, dict):
            return value
    return {}


def _warnings(profile: dict[str, Any], disk: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if disk.get("partitions"):
        warnings.append(
            f"{disk['path']} currently contains {len(disk['partitions'])} partition(s); "
            "they will be erased."
        )
    if (profile.get("storage") or {}).get("primary") == "hdd":
        warnings.append("Target is rotational storage; installation will be slower.")
    if (profile.get("machine") or {}).get("is_virtual_machine"):
        warnings.append("Target is a virtual machine disk.")
    return warnings


def validate_install_plan(plan: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if plan.get("schema_version") != INSTALL_PLAN_SCHEMA_VERSION:
        problems.append(f"schema_version must be {INSTALL_PLAN_SCHEMA_VERSION!r}")
    target = plan.get("target") or {}
    for key in ("disk", "name", "confirmation_token"):
        if not target.get(key):
            problems.append(f"target.{key} is required")
    if target.get("confirmation_token") != target.get("name"):
        problems.append("confirmation token must equal the disk name")
    if not str(target.get("disk", "")).startswith("/dev/"):
        problems.append("target.disk must be an absolute /dev path")
    layout = plan.get("layout") or {}
    for key in ("esp", "boot", "root", "swap"):
        if key not in layout:
            problems.append(f"layout.{key} is required")
    safety = plan.get("safety") or {}
    if safety.get("requires_confirmation") is not True:
        problems.append("safety.requires_confirmation must be true")
    if not plan.get("include_openqos_payload"):
        problems.append("the OpenQOS payload must be copied to the installed system")
    return problems


def render_kickstart(plan: dict[str, Any]) -> str:
    """Render the plan as a Fedora Kickstart file."""
    problems = validate_install_plan(plan)
    if problems:
        joined = "\n".join(f"  - {problem}" for problem in problems)
        raise InstallError(f"install plan is invalid:\n{joined}")

    target = plan["target"]
    name = target["name"]
    layout = plan["layout"]
    swap = layout["swap"]
    packages = plan["packages"]
    lines = [
        "#version=DEVEL",
        f"# OpenQOS installation plan {plan['schema_version']} "
        f"generated {plan['generated_at']}",
        f"# Target: {target['disk']} "
        f"({target.get('model') or 'unknown model'}, {target['size_gib']} GiB)",
        "# THIS FILE ERASES THE TARGET DISK WHEN USED BY ANACONDA.",
        "text",
        "lang en_US.UTF-8",
        "keyboard us",
        "timezone UTC --utc",
        "selinux --enforcing",
        "firewall --enabled",
        "rootpw --lock",
        "user --name=openqos --groups=wheel --lock",
        f"ignoredisk --only-use={name}",
        "zerombr",
        f"clearpart --all --initlabel --drives={name}",
        f"part /boot/efi --fstype=efi --size={layout['esp']['size_mib']} --ondisk={name}",
        f"part /boot --fstype=ext4 --size={layout['boot']['size_mib']} --ondisk={name}",
        f"part / --fstype={layout['root']['fstype']} --grow "
        f"--size={layout['root']['minimum_mib']} --ondisk={name}",
        f"bootloader --timeout={plan['bootloader']['timeout_seconds']}",
        "network --bootproto=dhcp --device=link --activate",
        *_repo_lines(plan),
        "",
        "%packages",
    ]
    lines.extend(f"@{group}" for group in packages["groups"])
    lines.extend(packages["packages"])
    lines.extend(f"-{package}" for package in packages["excluded"])
    lines.extend(
        [
            "%end",
            "",
            "# Copy the OpenQOS tooling from the live environment into the target.",
            "%post --nochroot --erroronfail",
            "set -eu",
            'mkdir -p "$ANA_INSTALL_PATH/opt/openqos"',
            'cp -a /opt/openqos/. "$ANA_INSTALL_PATH/opt/openqos/" 2>/dev/null || true',
            'install -D -m 0755 /usr/local/bin/openqos '
            '"$ANA_INSTALL_PATH/usr/local/bin/openqos" || true',
            'install -D -m 0755 /usr/local/bin/openqos-summary-window '
            '"$ANA_INSTALL_PATH/usr/local/bin/openqos-summary-window" || true',
            'install -D -m 0755 /usr/lib/systemd/system/openqos-scan.service '
            '"$ANA_INSTALL_PATH/usr/lib/systemd/system/openqos-scan.service" || true',
            'if [ -f /var/lib/openqos/plan.json ]; then '
            'install -D -m 0644 /var/lib/openqos/plan.json '
            '"$ANA_INSTALL_PATH/var/lib/openqos/plan.json"; fi',
            'cat > "$ANA_INSTALL_PATH/etc/openqos-release" <<\'EOF\'',
            "OpenQOS installed system",
            f"profile={plan['source_profile']}",
            f"policy={plan['policy']}",
            "EOF",
            "%end",
            "",
            "%post --erroronfail",
            "set -eu",
            "systemctl enable openqos-scan.service",
        ]
    )
    if "storage-trim" in plan["decisions_at_install"]:
        lines.append("systemctl enable fstrim.timer")
    lines.extend(
        [
            "install -d -m 0755 /var/lib/openqos",
            f"printf '%s\\n' 'zram percentage: {swap['zram_percent_of_ram']}' "
            "> /etc/openqos-swap.conf",
            "%end",
            "",
            "reboot",
            "",
        ]
    )
    return "\n".join(lines)
