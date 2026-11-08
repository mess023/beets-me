from beetsplug.singles import CAMELOT, key_from_chroma, month_folder
from beetsplug.singles.ui import apply_plugin_form


def test_month_folder_english_month_and_year():
    assert month_folder(1753401600) == "July 2025"  # 2025-07-25


def test_key_from_chroma_major_and_minor():
    c_major = [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1]
    assert key_from_chroma(c_major) == "C"
    # A minor scale with the tonic and fifth emphasised
    a_minor = [1, 0, 1, 0, 1, 1, 0, 1, 0, 3, 0, 1]
    assert key_from_chroma(a_minor) == "Am"


def test_camelot_wheel_covers_all_keys():
    assert len(CAMELOT) == 24
    assert CAMELOT["Am"] == "8A"
    assert CAMELOT["C"] == "8B"


def test_apply_plugin_form_toggles_and_keeps_values():
    cfg = {
        "plugins": "musicbrainz fetchart inline",
        "discogs": {"user_token": "old"},
    }
    form = {
        "on:discogs": "1",
        "discogs.user_token": "",
        "singles.batch_size": "5",
    }
    out = apply_plugin_form(cfg, form)
    assert out["plugins"] == ["inline", "discogs", "singles", "web"]
    assert out["discogs"]["user_token"] == "old"  # empty input keeps value
    assert out["singles"]["batch_size"] == 5


def test_apply_plugin_form_refuses_plugin_without_credential():
    out = apply_plugin_form({}, {"on:discogs": "1", "on:deezer": "1"})
    assert out["plugins"] == ["deezer", "singles", "web"]
