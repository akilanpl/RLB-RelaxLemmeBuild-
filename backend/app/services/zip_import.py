"""Safe ZIP archive inspection, validation, and ingestion service."""

import io
import os
import zipfile
import hashlib
from typing import List, Dict, Any, Tuple
from pathlib import Path
from backend.app.storage.base import StorageSecurityError, StorageError


class ZipValidationError(ValueError):
    """Raised when an uploaded zip file violates safety or format constraints."""
    pass


class ZipImportService:
    """
    Safely inspects and extracts ZIP archives into storage.
    Enforces path-traversal prevention, size limits, and non-execution guarantees.
    """

    MAX_ZIP_BYTES = 25 * 1024 * 1024  # 25 MB max compressed upload
    MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024  # 100 MB max uncompressed total
    MAX_FILE_COUNT = 5000  # Max total file count to prevent zip bombs

    @classmethod
    def validate_zip_stream(cls, zip_bytes: bytes) -> zipfile.ZipFile:
        """
        Validate zip integrity, size, and structure before processing.
        Returns ZipFile object if valid.
        """
        if len(zip_bytes) > cls.MAX_ZIP_BYTES:
            raise ZipValidationError(
                f"ZIP file exceeds maximum allowed upload size ({len(zip_bytes)} > {cls.MAX_ZIP_BYTES} bytes)"
            )

        if not zip_bytes.startswith(b"PK"):
            raise ZipValidationError("Uploaded file is not a valid ZIP archive format.")

        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            raise ZipValidationError(f"Corrupted or malformed ZIP file: {str(e)}")

        infolist = zf.infolist()
        if len(infolist) > cls.MAX_FILE_COUNT:
            raise ZipValidationError(
                f"ZIP contains too many entries ({len(infolist)} > {cls.MAX_FILE_COUNT} max limit)"
            )

        total_uncompressed = sum(info.file_size for info in infolist)
        if total_uncompressed > cls.MAX_UNCOMPRESSED_BYTES:
            raise ZipValidationError(
                f"Uncompressed size exceeds safety quota ({total_uncompressed} > {cls.MAX_UNCOMPRESSED_BYTES} bytes)"
            )

        return zf

    @classmethod
    def sanitize_and_inspect_members(
        cls, zf: zipfile.ZipFile
    ) -> List[Tuple[zipfile.ZipInfo, str]]:
        """
        Validates member paths against path traversal, symlink attacks, and absolute paths.
        Returns a list of (ZipInfo, normalized_relative_path).
        """
        sanitized_entries: List[Tuple[zipfile.ZipInfo, str]] = []
        seen_paths: set[str] = set()

        for member in zf.infolist():
            raw_name = member.filename

            # 1. Reject absolute paths (POSIX and Windows)
            if raw_name.startswith("/") or raw_name.startswith("\\") or (len(raw_name) > 1 and raw_name[1] == ":"):
                raise ZipValidationError(f"ZIP member contains absolute path: '{raw_name}'")

            # 2. Normalize and check for traversal
            normalized = os.path.normpath(raw_name).replace("\\", "/")
            parts = normalized.split("/")

            if ".." in parts:
                raise ZipValidationError(f"Path traversal detected in ZIP entry: '{raw_name}'")

            if normalized.startswith("/") or normalized == ".":
                continue
            if normalized in seen_paths:
                raise ZipValidationError(f"Duplicate ZIP member path: '{raw_name}'")
            seen_paths.add(normalized)

            # Filter out OS metadata junk like __MACOSX and .DS_Store
            if "__MACOSX" in parts or parts[-1] == ".DS_Store":
                continue

            # 3. Check for symlinks or device files (external attributes check)
            # High 4 bits of external_attr: 0120000 indicates symlink in POSIX
            mode = member.external_attr >> 16
            if mode & 0o120000 == 0o120000:
                raise ZipValidationError(f"Symlinks are prohibited for security: '{raw_name}'")

            sanitized_entries.append((member, normalized))

        return sanitized_entries

    @classmethod
    def extract_entries(
        cls, zf: zipfile.ZipFile, entries: List[Tuple[zipfile.ZipInfo, str]]
    ) -> List[Dict[str, Any]]:
        """
        Extracts bytes from validated zip entries in memory without writing to host disk.
        Returns list of file descriptors containing relative path, content bytes, size, and sha256.
        """
        extracted_files: List[Dict[str, Any]] = []

        for member, normalized_path in entries:
            # Skip pure directory markers
            if member.is_dir() or normalized_path.endswith("/"):
                continue

            content = zf.read(member)
            sha256 = hashlib.sha256(content).hexdigest()

            extracted_files.append({
                "relative_path": normalized_path,
                "content": content,
                "size_bytes": len(content),
                "sha256": sha256,
            })

        return extracted_files
