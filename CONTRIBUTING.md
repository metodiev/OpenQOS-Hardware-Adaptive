# Contributing to OpenQOS

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Before every commit

```bash
ruff check .
mypy
pytest
```

All three must pass. CI runs the same commands on Python 3.11 and 3.13
(Ubuntu), so also keep the code compatible with the minimum supported version.

## Code rules

1. Python 3.11+ syntax, type annotations everywhere; `mypy --strict` is enabled.
2. Hardware access is read-only and goes through `openqos.hardware.readers.FsRoot`.
   Do not call `open()`, `Path.read_text()`, or `subprocess` directly from a
   collector — pass the root so the collector stays testable.
3. Never build a command string from device or user data. Use argument lists.
4. A collector that cannot read something must record an `unavailable` entry;
   it must not raise and must not substitute a guess.
5. New inventory fields require a schema update in `src/openqos/schemas/` and a
   fixture that exercises them.
6. Behaviour changes need a test. "It works on my machine" is not evidence.

## Adding a hardware fixture

`tests/hardware-fixtures/builders.py` builds synthetic sysfs trees. Add a
builder function that models a real machine, register it as a fixture in
`tests/conftest.py`, and cover the interesting properties (driver binding,
hybrid graphics, rotational storage, missing firmware features).

Fixtures must work on Windows, so directory names cannot contain `:`.
PCI slots are stored as `0000_00_02.0` directories while the real slot name
lives in the `uevent` file, which is what the scanner reads.

## Changing the pinned Fedora inputs

`src/openqos/imagebuilder/plan.py` holds the release, repository, branch, commit,
and image profile. Update them together, adjust the tests, and record in the
pull request which upstream release notes you verified.

## Destructive operations

Never add code that partitions, formats, or installs to the host machine as part
of routine development. Test such behaviour in a virtual machine with disposable
disks, and require explicit user confirmation in the product code.

## Commits

* One logical change per commit.
* Describe *why* in the message body when the reasoning is not obvious.
* Do not commit secrets, credentials, or personal hardware inventories. Use
  `--privacy` when generating a sample.

## License

Contributions are accepted under GPL-3.0-or-later.
