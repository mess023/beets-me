"""Connection tests for the services page: one minimal real call per plugin,
using the settings typed in the form (saved or not). Each test returns a short
success summary or raises with the real error."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from collections.abc import Callable

TIMEOUT = 15
UA = {"User-Agent": "beets-singles/1.0 (https://github.com/mess023/beets-me)"}
QUERY = "Daft Punk One More Time"

HINTS = {
    "beatport4": (
        "Plak een verse token: log in op beatport.com, open de Network-tab van "
        "de developer tools, zoek de aanvraag naar api.beatport.com/v4/auth/o/"
        "token/ en kopieer de JSON-respons."
    ),
    "discogs": (
        "Maak een Personal access token aan op discogs.com → Settings → Developers."
    ),
    "spotify": "Client ID en secret komen uit het Spotify Developer Dashboard.",
    "chroma": "Vraag een gratis sleutel aan op acoustid.org/new-application.",
    "bandcamp": "beetcamp krijgt geen JSON van bandcamp.com; laat de plugin uit.",
    "sonovault": "Maak een gratis key aan op sonovault.now (e-mail verifiëren).",
}


def _json(url: str, headers: dict | None = None, **kw) -> dict:
    r = requests.get(
        url, timeout=TIMEOUT, headers={**UA, **(headers or {})}, **kw
    )
    r.raise_for_status()
    return r.json()


def test_musicbrainz(s: dict) -> str:
    d = _json(
        "https://musicbrainz.org/ws/2/recording",
        params={"query": QUERY, "fmt": "json", "limit": 1},
    )
    return f"verbonden · {d.get('count', 0)} opnames voor '{QUERY}'"


def test_deezer(s: dict) -> str:
    d = _json(
        "https://api.deezer.com/search/track", params={"q": QUERY, "limit": 1}
    )
    return f"verbonden · {d.get('total', 0)} tracks voor '{QUERY}'"


def test_discogs(s: dict) -> str:
    token = s.get("user_token")
    if not token:
        raise ValueError("geen token ingevuld")
    d = _json(
        "https://api.discogs.com/oauth/identity",
        headers={**UA, "Authorization": f"Discogs token={token}"},
    )
    return f"verbonden als {d.get('username')}"


def test_spotify(s: dict) -> str:
    if not (s.get("client_id") and s.get("client_secret")):
        raise ValueError("client id of secret ontbreekt")
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(s["client_id"], s["client_secret"]),
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return f"verbonden · token geldig {r.json().get('expires_in')} s"


def test_beatport4(s: dict) -> str:
    import time

    from beetsplug.beatport4.client import Beatport4Client
    from beetsplug.beatport4.models import BeatportOAuthToken

    from .ui import parse_beatport_token

    if not s.get("token_json"):
        raise ValueError("geen token geplakt (JSON, Bearer-header of cURL)")
    parsed = parse_beatport_token(s["token_json"])
    detected = parsed.pop("detected")
    token = BeatportOAuthToken.from_api_response(parsed)
    left = int(token.expires_at - time.time())
    if left <= 0:
        raise ValueError(
            "token is verlopen; plak een nieuwe "
            "(beets-beatport4 ververst hem niet zelf)"
        )
    # Check the token ourselves first: the plugin's client would otherwise
    # fall back to the (dead) username/password login and report HTTP 400.
    account = _json(
        "https://api.beatport.com/v4/my/account/",
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    client = Beatport4Client(
        log=logging.getLogger("beets.singles.connect"), beatport_token=token
    )
    query = "Agents of Time Stay With Me"
    hits = list(client.search(query, model="tracks"))
    first = f" · bv. {hits[0].name} ({hits[0].mix_name})" if hits else ""
    return (
        f"ingelogd als {account.get('username', '?')} · {len(hits)} tracks "
        f"voor '{query}'{first} · {detected} · token nog {left // 3600} u "
        f"{left % 3600 // 60} min geldig"
    )


def test_bandcamp(s: dict) -> str:
    from beetsplug.bandcamp import BandcampPlugin

    from beets.library import Item

    item = Item(artist="Daft Punk", title="One More Time", length=320)
    hits = list(BandcampPlugin().item_candidates(item, item.artist, item.title))
    return f"verbonden · {len(hits)} kandidaten"


def test_chroma(s: dict) -> str:
    key = (
        s.get("apikey") or "1vOwZtEn"
    )  # beets' built-in AcoustID key (chroma.py)
    d = _json(
        "https://api.acoustid.org/v2/lookup",
        params={
            "client": key,
            "duration": 1,
            "fingerprint": "AQAAAA",
            "meta": "recordings",
        },
    )
    if d.get("status") != "ok":
        raise RuntimeError(d.get("error", {}).get("message", d))
    return "verbonden · API-key geaccepteerd"


def test_fetchart(s: dict) -> str:
    d = _json(
        "https://itunes.apple.com/search",
        params={"term": QUERY, "entity": "album", "limit": 1},
    )
    requests.head("https://coverartarchive.org/", timeout=TIMEOUT, headers=UA)
    return (
        f"verbonden · iTunes {d.get('resultCount', 0)} hoes, "
        "Cover Art Archive bereikbaar"
    )


def test_lyrics(s: dict) -> str:
    d = _json("https://lrclib.net/api/search", params={"q": QUERY})
    return f"verbonden · LRCLIB {len(d)} resultaten"


def test_lastgenre(s: dict) -> str:
    from beets.plugins import LASTFM_KEY

    d = _json(
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method": "tag.getinfo",
            "tag": "techno",
            "api_key": LASTFM_KEY,
            "format": "json",
        },
    )
    if "error" in d:
        raise RuntimeError(d.get("message"))
    return f"verbonden · tag 'techno' heeft {d['tag'].get('total', '?')} tags"


def test_sonovault(s: dict) -> str:
    if not s.get("apikey"):
        raise ValueError("geen API key ingevuld")
    d = _json(
        "https://api.sonovault.now/v1/tracks/search",
        params={"artist": "Daft Punk", "title": "One More Time", "limit": 1},
        headers={**UA, "x-api-key": s["apikey"]},
    )
    hits = d.get("data") or []
    first = hits[0] if hits else {}
    extra = (
        f" · bv. {first.get('title')} {first.get('bpm')} BPM "
        f"{first.get('key_alphanumeric') or ''}"
        if first
        else ""
    )
    return f"verbonden · {len(hits)} treffer(s) voor Daft Punk - One More Time{extra}"


TESTS: dict[str, Callable[[dict], str]] = {
    "sonovault": test_sonovault,
    "musicbrainz": test_musicbrainz,
    "deezer": test_deezer,
    "discogs": test_discogs,
    "spotify": test_spotify,
    "beatport4": test_beatport4,
    "bandcamp": test_bandcamp,
    "chroma": test_chroma,
    "fetchart": test_fetchart,
    "lyrics": test_lyrics,
    "lastgenre": test_lastgenre,
}


def run_test(plugin: str, settings: dict) -> dict:
    """Run one test with a hard timeout; never raises."""
    fn = TESTS.get(plugin)
    if fn is None:
        return {"ok": False, "message": "geen test voor deze plugin"}
    # ponytail: one worker per call; the thread keeps running after a timeout
    # but the page never blocks.
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            return {
                "ok": True,
                "message": pool.submit(fn, settings).result(TIMEOUT),
            }
        except FutureTimeout:
            msg = f"geen antwoord binnen {TIMEOUT} s"
        except requests.HTTPError as e:
            body = (e.response.text or "")[:120].replace("\n", " ")
            msg = f"HTTP {e.response.status_code} {e.response.reason} · {body}"
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:300]}"
    return {"ok": False, "message": msg, "hint": HINTS.get(plugin, "")}
