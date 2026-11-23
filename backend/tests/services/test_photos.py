"""Meal photos (B-19): type by content, metadata stripped, upright, stored by user."""

import io

import pytest
from PIL import Image

from app.services.photos import InvalidPhotoError, prepare_photo, remove_photo, store_photo

ORIENTATION, GPS_INFO = 0x0112, 0x8825


def _jpeg_with_exif(width=40, height=20, orientation=6) -> bytes:
    image = Image.new("RGB", (width, height), "red")
    exif = Image.Exif()
    exif[ORIENTATION] = orientation  # 6: rotate 90 degrees to view upright
    exif[0x010F] = "PhoneMaker"  # camera make
    exif.get_ifd(GPS_INFO)[2] = (51.0, 14.0, 0.0)  # a GPS latitude
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_exif_is_stripped_and_the_photo_turned_upright():
    photo = prepare_photo(_jpeg_with_exif())

    with Image.open(io.BytesIO(photo.data)) as image:
        assert (photo.extension, photo.content_type, image.format) == ("jpg", "image/jpeg", "JPEG")
        assert image.size == (20, 40)  # rotated as the orientation tag said
        assert dict(image.getexif()) == {}
        assert "exif" not in image.info


@pytest.mark.parametrize(("fmt", "extension"), [("PNG", "png"), ("WEBP", "webp")])
def test_png_and_webp_keep_their_format(fmt, extension):
    out = io.BytesIO()
    Image.new("RGBA", (8, 8)).save(out, format=fmt)

    assert prepare_photo(out.getvalue()).extension == extension


@pytest.mark.parametrize("raw", [b"not an image", b"GIF89a" + b"\x00" * 20, b""])
def test_anything_else_is_invalid(raw):
    with pytest.raises(InvalidPhotoError):
        prepare_photo(raw)


def test_a_gif_is_invalid_even_if_readable():
    out = io.BytesIO()
    Image.new("RGB", (8, 8)).save(out, format="GIF")

    with pytest.raises(InvalidPhotoError):
        prepare_photo(out.getvalue())


def test_stored_under_the_users_folder_with_a_random_name(tmp_path):
    photo = prepare_photo(_jpeg_with_exif())

    first = store_photo(tmp_path, 7, photo)
    second = store_photo(tmp_path, 7, photo)

    assert first.startswith("meals/7/") and first.endswith(".jpg") and first != second
    assert (tmp_path / first).read_bytes() == photo.data
    assert [p.name for p in (tmp_path / "meals" / "7").iterdir() if p.name.startswith(".")] == []
    remove_photo(tmp_path, first)
    remove_photo(tmp_path, first)  # missing: no error
    assert not (tmp_path / first).exists()
