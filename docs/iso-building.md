# Building the OpenQOS ISO

The image builder wraps the official Fedora KIWI descriptions. It does not fork
them: it checks out a pinned commit, adds a small overlay, and records exactly
what was built.

## Pinned inputs

| Input | Value |
| --- | --- |
| Base release | Fedora Linux 44 (x86-64) |
| KIWI descriptions | `https://forge.fedoraproject.org/releng/kiwi-descriptions.git` |
| Branch | `f44` |
| Commit | see `KIWI_DESCRIPTIONS_COMMIT` in `src/openqos/imagebuilder/plan.py` |
| Image type / profile | `iso` / `KDE-Desktop-Live` |
| KIWI version at time of writing | 11.1.1 (`kiwi-cli`, `kiwi-systemdeps`) |
| GPG keys | `distribution-gpg-keys` 1.123 |

Pin values are asserted by tests so a careless edit is caught.

## Host requirements

The build must run on Fedora Linux; KIWI depends on `dnf5`, loop devices, and
`chroot`. A current Fedora 44 installation with at least 20 GiB free in the work
directory is recommended (Fedora upstream suggests 10 GiB; the extra headroom
avoids partial downloads failing late).

```bash
sudo dnf install -y kiwi-cli kiwi-systemdeps distribution-gpg-keys git xorriso qemu-img
```

`qemu-img` and `/dev/kvm` are only required for the optional boot test.

## Step 1 — inspect the plan

```bash
openqos image plan
openqos image plan --format json --output build-plan.json
```

## Step 2 — preflight

```bash
openqos image build
```

This prints every check and does **not** build. Required checks are:
Linux host, Fedora distribution, `kiwi-cli`, `kiwi-systemdeps`,
`distribution-gpg-keys`, `git`, `xorriso`, `qemu-img`, root privileges, and
free disk space. `/dev/kvm` and the exact Fedora version are warnings only.

## Step 3 — build

```bash
sudo .venv/bin/openqos image build --execute --work-directory /var/tmp/openqos
```

What happens:

1. `git clone --branch f44` and `git checkout --detach <pinned commit>`.
2. `image/overlay` is applied to the checkout:
   * `components/openqos.xml` adds the OpenQOS live packages;
   * the include line is added to `Fedora.kiwi` exactly once;
   * `root/usr/local/bin/openqos` and `root/opt/openqos/src/openqos` are
     installed through KIWI's description `root/` overlay;
   * `root/etc/openqos-release` records the pinned release and OpenQOS version.

   No script is injected into `config.sh`; the overlay is purely declarative.
3. `./kiwi-build --image-type=iso --image-profile=KDE-Desktop-Live` runs with
   output logged to `<work-dir>/kiwi-build.log`.
4. The result is verified: file size, ISO 9660 volume descriptor, SHA-256.
5. `releases/<name>.manifest.json` and `releases/<name>.iso.sha256` are written,
   and the ISO is copied into `releases/`.

The manifest contains the artifact hash and size, the profile, the pinned KIWI
source, the host package list, the OpenQOS git revision, and the overlay files
that were applied.

## Step 4 — boot test (optional, separate)

```bash
qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 \
  -drive file=releases/openqos-generic.iso,media=cdrom,readonly=on \
  -boot d -display gtk
```

Inside the live session:

```bash
openqos hardware scan --output /tmp/inventory.json
openqos hardware validate /tmp/inventory.json
```

## Reproducing on a non-Fedora host

Not supported by KIWI. Options, in order of preference:

1. Use a Fedora virtual machine (`qemu`, `virt-manager`, or a cloud instance).
2. Use a Fedora container with privileges (`podman run --privileged`), accepting
   that loop devices and `chroot` need extra setup.
3. Run only the planning, preflight, overlay, and manifest code, which is
   platform independent and covered by the test suite.

## Verified build

A complete build and boot test was performed on **2026-10-20**:

| Item | Value |
| --- | --- |
| Build host | Fedora Linux 44 container (Docker Desktop 29.7.2), x86-64, root |
| `kiwi-cli` / `kiwi-systemdeps` | 11.1.1-2.fc44 |
| `distribution-gpg-keys` | 1.123-1.fc44 |
| KIWI descriptions | `f44` @ `dfc49a5a10f69941179fdadd96aa6a5984f7c677` |
| Target | `iso` / `KDE-Desktop-Live` |
| Duration | about 8-15 minutes (package download and EROFS compression included) |
| Artifact | `releases/openqos-generic-44.iso` |
| Size | 3,414,626,304 bytes (3256.3 MiB) |
| SHA-256 | `d85b1e2a1fd5ed09460d3ba1fb07af327c724b95adb9d1778195b13171da8bfe` |
| Source revision | `a1f5597144788da7fe3ece7e6e4082ca9bb2ad7f` |
| Manifest | `releases/openqos-generic-44.manifest.json` |

Build command (inside the container, repository at `/work`):

```bash
PYTHONPATH=/work/src python3 -m openqos image build --execute \
    --work-directory /var/tmp/openqos-iso \
    --releases-directory /var/tmp/openqos-releases
```

### What was verified

1. All preflight checks passed (`linux-host`, `fedora-host`, `fedora-release`,
   `package:*`, `command:*`, `root-privileges`, `disk-space`).
2. `kiwi-ng` produced a hybrid ISO with both El Torito entries:
   BIOS (`/boot/x86_64/loader/eltorito.img`) and UEFI (61440-block EFI image).
3. The ISO 9660 volume descriptor and SHA-256 were checked by
   `openqos image build`.
4. The live root was extracted from `/LiveOS/squashfs.img` (EROFS in Fedora 44)
   and contains:
   * `/usr/local/bin/openqos` (mode 0755),
   * `/opt/openqos/src/openqos/**` (mode 0644, all collectors and the schema),
   * `/etc/openqos-release` with `base=Fedora Linux 44`, `openqos=0.1.0`.
5. The shipped CLI was executed from the extracted tree:
   `openqos 0.1.0`, and `openqos hardware scan` + `validate` both succeeded
   against a live kernel.
6. The ISO was booted under QEMU 10.2.2 with KVM:
   * SeaBIOS (BIOS) boot, 4 GiB RAM, 4 vCPU, virtio-vga;
   * OVMF (UEFI) boot with the same settings.

   Both reached the KDE Plasma live desktop with the *Welcome to Fedora Linux!*
   dialog and the **Install to Hard Drive** launcher.
7. With Phase 4 included, the boot report was verified: `systemctl --root`
   reports `openqos-scan.service` as `enabled` in the image, and after boot the
   KDE session automatically opened a Konsole window containing the generated
   `OpenQOS hardware report` (system, CPU, memory, graphics, storage, network,
   firmware, selected profile, policy, decisions, packages, and compatibility
   notes).

### Not yet verified

* The Anaconda installer itself was not run to completion; that is Phase 3 work.
* Nothing was booted on physical hardware, so no hardware-compatibility claim is
  made.
* The ISO was produced inside a privileged Fedora 44 container rather than on a
  bare-metal Fedora host. The build steps are identical, but a bare-metal run
  remains to be recorded.
* `grub2-probe: failed to get canonical path of 'overlay'` appears during the
  `grub2-efi-x64` post-install scriptlet inside the container. It is a
  container-filesystem artefact, not an OpenQOS change; the resulting ISO still
  boots on both firmware types.
