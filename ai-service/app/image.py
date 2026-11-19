"""Photo check and normalisation before the photo is sent to Gemini.

The format is judged by the decoded content, never by the declared content type or the
file name: only JPEG, PNG and WebP open. The photo is fully decoded (a truncated file
fails), turned upright by its EXIF orientation, flattened onto white when it has
transparency, shrunk to MAX_SIDE_PX on its longest side (never enlarged) and written
again as a baseline JPEG without EXIF, ICC or other metadata, so GPS and camera data
never leave our system. Animated WebP and APNG use their first frame.
"""

import io
import struct
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.config import JPEG_QUALITY, MAX_PIXELS, MAX_SIDE_PX

ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP")
WHITE = (255, 255, 255, 255)

# What Pillow raises for a file it cannot read: UnidentifiedImageError (an OSError) for
# an unknown or excluded format, OSError for a truncated file, SyntaxError, struct.error,
# EOFError or ValueError for a broken one.
_DECODE_ERRORS = (
    OSError,
    SyntaxError,
    ValueError,
    EOFError,
    struct.error,
    Image.DecompressionBombError,
    Image.DecompressionBombWarning,
)


class InvalidImageError(Exception):
    """Not a readable JPEG, PNG or WebP photo (400 invalid_image)."""


@dataclass(frozen=True)
class PreparedPhoto:
    jpeg: bytes
    source_format: str  # JPEG, PNG or WEBP, as decoded
    width: int
    height: int


def prepare_photo(data: bytes) -> PreparedPhoto:
    """Check the photo and return it as the JPEG sent to Gemini; InvalidImageError if not."""
    try:
        with warnings.catch_warnings():
            # Pillow only warns between MAX_IMAGE_PIXELS and twice that; treat it as an error
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=ACCEPTED_FORMATS) as image:
                source_format = image.format or ""
                if image.width * image.height > MAX_PIXELS:
                    raise InvalidImageError(
                        f"photo has {image.width}x{image.height} pixels, "
                        f"more than {MAX_PIXELS} in total"
                    )
                if source_format == "JPEG":
                    # decode at the smallest 1/2, 1/4 or 1/8 scale still >= the target,
                    # which saves memory and time on large camera photos
                    image.draft("RGB", (MAX_SIDE_PX, MAX_SIDE_PX))
                image.load()
                upright = ImageOps.exif_transpose(image)
                rgb = _flatten(upright)
    except InvalidImageError:
        raise
    except _DECODE_ERRORS as error:
        raise InvalidImageError("photo is not a readable JPEG, PNG or WebP image") from error

    rgb.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    # no exif= or icc_profile= argument: the written JPEG carries no metadata
    rgb.save(out, format="JPEG", quality=JPEG_QUALITY)
    return PreparedPhoto(out.getvalue(), source_format, rgb.width, rgb.height)


def _flatten(image: Image.Image) -> Image.Image:
    """RGB; transparent pixels become white."""
    if image.has_transparency_data:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, WHITE)
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")
