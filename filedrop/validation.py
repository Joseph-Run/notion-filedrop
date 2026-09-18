"""Upload validation, kept separate so it is trivially testable."""

from __future__ import annotations

import os
from dataclasses import dataclass

BYTES_PER_MB = 1024 * 1024

# Suffixes we refuse even if someone adds them to ALLOWED_EXTENSIONS.
BLOCKED_EXTENSIONS = {
    "exe", "msi", "bat", "cmd", "com", "scr", "ps1", "vbs", "js", "jar",
    "dll", "app", "sh", "php", "py", "rb", "htm", "html", "svgz",
}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    error: str = ""

    def __bool__(self) -> bool:  # lets callers write `if validate(...):`
        return self.ok


def extension_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lstrip(".").lower()


def validate_upload(
    filename: str | None,
    size_bytes: int | None,
    *,
    max_bytes: int,
    allowed_extensions: tuple[str, ...],
    title: str = "",
) -> ValidationResult:
    """Reject junk before a byte reaches Notion."""
    if not filename:
        return ValidationResult(False, "Choose a file to upload.")
    if not (title or "").strip():
        return ValidationResult(False, "Give the upload a name so people know what it is.")
    if len(title.strip()) > 120:
        return ValidationResult(False, "Keep the name under 120 characters.")
    if not size_bytes:
        return ValidationResult(False, "That file looks empty.")
    if size_bytes > max_bytes:
        return ValidationResult(
            False,
            f"Too large: {size_bytes / BYTES_PER_MB:.1f} MB. "
            f"The limit here is {max_bytes / BYTES_PER_MB:.0f} MB.",
        )

    ext = extension_of(filename)
    if ext in BLOCKED_EXTENSIONS:
        return ValidationResult(False, f".{ext} files are not accepted here.")
    if allowed_extensions and ext not in allowed_extensions:
        return ValidationResult(
            False,
            f".{ext or '?'} files are not accepted here. Allowed: "
            + ", ".join(f".{e}" for e in allowed_extensions),
        )
    return ValidationResult(True)
