# OpenQOS architecture

## Scope of this document

This describes the architecture implemented so far and the interfaces that
later phases build on. Components that do not exist yet are listed explicitly
as planned.

Phase 1 delivered the hardware inventory and the ISO pipeline; Phase 2 added the
normalised profile, the data-driven compatibility rules, and the optimization
planner (which produces plans but applies nothing).

## Component map

| Component | Package | Status |
| --- | --- | --- |
| Hardware discovery | `openqos.hardware` | Implemented (read-only) |
| Inventory schema and validation | `openqos.schemas`, `openqos.hardware.validate` | Implemented |
| Image builder | `openqos.imagebuilder` | Implemented and verified (built + boot-tested) |
| Hardware profiles and compatibility rules | `openqos.profiles` | Implemented (Phase 3) |
| Live-session integration | `openqos.status`, overlay units | Implemented (Phase 4) |
| Optimization planner | `openqos.optimizer` | Implemented (Phase 3, plan only) |
| Installer | — | Planned |
| Runtime adaptation | — | Planned |
| Benchmarks | — | Planned |

## Data flow

```
/sys + /proc (read-only)
        |
        v
collectors  ->  warnings/unavailable  ->  scanner  ->  versioned JSON inventory
                                                              |
                                                     schema validation
                                                              |
                                          (Phase 2) normalized hardware profile
                                                              |
                                          (Phase 2) compatibility rules
                                                              |
                                             configuration plan + rationale
                                                              |
                                          (Phase 3) installer / bootloader
```

The inventory is the only contract between phases. Each document carries
`schema_version`, so a newer scanner cannot silently break an older optimizer.

## Hardware discovery

`openqos.hardware.scanner.scan(root, privacy=False)` runs one collector per
device class and assembles the document. Collectors are pure readers:

* They never invoke external binaries (no `lspci`, no `dmidecode`).
* They never write, mount, or change state.
* They take an explicit filesystem root (`/` by default) so tests can run
  against synthetic trees on any operating system.

Device identity, class, and bound driver come from sysfs `uevent` files and the
`driver` symlinks. `uevent` is preferred because it is a stable kernel interface
and is trivial to fixture.

### Failure handling

Two separate channels make partial knowledge explicit:

* `warnings` — the data was read but looks wrong (for example an EFI variable
  that is shorter than expected).
* `unavailable` — the data could not be read at all, with a reason the user can
  act on (missing file, requires root, unsupported firmware).

A collector that finds nothing never raises; it records an `unavailable` entry.
This is why the scanner also works inside a container or WSL.

### Privacy mode

`privacy=True` removes the hostname, DMI vendor/product strings, storage and USB
serials, MAC addresses, and the kernel command line. Everything needed for
compatibility decisions (vendor/product IDs, drivers, topology, firmware mode,
power capabilities) is retained.

## Inventory schema

`src/openqos/schemas/hardware-inventory-<version>.json` is a JSON Schema
(Draft 2020-12) that mirrors the emitted document with
`additionalProperties: false`. Adding a field therefore requires a schema
change, which keeps documentation and output in sync.

Validation runs in two layers:

1. a dependency-free structural check, always available in a minimal live
   environment;
2. full JSON Schema validation when `jsonschema` is installed.

## Image builder

The ISO is produced from the official Fedora KIWI descriptions:

* repository: `https://forge.fedoraproject.org/releng/kiwi-descriptions.git`
* branch: `f44`
* commit: pinned in `openqos.imagebuilder.plan.KIWI_DESCRIPTIONS_COMMIT`
* target: `iso` / `KDE-Desktop-Live`

`openqos image build` performs preflight checks, clones the pinned commit,
applies the OpenQOS overlay (`image/overlay`), runs `kiwi-build`, verifies the
ISO 9660 signature, and writes a manifest with SHA-256, size, source revision,
and the pinned inputs.

The overlay copies `src/openqos` into `/opt/openqos/src` inside the image and
installs a `/usr/local/bin/openqos` wrapper. That means the live image contains
exactly the sources that were built — no separately packaged copy can drift.
The overlay is declarative: KIWI imports the description's `root/` directory, so
no post-install shell hook is injected into Fedora's `config.sh`.

Applying the overlay is idempotent: the `Fedora.kiwi` include line is added at
most once.

## Command-line interface

```
openqos hardware scan|validate|schema
openqos image plan|build|verify
openqos --version
```

Exit codes: `0` success, `1` validation failure, `2` usage or expected runtime
error. Errors are printed to stderr; JSON is only ever written to stdout or to
the requested file.

## Why no external tools

The original design listed `lspci`, `lsusb`, and `dmidecode`. Phase 1 does not
use them because:

* sysfs/procfs already exposes vendor/device IDs, classes, drivers, and
  firmware state;
* parsing text output of external binaries is fragile across versions;
* a `PATH`-resolved binary is an execution surface that a hostile environment
  could influence.

`dmidecode` is still installed in the live image for manual diagnostics, and its
absence is recorded as `unavailable: memory.modules` rather than being guessed.

## Testing strategy

* Synthetic sysfs trees (`tests/hardware-fixtures/builders.py`) describe an
  Intel hybrid laptop, an AMD desktop, and an almost-empty host.
* Every collector is unit tested against those trees.
* The full document is validated against the JSON Schema.
* A hostile device string (`; rm -rf /`, backticks, `$()`) is asserted to be
  preserved as data and never interpreted.
* The image builder is tested with fake commands and fake ISO payloads; the
  repository never requires root or a Fedora host to run the suite.

Physical-hardware testing is not claimed anywhere in this repository.
