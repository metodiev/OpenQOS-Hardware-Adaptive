# Security model

## Principles

1. **Read-only discovery.** Hardware collection reads `/sys` and `/proc` and
   nothing else. It never writes, mounts, or changes state.
2. **No shell.** The scanner never spawns a process. Device-provided strings
   (product names, serials, model strings) are only ever stored as JSON text.
3. **Deterministic subprocess use.** The only external commands are `git` and
   `./kiwi-build`, invoked with an argument list, `shell=False`, and a fixed
   working directory. No user or device data is interpolated into a command.
4. **Explicit privilege boundaries.** Scanning runs unprivileged. Image creation
   requires root and is gated behind `--execute` plus a passing preflight.
5. **Versioned data contracts.** Every JSON document carries a schema version and
   is validated before use. A malformed profile or inventory is rejected, never
   "repaired" into something executable.
6. **Secure defaults preserved.** OpenQOS does not disable Secure Boot, SELinux,
   or signature verification. The build consumes signed Fedora repositories and
   `distribution-gpg-keys`.

## What the Phase 1 code can and cannot do

| Capability | Phase 1 |
| --- | --- |
| Read hardware state | Yes |
| Write a JSON file | Yes, to the path the user names |
| Execute a shell command derived from device data | No |
| Partition, format, or mount a disk | No |
| Modify `/boot`, the bootloader, or firmware settings | No |
| Install packages on the host | No |
| Download anything | No (only `git clone` during an explicit `--execute` build) |

## Threat model

| Threat | Mitigation |
| --- | --- |
| Malicious device strings (command injection) | No shell, no `eval`, no `PATH` lookup by device data; asserted by a test |
| Malformed or hostile inventory supplied to a later phase | JSON Schema validation with `additionalProperties: false` plus structural checks |
| Supply-chain compromise of the ISO inputs | Pinned commit, signed Fedora repositories, manifest with SHA-256 and source revision |
| Accidental data disclosure in bug reports | `--privacy` removes hostname, serials, MAC addresses, and cmdline; the committed sample is privacy-mode |
| Running the wrong thing as root | `--execute` required; preflight must fully pass; the build never touches the host's disks |
| Partial hardware knowledge causing a bad decision | Missing data is recorded in `unavailable`; later phases must treat it as unknown |

## Logging

The scanner has no logging of its own; the document records what was read and
what was not. When `--privacy` is used, no personal identifiers reach the file at
all, which makes the artifact safe to attach to a bug report.

Build logs contain the KIWI output and the pinned revisions. They do not contain
credentials.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
