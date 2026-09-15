"""
apps/radio/overlay/atomic_writer.py
Atomic PNG writer and validator.
Writes image to scratch file in target directory -> validates -> atomic rename.
Preserves last-known-good on failure.
"""
from __future__ import annotations
import os
import io
import tempfile
from typing import Optional
from PIL import Image

def validate_png_bytes(data: bytes, expected_size: tuple[int, int] = (385, 88)) -> bool:
    """
    Validate that bytes represent a valid RGBA PNG with exact expected dimensions.
    """
    if not data:
        return False
    try:
        buf = io.BytesIO(data)
        with Image.open(buf) as img:
            if img.format != "PNG":
                return False
            if img.size != expected_size:
                return False
            if img.mode != "RGBA":
                return False
        return True
    except Exception:
        return False

def atomic_write_png(
    target_path: str,
    png_bytes: bytes,
    expected_size: tuple[int, int] = (385, 88),
    sync_to_disk: bool = True,
) -> bool:
    """
    Atomically writes png_bytes to target_path:
    1. Validates png_bytes in memory.
    2. Writes to temporary file in the same directory as target_path.
    3. Flushes and syncs to disk.
    4. Re-validates written file from disk.
    5. Performs atomic os.replace(temp_path, target_path).
    6. Retains last-known-good on failure.
    """
    if not validate_png_bytes(png_bytes, expected_size):
        return False

    target_dir = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(target_dir, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(prefix="tmp_ovr_", suffix=".png", dir=target_dir)
    try:
        with os.fdopen(temp_fd, "wb") as f:
            f.write(png_bytes)
            f.flush()
            if sync_to_disk:
                os.fsync(f.fileno())

        # Verify disk file
        with open(temp_path, "rb") as f:
            disk_bytes = f.read()
        if not validate_png_bytes(disk_bytes, expected_size):
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False

        # Atomic replacement
        os.replace(temp_path, target_path)
        return True
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return False
