"""Read-only access to kernel-exposed hardware information.

Every helper here only reads from ``sysfs``/``procfs`` style trees. Nothing in
this module executes commands, writes to disk, or requires privileges, which
keeps hardware discovery safe to run inside a live environment.
"""

from __future__ import annotations

import os
from pathlib import Path


class FsRoot:
    """A filesystem root that contains ``sys``, ``proc`` (and optionally ``etc``).

    Using an explicit root keeps the collectors testable without a Linux host:
    tests point the root at a synthetic directory tree.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FsRoot({self.root!s})"

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def exists(self, *parts: str) -> bool:
        return self.path(*parts).exists()

    def is_dir(self, *parts: str) -> bool:
        return self.path(*parts).is_dir()

    def text(self, *parts: str) -> str | None:
        """Return the stripped contents of a text file, or ``None``."""
        try:
            return self.path(*parts).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None

    def raw_bytes(self, *parts: str) -> bytes | None:
        try:
            return self.path(*parts).read_bytes()
        except OSError:
            return None

    def integer(self, *parts: str) -> int | None:
        value = self.text(*parts)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def entries(self, *parts: str) -> list[Path]:
        """List directory entries sorted by name, ignoring unreadable dirs."""
        try:
            return sorted(self.path(*parts).iterdir(), key=lambda entry: entry.name)
        except OSError:
            return []

    def subdirectories(self, *parts: str) -> list[Path]:
        return [entry for entry in self.entries(*parts) if entry.is_dir()]

    def link_name(self, *parts: str) -> str | None:
        """Return the basename of a symlink target (used for ``driver`` links)."""
        target = self.path(*parts)
        try:
            return Path(os.readlink(target)).name
        except OSError:
            return None

    def key_values(self, *parts: str, separator: str = "=") -> dict[str, str]:
        """Parse a ``KEY=value`` file such as ``os-release`` or ``uevent``."""
        content = self.text(*parts)
        if not content:
            return {}
        values: dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or separator not in line:
                continue
            key, _, value = line.partition(separator)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def keys_with_prefix(self, *parts: str, prefix: str = "") -> list[str]:
        """Return ``KEY`` names from a ``KEY=value`` file matching ``prefix``."""
        return [key for key in self.key_values(*parts) if key.startswith(prefix)]


def split_list(value: str | None) -> list[str]:
    """Split a kernel-style comma/space separated list."""
    if not value:
        return []
    normalised = value.replace(",", " ").replace("\n", " ")
    return [item for item in normalised.split() if item]


def parse_range_current(value: str | None) -> int | None:
    """Parse ``0-15`` style CPU list ranges and return the number of CPUs."""
    if not value:
        return None
    total = 0
    for part in value.replace(",", " ").split():
        low, _, high = part.partition("-")
        if not high:
            total += 1
            continue
        try:
            total += int(high) - int(low) + 1
        except ValueError:
            return None
    return total or None


def read_flag_list(*values: str | None) -> list[str]:
    """Merge several whitespace separated flag strings into a sorted unique list."""
    flags: set[str] = set()
    for value in values:
        flags.update(split_list(value))
    return sorted(flags)
