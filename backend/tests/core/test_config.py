"""Settings parsing that the code relies on."""

from pathlib import Path

import pytest

from tests.conftest import make_settings


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_photo_dir_is_unset_not_the_current_directory(value):
    settings = make_settings(photo_dir=value)

    assert settings.photo_dir is None
    with pytest.raises(RuntimeError, match="PHOTO_DIR"):
        settings.photo_root()


def test_photo_dir_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))

    assert make_settings().photo_root() == Path(tmp_path)


def test_empty_photo_dir_from_the_environment_is_unset(monkeypatch):
    monkeypatch.setenv("PHOTO_DIR", "")

    assert make_settings().photo_dir is None
