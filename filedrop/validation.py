"""Upload validation, kept separate so it is trivially testable."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

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


def validate_submission(
    files: Sequence[tuple[str, bytes]],
    *,
    max_bytes_per_file: int,
    allowed_extensions: Sequence[str] | str,
    title: str = "",
    max_files: int = 10,
    max_total_bytes: int | None = None,
) -> ValidationResult:
    """Check a whole submission: count, total weight, then every file on its own."""
    if not files:
        return ValidationResult(False, "Choose at least one file.")
    if len(files) > max_files:
        return ValidationResult(
            False,
            f"Up to {max_files} files under one name at a time; you picked {len(files)}.",
        )

    total = sum(len(data or b"") for _, data in files)
    if max_total_bytes is not None and total > max_total_bytes:
        return ValidationResult(
            False,
            f"Those files add up to {total / BYTES_PER_MB:.1f} MB "
            f"({total:,} bytes); the limit per submission is "
            f"{max_total_bytes / BYTES_PER_MB:.0f} MB ({max_total_bytes:,} bytes). "
            "Split it into two uploads.",
        )

    for name, data in files:
        result = validate_upload(
            name,
            len(data or b""),
            max_bytes=max_bytes_per_file,
            allowed_extensions=allowed_extensions,
            title=title,
        )
        if not result:
            return result
    return ValidationResult(True)


def extension_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lstrip(".").lower()


def allowed_list(allowed_extensions: Sequence[str] | str) -> tuple[str, ...]:
    """Normalise an allowlist.

    Accepts a comma-separated string as well as a sequence - iterating the raw
    string would yield single characters, which is how a rejection message once
    came out as "Allowed: .p, .d, .f".
    """
    if isinstance(allowed_extensions, str):
        return tuple(
            ext.strip().lower().lstrip(".")
            for ext in allowed_extensions.split(",")
            if ext.strip()
        )
    return tuple(str(ext).strip().lower().lstrip(".") for ext in allowed_extensions)


def validate_upload(
    filename: str | None,
    size_bytes: int | None,
    *,
    max_bytes: int,
    allowed_extensions: Sequence[str] | str,
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
        # Show bytes as well as MB: at the boundary both round to the same MB and
        # the message reads like a bug ("50.0 MB ... the limit is 50 MB").
        return ValidationResult(
            False,
            f"Too large: {size_bytes / BYTES_PER_MB:.1f} MB ({size_bytes:,} bytes); "
            f"the limit here is {max_bytes / BYTES_PER_MB:.0f} MB ({max_bytes:,} bytes).",
        )

    ext = extension_of(filename)
    if ext in BLOCKED_EXTENSIONS:
        return ValidationResult(False, f".{ext} files are not accepted here.")
    allowed = allowed_list(allowed_extensions)
    if allowed and ext not in allowed:
        return ValidationResult(
            False,
            f".{ext or '?'} files are not accepted here. Allowed: "
            + ", ".join(f".{e}" for e in allowed),
        )
    return ValidationResult(True)
