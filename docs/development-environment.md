# Development environment

This is the environment in which Phase 1 was implemented and verified. It is
recorded so results can be reproduced and so the limits of the testing are
explicit.

## Host used for development

| Item | Value |
| --- | --- |
| Host OS | Windows 11, x86-64 |
| CPU | AMD Ryzen 9 9950X3D (16 cores / 32 threads) |
| Python (tooling) | 3.13.5 in a local `.venv` |
| Git | Git for Windows |
| Container runtime | Docker Desktop 29.7.2 (Linux engine), `fedora:44` image |
| WSL | Ubuntu 24.04.4 LTS, kernel 6.6.87.2-microsoft-standard-WSL2 |
| Free disk on `D:` | about 3.4 TB (the ISO needs roughly 15 GB of scratch space) |
| Hypervisor for boot tests | QEMU 10.2.2 with KVM (inside the container), OVMF and SeaBIOS |

No Fedora installation was available on bare metal, and `/dev/kvm` is not
exposed on the Windows host itself; both were provided by the container.

## Toolchain installed for the ISO build

Inside the Fedora 44 container:

```bash
dnf install -y kiwi-cli kiwi-systemdeps distribution-gpg-keys \
    git xorriso qemu-img e2fsprogs dosfstools
```

Resulting versions:

```
kiwi-cli-11.1.1-2.fc44.noarch
kiwi-systemdeps-11.1.1-2.fc44.x86_64
distribution-gpg-keys-1.123-1.fc44.noarch
KIWI (next generation) version 11.1.1
glibc 2.4x / Python 3.14.8 (container interpreter)
```

`qemu-system-x86-core` and `edk2-ovmf` were added only to boot-test the result.

## Reproducing the checks

Python tooling (any OS):

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
ruff check .
mypy
```

ISO build (Fedora host, or a privileged Fedora container with the repository
bind-mounted at `/work`):

```bash
PYTHONPATH=/work/src python3 -m openqos image build --execute \
    --work-directory /var/tmp/openqos-iso \
    --releases-directory /var/tmp/openqos-releases
```

Boot test (needs KVM and OVMF):

```bash
qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 -machine q35 -cpu host \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/ovmf/OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=/var/tmp/OVMF_VARS.fd \
  -drive file=openqos-generic-44.iso,media=cdrom,readonly=on \
  -boot d -device virtio-vga -display none -vnc :0 \
  -monitor unix:/var/tmp/mon.sock,server=on,wait=off
```

The live session reaches the KDE Plasma desktop with the *Welcome to Fedora
Linux!* dialog and the *Install to Hard Drive* launcher.

## Known container artefacts

* `grub2-efi-x64` prints `grub2-probe: failed to get canonical path of
  'overlay'` during its `%posttrans` scriptlet. It comes from the container's
  overlayfs root, not from OpenQOS, and does not affect the produced ISO.
* `/sys/block` inside the container exposes the Docker VM's disks, so a scan
  performed there describes the container, not the physical host. Hardware
  scanning is meant to run on the machine being profiled.
* WSL reports the Microsoft virtual GPU (`dxgkrnl`) and the WSL2 kernel. That is
  what the kernel exposes; it is not a representation of the laptop hardware.
