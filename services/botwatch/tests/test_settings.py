import pytest

from botwatch import core, settings


def test_the_shipped_settings_are_valid():
    assert settings.load()["check_every_seconds"] == 60


@pytest.mark.parametrize("text, message", [
    ("check_every_seconds: 60", "these should be numbers above 0: stuck_after_minutes"),
    ("[1, 2]", "name: value"),
    ("check_every_seconds: [", "Can't read"),
])
def test_mistakes(tmp_path, text, message):
    file = tmp_path / "settings.yaml"
    file.write_text(text)
    with pytest.raises(core.Invalid, match=message.replace("[", r"\[")):
        settings.load(file)


def test_too_often(tmp_path):
    file = tmp_path / "settings.yaml"
    file.write_text(settings.path().read_text().replace("check_every_seconds: 60", "check_every_seconds: 1"))
    with pytest.raises(core.Invalid, match="at least 10"):
        settings.load(file)
