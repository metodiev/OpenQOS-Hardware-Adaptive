# Security policy

## Supported versions

OpenQOS is pre-alpha. Only the current `main` branch receives fixes; there are
no supported releases yet.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Report it
privately to the maintainers of this repository (for example through a private
security advisory on GitHub) and include:

* the affected component and version,
* a description of the impact,
* reproduction steps or a proof of concept,
* whether the issue is reachable without root privileges.

You can expect an acknowledgement within a few days. Please allow time for a fix
before public disclosure.

## Scope

In scope:

* the hardware scanner (parsing of device data, denial of service, data
  disclosure),
* the inventory validator and schema handling,
* the image build pipeline (pinned inputs, overlay application, manifest
  integrity),
* anything that could turn device-provided data into code execution.

Out of scope for now, because the features do not exist yet:

* installer and partitioning behaviour,
* runtime adaptation,
* kernel and bootloader policy.

## Current guarantees

Documented in detail in [docs/security.md](docs/security.md). In short:

* hardware discovery is unprivileged and read-only;
* no shell is involved anywhere in discovery;
* every document is schema-versioned and validated;
* image builds use signed Fedora repositories and a pinned upstream commit;
* `--privacy` removes hostnames, serial numbers, MAC addresses, and the kernel
  command line from the inventory.
