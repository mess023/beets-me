import pytest

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


def test_parse_line_plugin_error_is_a_warning_not_a_skip():
    STATE["events"].clear()
    batch = {"/inbox/a.flac"}
    cur = parse_line("/inbox/a.flac\n", batch, "")
    parse_line(
        "Error in 'Bandcamp.item_candidates': Expecting value: line 1\n",
        batch,
        cur,
    )
    assert STATE["events"][0]["kind"] == "warn"
    assert "Bandcamp" in STATE["events"][0]["text"]


def _jwt(exp: int) -> str:
    import base64
    import json

    def seg(d: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(d).encode()).decode()
        return raw.rstrip("=")

    return f"{seg({'alg': 'HS256'})}.{seg({'exp': exp, 'sub': '1'})}.sig"


def test_beatport_token_parser_accepts_json_bearer_curl_and_jwt():
    import json
    import time

    from beetsplug.singles.ui import parse_beatport_token

    good = parse_beatport_token(
        json.dumps(
            {"access_token": "a", "refresh_token": "r", "expires_in": 60}
        )
    )
    assert good["detected"] == "token-JSON"
    assert good["expires_at"] > time.time()

    bearer = parse_beatport_token("Bearer abcdefghijklmnopqrstuvwxyz0123")
    assert bearer["access_token"] == "abcdefghijklmnopqrstuvwxyz0123"
    assert bearer["refresh_token"] == ""
    assert bearer["detected"] == "Bearer-header"
    assert bearer["expires_at"] - time.time() > 35000

    curl = parse_beatport_token(
        "curl 'https://api.beatport.com/v4/my/account/' "
        "-H 'Accept: application/json' -H 'Authorization: Bearer tok_ABCDEFGHIJKLMNOP' "
        "--compressed"
    )
    assert curl["access_token"] == "tok_ABCDEFGHIJKLMNOP"
    assert curl["detected"] == "cURL-commando"

    exp = int(time.time()) + 1234
    jwt = parse_beatport_token(_jwt(exp))
    assert jwt["expires_at"] == exp
    assert "JWT" in jwt["detected"]
    assert jwt["detected"].startswith("los access token")

    with pytest.raises(ValueError, match="niet herkend"):
        parse_beatport_token("dit is geen token")


def test_apply_plugin_form_keeps_beatport_off_without_token_file():
    out = apply_plugin_form(
        {"beatport4": {"tokenfile": "/nonexistent/beatport_token.json"}},
        {"on:beatport4": "1", "on:musicbrainz": "1"},
    )
    assert out["plugins"] == ["musicbrainz", "singles"]


def test_parse_line_sources_event():
    STATE["events"].clear()
    line = (
        "singles: sources|/inbox/a.flac|medium|"
        "MusicBrainz: 10 kandidaten, beste 0.163 · Deezer: 0 kandidaten\n"
    )
    parse_line(line, {"/inbox/a.flac"}, "/inbox/a.flac")
    ev = STATE["events"][0]
    assert ev["kind"] == "sources"
    assert ev["file"] == "a.flac"
    assert "matig" in ev["text"]
    assert "Deezer: 0" in ev["text"]


def test_guess_artist_from_filename():
    from beetsplug.singles import guess_from_filename

    assert guess_from_filename(
        "01 - Agents of Time & Darla Jade - Stay With Me (Original Mix)"
    ) == ("Agents of Time & Darla Jade", "Stay With Me (Original Mix)")
    assert guess_from_filename("00 - Next to Me") == ("", "Next to Me")
    assert guess_from_filename("Artist - Title") == ("Artist", "Title")
