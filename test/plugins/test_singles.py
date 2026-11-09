from beetsplug.singles import CAMELOT, key_from_chroma, month_folder
from beetsplug.singles.ui import STATE, apply_plugin_form, parse_line


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
    assert out["plugins"] == ["inline", "discogs", "singles"]
    assert out["discogs"]["user_token"] == "old"  # empty input keeps value
    assert out["singles"]["batch_size"] == 5


def test_apply_plugin_form_refuses_plugin_without_credential():
    out = apply_plugin_form({}, {"on:discogs": "1", "on:deezer": "1"})
    assert out["plugins"] == ["deezer", "singles"]


def test_parse_line_tracks_skipped_and_added():
    STATE["skipped"].clear()
    STATE["events"].clear()
    STATE["added"] = 0
    STATE["added_paths"].clear()
    batch = {"/inbox/a.flac", "/inbox/b.flac"}
    cur = parse_line("/inbox/a.flac\n", batch, "")
    cur = parse_line("Skipping.\n", batch, cur)
    assert STATE["skipped"] == {"/inbox/a.flac": "geen match gevonden"}
    cur = parse_line("/inbox/b.flac\n", batch, cur)
    parse_line("  Tagging track: Artist - Title\n", batch, cur)
    assert STATE["added"] == 1
    assert [e["kind"] for e in STATE["events"]] == ["added", "skipped"]


def test_parse_line_skip_after_asis_undoes_added():
    STATE["skipped"].clear()
    STATE["added_paths"].clear()
    STATE["added"] = 0
    batch = {"/inbox/a.flac"}
    cur = parse_line("/inbox/a.flac\n", batch, "")
    parse_line("Importing as-is.\n", batch, cur)
    assert STATE["added"] == 1
    parse_line("This track is already in the library!\n", batch, cur)
    parse_line("Skipping.\n", batch, cur)
    assert STATE["added"] == 0
    assert STATE["skipped"]["/inbox/a.flac"] == "geen match gevonden"
