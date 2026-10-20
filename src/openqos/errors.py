"""Project-wide exception types."""

from __future__ import annotations


class OpenQOSError(Exception):
    """Base class for expected, user-facing OpenQOS failures."""


class UnsupportedPlatformError(OpenQOSError):
    """Raised when an operation requires a platform that is not available."""


class CollectionError(OpenQOSError):
    """Raised when a hardware scan cannot start."""


class SchemaError(OpenQOSError):
    """Raised when a document does not conform to its schema."""


class SchemaValidationUnavailableError(SchemaError):
    """Raised when schema validation is requested without jsonschema installed."""


class ImageBuildError(OpenQOSError):
    """Raised when an image build cannot be prepared or completed."""


class ProfileError(OpenQOSError):
    """Raised when a hardware profile cannot be built or matched."""


class OptimizationError(OpenQOSError):
    """Raised when an optimization plan cannot be produced."""


class InstallError(OpenQOSError):
    """Raised when an installation cannot be planned or started."""
