"""Pipeline for loose (non-album) tracks: creation-date folders, key
detection, cover art for singletons and a small web UI to run batches.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar

from beets import plugins
from beets.dbcore import types
from beets.plugins import BeetsPlugin
from beetsplug._utils import art

if TYPE_CHECKING:
    from beets.importer import ImportSession, ImportTask
    from beets.library import Item, Library

MONTHS = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)  # fmt: skip

KEYS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# Krumhansl-Schmuckler key profiles (major / minor), index 0 = tonic.
_MAJOR = (
    6.35,
    2.23,
    3.48,
    2.33,
    4.38,
    4.09,
    2.52,
    5.19,
    2.39,
    3.66,
    2.29,
    2.88,
)
_MINOR = (
    6.33,
    2.68,
    3.52,
    5.38,
    2.60,
    3.53,
    2.54,
    4.75,
    3.98,
    2.69,
    3.34,
    3.17,
)
# Camelot wheel: standard notation -> DJ notation (Rekordbox/Traktor style).
CAMELOT = {
    "B": "1B", "F#": "2B", "C#": "3B", "G#": "4B", "D#": "5B", "A#": "6B",
    "F": "7B", "C": "8B", "G": "9B", "D": "10B", "A": "11B", "E": "12B",
    "G#m": "1A", "D#m": "2A", "A#m": "3A", "Fm": "4A", "Cm": "5A", "Gm": "6A",
    "Dm": "7A", "Am": "8A", "Em": "9A", "Bm": "10A", "F#m": "11A", "C#m": "12A",
}  # fmt: skip


def file_created(path: str | bytes) -> float:
    """Birth time of a file; falls back to mtime where the filesystem or
    kernel does not expose it (common on network shares)."""
    st = os.stat(path)
    return getattr(st, "st_birthtime", None) or st.st_mtime


def month_folder(timestamp: float) -> str:
    d = datetime.fromtimestamp(timestamp)
    return f"{MONTHS[d.month - 1]} {d.year}"


def key_from_chroma(chroma: list[float] | tuple[float, ...]) -> str:
    """Krumhansl-Schmuckler: best-correlated rotation of the major/minor
    profiles against a 12-bin pitch-class vector. Returns e.g. 'Am'."""
    import numpy as np

    c = np.asarray(chroma, dtype=float)
    best, best_key = -2.0, "C"
    for i in range(12):
        rolled = np.roll(c, -i)
        for profile, suffix in ((_MAJOR, ""), (_MINOR, "m")):
            r = np.corrcoef(rolled, profile)[0, 1]
            if r > best:
                best, best_key = r, KEYS[i] + suffix
    return best_key


def detect_key(path: str) -> str | None:
    """Essentia (edma profile) when installed, else librosa chroma + KS."""
    try:
        import essentia.standard as es  # type: ignore[import-not-found]

        audio = es.MonoLoader(filename=path, sampleRate=44100)()
        key, scale, _ = es.KeyExtractor(profileType="edma")(audio)
        return key + ("m" if scale == "minor" else "")
    except ImportError:
        pass
    try:
        import librosa
    except ImportError:
        return None
    y, sr = librosa.load(path, res_type="kaiser_fast")
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    return key_from_chroma(chroma)


class SinglesPlugin(BeetsPlugin):
    item_types: ClassVar[dict[str, types.Type]] = {"creation_date": types.DATE}

    def __init__(self) -> None:
        super().__init__()
        self.config.add(
            {
                "inbox": "/music/inbox",
                "batch_size": 20,
                "auto_key": True,
                "auto_art": True,
            }
        )
        self.template_fields["month_folder"] = self._month_folder
        self.register_listener("import_task_start", self._remember_created)
        if self.config["auto_key"].get(bool):
            self.import_stages = [self._key_stage]
        if self.config["auto_art"].get(bool):
            self.register_listener("item_imported", self._singleton_art)
        self.register_listener("item_imported", self._mark_source)

    def _mark_source(self, lib: Library, item: Item) -> None:
        """Record where the metadata came from; 'none' = imported as-is, so
        the web UI can show it and offer a re-match later."""
        item.match_source = item.get("data_source") or "none"
        item.store()

    def commands(self) -> list:
        from beets import ui as beets_ui

        cmd = beets_ui.Subcommand(
            "singles-web", help="start the singles web interface"
        )

        def func(lib: Library, opts: object, args: list[str]) -> None:
            from . import ui

            host = args[0] if args else "0.0.0.0"
            port = int(args[1]) if len(args) > 1 else 8338
            ui.serve(lib, host, port)

        cmd.func = func
        return [cmd]

    # --- creation date -> "July 2025" -------------------------------------

    def _remember_created(
        self, session: ImportSession, task: ImportTask
    ) -> None:
        # Runs before convert replaces the file, so the original's date wins.
        for item in task.items:
            if not item.get("creation_date"):
                item.creation_date = file_created(item.path)

    def _month_folder(self, item: Item) -> str:
        return month_folder(item.get("creation_date") or item.added)

    # --- key ----------------------------------------------------------------

    def _key_stage(self, session: ImportSession, task: ImportTask) -> None:
        for item in task.imported_items():
            if item.initial_key:
                continue
            try:
                key = detect_key(str(item.filepath))
            except Exception as exc:
                self._log.error("key detection failed for {}: {}", item, exc)
                continue
            if key:
                item.initial_key = key
                item.camelot_key = CAMELOT.get(key, "")
                item.store()
                self._log.info(
                    "Key for {}: {} ({})", item, key, item.camelot_key
                )

    # --- cover art for singletons -------------------------------------------

    def _singleton_art(self, lib: Library, item: Item) -> None:
        fetchart = next(
            (p for p in plugins.find_plugins() if p.name == "fetchart"), None
        )
        if fetchart is None:
            return
        # fetchart works on albums; a stand-in with the fields its sources
        # read lets it search for the release this track appears on.
        stand_in = SimpleNamespace(
            albumartist=item.albumartist or item.artist,
            album=item.album or item.title,
            mb_albumid=item.mb_albumid,
            mb_releasegroupid=item.mb_releasegroupid,
            artpath=None,
            get=lambda k, d=None: item.get(k, d),
            items=lambda: SimpleNamespace(get=lambda: item),
        )
        candidate = fetchart.art_for_album(stand_in, None)
        if candidate is None or candidate.path is None:
            self._log.info("no cover art found for {}", item)
            return
        art.embed_item(
            self._log, item, candidate.path, maxwidth=fetchart.maxwidth
        )
        with contextlib.suppress(OSError):
            os.remove(candidate.path)
