# OpenQOS

OpenQOS is a hardware-adaptive Linux operating system for desktop and laptop
computers. It detects the machine it runs on, builds a versioned hardware
inventory, and will use that inventory to select drivers, packages, and
performance policies and to install itself onto a chosen disk.

OpenQOS is built on **Fedora Linux 44** and uses existing, supported tooling
(KIWI, Anaconda, dracut, systemd, KDE Plasma) instead of reimplementing kernel
or userspace infrastructure.

## Project status

This repository is at the end of **Phase 1 (Foundation)**. It contains real,
tested code — not placeholder files — and it deliberately stops short of
anything that could modify a machine.

| Area | Status |
| --- | --- |
| Repository structure, packaging, linting, typing, tests | **Implemented** |
| Read-only hardware inventory (`openqos hardware scan`) | **Implemented** |
| Versioned JSON schema + validator (`openqos hardware validate`) | **Implemented** |
| ISO build plan and preflight (`openqos image plan/build`) | **Implemented** |
| ISO build execution on Fedora (KIWI overlay) | **Verified** — `releases/openqos-generic-44.iso`, booted under BIOS and UEFI |
| Hardware profile + compatibility rules (`openqos profile`) | **Implemented** (master roadmap Phase 3) |
| Optimization planner (`openqos optimize`) | **Implemented** — plan only, nothing applied (Phase 3) |
| Live USB integration (`openqos-scan.service`, boot report) | **Implemented** (Phase 4) |
| Installer | Planned (Phase 5) |
| Runtime adaptation service | Planned |
| Benchmarks | Planned (Phase 7) |

Nothing in this repository partitions disks, writes to `/boot`, or changes
firmware settings.

## Requirements

* Python **3.11+** for the tooling (the live image uses the Fedora system Python).
* Linux for a real hardware scan. Windows and macOS can run the tests and the
  build planner, but there is no `/sys` or `/proc` to scan.
* Fedora 44 for ISO creation (KIWI is not packaged elsewhere).

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

pytest                          # 107 tests
ruff check .
mypy
```

### Released artifact

`releases/openqos-generic-44.iso` is a boot-tested Fedora 44 KDE live image with
the OpenQOS tooling installed. See
[docs/iso-building.md](docs/iso-building.md#verified-build) for the recorded
build inputs, SHA-256, and boot-test evidence.

### Scan the current machine

```bash
openqos hardware scan --output hardware-profile.json
openqos hardware validate hardware-profile.json
```

On a laptop the summary looks like:

```
hardware summary
  os           : Fedora Linux 44 (KDE Plasma Desktop Edition)
  kernel       : 6.16.3-200.fc44.x86_64
  firmware     : uefi / secure boot enabled
  cpu          : 12th Gen Intel(R) Core(TM) i7-1260P (8 logical, 4 physical)
  memory       : 15360 MiB
  graphics     : 2 adapter(s), primary=i915, hybrid=True
  storage      : 1 device(s): nvme0n1
  warnings     : 0
  unavailable  : 3 entry(ies)
```

Use `--privacy` to omit the hostname, serial numbers, MAC addresses, and the
kernel command line. `docs/samples/hardware-profile.json` is a privacy-mode
example produced from the synthetic laptop fixture.

The scanner never executes commands. Everything is read from `/sys` and
`/proc`, so a device string can never reach a shell.

### Validate an inventory

```bash
openqos hardware validate hardware-profile.json --quiet   # exit code 1 on problems
openqos hardware schema --output inventory-schema.json
```

Validation always performs a built-in structural check and additionally runs
full JSON Schema validation when `jsonschema` is installed.

### Plan an ISO build

```bash
openqos image plan                 # human readable
openqos image plan --format json   # machine readable
openqos image build                # preflight + plan, changes nothing
```

`image build` only performs the build with `--execute`, and only after all
required preflight checks pass. See [docs/iso-building.md](docs/iso-building.md).

### Build a profile and an optimization plan

```bash
openqos hardware scan --privacy --output inventory.json
openqos profile explain --inventory inventory.json
openqos profile build   --inventory inventory.json --output profile.json
openqos optimize        --inventory inventory.json --policy balanced --format json
```

The planner explains every decision and never applies anything. See
[docs/profiles-and-optimization.md](docs/profiles-and-optimization.md).

## Repository layout

```
src/openqos/            Python package
  hardware/             read-only collectors, scanner, validation
  imagebuilder/         pinned build plan, preflight, overlay, manifest
  schemas/              versioned JSON Schema documents
image/overlay/          files injected into the KIWI description
tests/                  unit tests and synthetic hardware fixtures
docs/                   architecture, hardware support, ISO building, security
scripts/                maintenance helpers (sample inventory generation)
```

## Design rules

1. Hardware discovery is read-only and unprivileged.
2. No shell, no `eval`, no command constructed from device data.
3. Every document is versioned and validated.
4. Missing information is reported as `unavailable`, never guessed.
5. Destructive operations require explicit confirmation (installer, Phase 3).
6. No optimization is claimed without a measurement.

## Documentation

* [Architecture](docs/architecture.md)
* [Development environment](docs/development-environment.md)
* [Hardware support and detection limits](docs/hardware-support.md)
* [Profiles and optimization](docs/profiles-and-optimization.md)
* [Live USB integration](docs/live-usb.md)
* [ISO building](docs/iso-building.md)
* [Security model](docs/security.md)
* [Contributing](CONTRIBUTING.md)
* [Security policy](SECURITY.md)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
