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
   * `root/usr/local/bin/openqos` and `root/opt/openqos/src/openqos` are installed;
   * `config.sh.append` is appended to `config.sh` exactly once.
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

## Current status

The build pipeline is implemented and unit tested, but **no ISO has been built
yet**: this development environment has no Fedora host, no `kiwi-ng`, and no
`/dev/kvm`. Do not treat the ISO path as proven until a build and a QEMU boot
test have been recorded here.
