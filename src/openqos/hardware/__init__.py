"""Hardware discovery package for OpenQOS.

The collectors are strictly read-only and rely on kernel interfaces under
``/sys`` and ``/proc``. No external binaries are invoked, so no untrusted
device-provided string can ever reach a shell.
"""

from __future__ import annotations

from openqos.hardware.scanner import scan

__all__ = ["scan"]
