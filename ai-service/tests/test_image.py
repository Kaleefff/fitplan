"""A-01: photo check and normalisation (app/image.py)."""

import io
import random

import pytest
from PIL import Image

from app.config import MAX_PIXELS, MAX_SIDE_PX
from app.image import InvalidImageError, prepare_photo
from tests.conftest import make_photo, open_photo

EXIF_ORIENTATION = 0x0112
EXIF_MAKE = 0x010F
ROTATE_90_CW = 6  # stored landscape, shown portrait


def noise_jpeg(size: tuple[int, int]) -> bytes:
    """A JPEG whose scan data fills most of the file, so a cut lands inside it."""
    rng = random.Random(1)
    image = Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_each_accepted_format_becomes_a_jpeg(fmt):
    photo = prepare_photo(make_photo(fmt))

    assert photo.source_format == fmt
    result = open_photo(photo.jpeg)
    assert result.format == "JPEG"
    assert result.mode == "RGB"
    assert result.size == (300, 200)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((4000, 3000), (1024, 768)),
        ((3000, 4000), (768, 1024)),
        ((2048, 1024), (1024, 512)),
    ],
)
def test_large_photo_is_shrunk_to_the_longest_side(size, expected):
    photo = prepare_photo(make_photo("JPEG", size))

    assert open_photo(photo.jpeg).size == expected
    assert (photo.width, photo.height) == expected


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_small_photo_is_never_upscaled(fmt):
    photo = prepare_photo(make_photo(fmt, (64, 40)))

    assert open_photo(photo.jpeg).size == (64, 40)


def test_exactly_the_limit_keeps_its_size():
    photo = prepare_photo(make_photo("PNG", (MAX_SIDE_PX, 500)))

    assert open_photo(photo.jpeg).size == (MAX_SIDE_PX, 500)


def test_exif_is_applied_and_removed():
    exif = Image.Exif()
    exif[EXIF_ORIENTATION] = ROTATE_90_CW
    exif[EXIF_MAKE] = "SecretCam"
    source = make_photo("JPEG", (300, 200), exif=exif.tobytes())
    assert open_photo(source).getexif()[EXIF_MAKE] == "SecretCam"

    photo = prepare_photo(source)

    result = open_photo(photo.jpeg)
    assert result.size == (200, 300)  # turned upright
    assert len(result.getexif()) == 0
    assert b"Exif" not in photo.jpeg
    assert b"SecretCam" not in photo.jpeg


def test_icc_profile_is_not_kept():
    source = make_photo("JPEG", icc_profile=b"\x00" * 128)
    assert "icc_profile" in open_photo(source).info

    assert "icc_profile" not in open_photo(prepare_photo(source).jpeg).info


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_transparency_is_flattened_onto_white(fmt):
    source = make_photo(fmt, (40, 40), "RGBA", (255, 0, 0, 0))  # fully transparent red

    result = open_photo(prepare_photo(source).jpeg)

    assert result.mode == "RGB"
    assert all(channel >= 250 for channel in result.getpixel((20, 20)))


def test_half_transparent_pixels_are_blended_with_white():
    source = make_photo("PNG", (40, 40), "RGBA", (0, 0, 0, 128))

    red, green, blue = open_photo(prepare_photo(source).jpeg).getpixel((20, 20))

    assert all(120 <= channel <= 135 for channel in (red, green, blue))


def test_palette_png_with_a_transparent_index_is_flattened():
    image = Image.new("P", (40, 40), 0)
    image.putpalette([0, 0, 0] * 256)
    out = io.BytesIO()
    image.save(out, format="PNG", transparency=0)

    result = open_photo(prepare_photo(out.getvalue()).jpeg)

    assert all(channel >= 250 for channel in result.getpixel((20, 20)))


@pytest.mark.parametrize("mode", ["L", "CMYK"])
def test_other_colour_modes_become_rgb(mode):
    color = 128 if mode == "L" else (0, 0, 0, 0)

    result = open_photo(prepare_photo(make_photo("JPEG", mode=mode, color=color)).jpeg)

    assert result.mode == "RGB"


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\xff\xd8\xff" + b"\x00" * 50])
def test_unreadable_data_is_rejected(data):
    with pytest.raises(InvalidImageError):
        prepare_photo(data)


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_other_formats_are_rejected(fmt):
    with pytest.raises(InvalidImageError):
        prepare_photo(make_photo(fmt, mode="RGB"))


def test_truncated_jpeg_is_rejected():
    data = noise_jpeg((400, 300))
    assert open_photo(data).size == (400, 300)

    with pytest.raises(InvalidImageError):
        prepare_photo(data[: len(data) * 2 // 3])


def test_truncated_png_is_rejected():
    data = make_photo("PNG", (400, 300))

    with pytest.raises(InvalidImageError):
        prepare_photo(data[: len(data) // 2])


def test_decompression_bomb_is_rejected_before_decoding():
    side = int(MAX_PIXELS**0.5) + 100  # just over the limit, a tiny file
    data = make_photo("PNG", (side, side), mode="1", color=0)
    assert len(data) < 200_000

    with pytest.raises(InvalidImageError, match="pixels"):
        prepare_photo(data)
