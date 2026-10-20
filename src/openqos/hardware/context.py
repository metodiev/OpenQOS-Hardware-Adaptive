"""Shared state for a hardware scan."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openqos.hardware.readers import FsRoot


@dataclass
class CollectionContext:
    """Carries the filesystem root, privacy policy, and diagnostics."""

    fs: FsRoot
    privacy: bool = False
    warnings: list[dict[str, str]] = field(default_factory=list)
    unavailable: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def create(cls, root: Path | None = None, *, privacy: bool = False) -> CollectionContext:
        return cls(fs=FsRoot(root if root is not None else Path("/")), privacy=privacy)

    def warn(self, code: str, message: str, source: str) -> None:
        self.warnings.append({"code": code, "message": message, "source": source})

    def unavailable_reason(self, collector: str, reason: str) -> None:
        self.unavailable.append({"collector": collector, "reason": reason})

    def redact(self, value: str | None) -> str | None:
        """Drop identifiers that are not needed for compatibility decisions."""
        if value is None:
            return None
        return None if self.privacy else value
