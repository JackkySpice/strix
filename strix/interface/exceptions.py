"""Custom exceptions for Strix interface layers."""

from __future__ import annotations

from typing import Iterable


class StrixInterfaceError(Exception):
    """Base exception for interface-related errors."""


class EnvironmentValidationError(StrixInterfaceError):
    """Raised when required environment variables are missing."""

    def __init__(
        self,
        missing_required: Iterable[str],
        missing_optional: Iterable[str] | None = None,
    ) -> None:
        self.missing_required = list(missing_required)
        self.missing_optional = list(missing_optional or [])

        missing_str = ", ".join(self.missing_required) or "unknown"
        super().__init__(f"Missing required environment variables: {missing_str}")


class DockerUnavailableError(StrixInterfaceError):
    """Raised when the docker CLI is not available."""


class DockerImagePullError(StrixInterfaceError):
    """Raised when the Strix docker image cannot be pulled."""

    def __init__(self, image_name: str, details: str | None = None) -> None:
        self.image_name = image_name
        self.details = details
        message = f"Failed to pull docker image: {image_name}"
        if details:
            message = f"{message} ({details})"
        super().__init__(message)


class LLMWarmupError(StrixInterfaceError):
    """Raised when the configured LLM cannot be reached during warm-up."""

    def __init__(self, details: str | None = None) -> None:
        self.details = details
        message = "Failed to warm up the configured LLM"
        if details:
            message = f"{message}: {details}"
        super().__init__(message)
