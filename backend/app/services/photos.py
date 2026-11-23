"""Meal photos (B-19; FR-N1; api-rules.md "Recognition").

The type is checked by content (JPEG, PNG or WebP), never by the file name. EXIF and
other metadata (GPS position, camera) are stripped by re-encoding the first frame,
turned upright first so that dropping the orientation tag does not rotate the photo.
The file is stored as `PHOTO_DIR/meals/<user id>/<uuid>.<ext>`; the database and the
buffer hold only that relative path.
"""

import contextlib
import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.db.photo_cleanup import MEALS_SUBDIR

MAX_PIXELS = 50_000_000  # as ai-service: larger is refused (decompression bombs)
# Pillow format -> (extension, content type, save options)
FORMATS = {
    "JPEG": ("jpg", "image/jpeg", {"quality": 95}),
    "PNG": ("png", "image/png", {"optimize": True}),
    "WEBP": ("webp", "image/webp", {"quality": 95}),
}


class InvalidPhotoError(Exception):
    """Not a readable JPEG, PNG or WebP, or too many pixels."""


@dataclass(frozen=True)
class Photo:
    data: bytes  # re-encoded, without metadata
    extension: str
    content_type: str


def prepare_photo(raw: bytes) -> Photo:
    """CPU-bound: run it in a worker thread."""
    try:
        with Image.open(io.BytesIO(raw)) as image:
            fmt = image.format
            if fmt not in FORMATS:
                raise InvalidPhotoError
            if image.width * image.height > MAX_PIXELS:
                raise InvalidPhotoError
            image.seek(0)  # the first frame of an animation
            upright = ImageOps.exif_transpose(image)
            if fmt == "JPEG" and upright.mode not in ("RGB", "L"):
                upright = upright.convert("RGB")
            extension, content_type, options = FORMATS[fmt]
            out = io.BytesIO()
            upright.save(out, format=fmt, **options)  # no exif=, so no metadata is written
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise InvalidPhotoError from None
    return Photo(out.getvalue(), extension, content_type)


def store_photo(photo_dir: Path, user_id: int, photo: Photo) -> str:
    """Writes the file (via a temporary name, so a half-written photo never has the final
    name) and returns its path relative to `photo_dir`."""
    relative = Path(MEALS_SUBDIR, str(user_id), f"{uuid.uuid4().hex}.{photo.extension}")
    target = photo_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(photo.data)
    os.replace(temporary, target)
    return relative.as_posix()


def remove_photo(photo_dir: Path, relative: str) -> None:
    """Best effort; the cleanup job removes what is left (mongo_buffer.md)."""
    with contextlib.suppress(OSError):
        (photo_dir / relative).unlink()
