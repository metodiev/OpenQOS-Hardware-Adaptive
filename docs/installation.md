# Automated installation

Phase 5 adds an installer that never guesses. It enumerates disks, refuses
unsafe targets, generates a Fedora **Kickstart** file from the validated
optimization plan, and only hands control to Anaconda after an explicit
confirmation token.

Nothing in this repository partitions a disk on its own.

## Commands

```bash
openqos install disks
openqos install disks --format json

openqos install plan --inventory inventory.json --disk /dev/nvme0n1 \
                     --output install-plan.json --kickstart install.ks

openqos install run --plan install-plan.json --confirm nvme0n1
openqos install run --plan install-plan.json --confirm nvme0n1 --execute
```

* `install disks` is read-only and always safe.
* `install plan` is read-only; it writes a plan and a Kickstart file.
* `install run` without `--execute` prints the exact Anaconda command and touches
  nothing. With `--execute` it runs `anaconda --kickstart ... --text` and writes
  a machine-readable report.

## Disk eligibility

A disk is only eligible when the evidence says so. The following are refused
with a reason:

| Condition | Reason |
| --- | --- |
| removable media | `removable media` |
| optical drive | `optical drive` |
| smaller than 20 GiB | `smaller than 20 GiB` |
| hosts the live medium (`/run/initramfs/live`, …) | `hosts the running live medium` |
| hosts `/` | `hosts the running root filesystem` |
| any partition is mounted | `has mounted filesystems` |
| contains partitions | `contains existing partitions` |

The refusal for existing partitions is deliberate: installing to such a disk
destroys them, so the operator has to choose a disk that is either empty or has
been prepared explicitly. The plan records the partitions it will erase.

Existing operating systems are visible through those partitions and mount
points. OpenQOS never selects a disk automatically, and there is no
"first disk" default.

## Layout

| Mount | Filesystem | Size |
| --- | --- | --- |
| `/boot/efi` | `efi` | 600 MiB |
| `/boot` | `ext4` | 1024 MiB |
| `/` | `btrfs` | grows to fill the disk, minimum 4 GiB |
| swap | `zram` (no partition) | per policy (default 50% of RAM) |

* UEFI is required for the automated path; the bootloader entry is `grub2-efi`.
  A BIOS path (`grub2`) is selected when the inventory reports BIOS firmware.
* Fedora keeps the previous kernels (`installonly_limit=3`), and the GRUB menu
  exposes them. That is the recovery boot path; nothing is removed from the
  bootloader configuration.
* Accounts are **locked** (`rootpw --lock`, `user --name=openqos --lock`) unless
  a password is supplied. A locked account is safer than a default password.
* SELinux is `--enforcing` and the firewall is enabled; the installer does not
  weaken either.

## Kickstart

The generated file is ordinary Fedora Kickstart:

```
ignoredisk --only-use=nvme0n1
clearpart --all --initlabel --drives=nvme0n1
part /boot/efi --fstype=efi --size=600 --ondisk=nvme0n1
part /boot --fstype=ext4 --size=1024 --ondisk=nvme0n1
part / --fstype=btrfs --grow --size=4096 --ondisk=nvme0n1
...
%packages
@kde-desktop-environment
kernel
dracut-config-rescue
zram-generator
<packages from the optimization plan>
%end
```

`%post --nochroot` copies the OpenQOS tooling from the live environment
(`/opt/openqos`, `/usr/local/bin/openqos`, the systemd unit) into the target and
writes `/etc/openqos-release`. `%post` runs in the target and enables
`openqos-scan.service` plus `fstrim.timer` when the plan planned TRIM.

Only decisions the Kickstart can apply safely are marked `decisions_at_install`
(currently package selection and `fstrim.timer`). CPU governor, EPP, platform
profile and zram configuration stay in `decisions_at_runtime` for the runtime
service.

## Safety properties

1. The target must be named explicitly (`--disk /dev/...`).
2. `install run` requires `--confirm <disk name>` to match the token in the plan.
3. An ineligible disk raises before any file is generated.
4. The plan states `safety.destructive = true`, the exact device, and which
   partitions will be erased.
5. `--execute` is required to start Anaconda; the default is a dry run.
6. Logs go to `/var/log/openqos/install.log`, the report to
   `/var/lib/openqos/install-report.json`.

## Status

Planning, validation, Kickstart generation, confirmation, and report writing are
covered by unit tests (13 installer tests, including refusal of mounted, live,
removable, small, and partitioned disks).

**A full Anaconda installation has not been executed yet.** The next verification
step is to install into a blank QEMU disk and boot it; until that is recorded
here, treat the execution path as unverified.
