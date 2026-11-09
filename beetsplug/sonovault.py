"""Sonovault (https://sonovault.now) as a metadata source for singletons.

DJ-oriented catalogue: BPM, key (musical/Camelot/Open Key), genre, label,
ISRC. Search is artist + title only, so only ``item_candidates`` is useful;
album matching is left to the other sources. Needs a personal API key
(free tier: 1.000 requests/month). Terms of service require every user to
use their own key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

from beets.autotag.hooks import AlbumInfo, TrackInfo
from beets.metadata_plugins import MetadataSourcePlugin

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from beets.library import Item

API = "https://api.sonovault.now/v1"


class SonovaultPlugin(MetadataSourcePlugin):
    data_source = "Sonovault"  # type: ignore[assignment]
    # perfect match scores 0.044 with this penalty: still "strong" at 0.10
    DEFAULT_DATA_SOURCE_MISMATCH_PENALTY = 0.2

    def __init__(self) -> None:
        super().__init__()
        self.config.add({"apikey": "", "search_limit": 5})
        self.config["apikey"].redact = True

    # --- http -------------------------------------------------------------

    def _get(self, path: str, **params: Any) -> dict | None:
        key = self.config["apikey"].as_str()
        if not key:
            self._log.debug("no apikey configured, skipping")
            return None
        r = requests.get(
            f"{API}{path}",
            params=params,
            headers={"x-api-key": key, "User-Agent": "beets-singles"},
            timeout=10,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    # --- mapping ----------------------------------------------------------

    def _track_info(self, t: dict) -> TrackInfo:
        artists = [a for a in t.get("artists") or [] if not a.get("is_remixer")]
        primary = [a["name"] for a in artists if a.get("is_primary")] or [
            a["name"] for a in artists
        ]
        release = (t.get("releases") or [{}])[0]
        date = (release.get("release_date") or "")[:10]
        year = int(date[:4]) if date[:4].isdigit() else None
        return TrackInfo(
            title=t.get("title"),
            track_id=str(t["id"]),
            data_source=self.data_source,
            data_url=f"https://sonovault.now/track/{t['id']}",
            artist=", ".join(primary) or None,
            artists=primary or None,
            length=t.get("duration"),
            isrc=t.get("isrc"),
            bpm=t.get("bpm"),
            initial_key=t.get("key_musical"),
            camelot_key=t.get("key_alphanumeric"),
            genre=", ".join(t.get("genre") or []) or None,
            label=(release.get("label") or {}).get("name"),
            album=release.get("title"),
            year=year,
        )

    # --- MetadataSourcePlugin API -------------------------------------------

    def item_candidates(
        self, item: Item, artist: str, title: str
    ) -> Iterable[TrackInfo]:
        if not (artist and title):
            return []
        try:
            data = self._get(
                "/tracks/search",
                artist=artist,
                title=title,
                limit=self.config["search_limit"].get(int),
            )
        except requests.RequestException as e:
            self._log.error("Error searching Sonovault: {}", e)
            return []
        return [self._track_info(t) for t in (data or {}).get("data", [])]

    def track_for_id(self, track_id: str) -> TrackInfo | None:
        try:
            data = self._get(f"/tracks/{track_id}")
        except requests.RequestException as e:
            self._log.error(
                "Error fetching Sonovault track {}: {}", track_id, e
            )
            return None
        return self._track_info(data) if data else None

    def candidates(
        self, items: Sequence[Item], artist: str, album: str, va_likely: bool
    ) -> Iterable[AlbumInfo]:
        return []  # artist+title search only; albums come from other sources

    def album_for_id(self, album_id: str) -> AlbumInfo | None:
        return None
