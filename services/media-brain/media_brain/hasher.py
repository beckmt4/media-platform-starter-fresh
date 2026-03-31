from __future__ import annotations

import hashlib
from pathlib import Path


def compute_media_id(file_path: str) -> tuple[str, int]:
    """Return (media_id, file_size_bytes).

    media_id is a SHA-256 hex digest of "<absolute_path>:<size_in_bytes>".
    Using path + size gives a stable, collision-resistant identifier that
    does not require reading file contents, yet changes if the file is replaced.
    """
    path = Path(file_path).resolve()
    size = path.stat().st_size
    payload = f"{path}:{size}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    return digest, size


def compute_media_id_from_parts(file_path: str, file_size: int) -> str:
    """Compute media_id when the file size is already known (avoids a stat call)."""
    path = Path(file_path).resolve()
    payload = f"{path}:{file_size}".encode()
    return hashlib.sha256(payload).hexdigest()
