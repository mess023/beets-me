"""Web pages for the singles pipeline, mounted on the ``web`` plugin's
Flask app under ``/singles/``.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

import flask
import yaml

from beets import config

AUDIO_EXTS = {
    ".flac", ".wav", ".aiff", ".aif", ".mp3", ".m4a", ".ogg", ".opus", ".wv", ".ape",
}  # fmt: skip

# Curated plugin catalogue for the settings page: name -> (description,
# [(config key, label, is_secret)]). Keys are relative to the plugin section.
PLUGINS: dict[str, tuple[str, list[tuple[str, str, bool]]]] = {
    "musicbrainz": ("Metadatabron: MusicBrainz (gratis, basis)", []),
    "discogs": (
        "Metadatabron: Discogs (label, catalogusnummer, remixers, vinyl)",
        [("user_token", "Personal access token", True)],
    ),
    "deezer": ("Metadatabron: Deezer (gratis, geen sleutel)", []),
    "spotify": (
        "Metadatabron: Spotify (ISRC, populariteit)",
        [
            ("client_id", "Client ID", False),
            ("client_secret", "Client secret", True),
        ],
    ),
    "bandcamp": ("Metadatabron: Bandcamp (externe plugin beetcamp)", []),
    "beatport4": (
        "Metadatabron: Beatport v4 (externe plugin, onofficieel; kan breken)",
        [
            ("username", "Gebruikersnaam", False),
            ("password", "Wachtwoord", True),
        ],
    ),
    "chroma": (
        "Akoestische fingerprint via AcoustID (herkent bestanden zonder tags)",
        [("apikey", "AcoustID API key", True)],
    ),
    "fromfilename": ("Artiest/titel raden uit de bestandsnaam", []),
    "ftintitle": ("'feat. X' van artiest naar titel verplaatsen", []),
    "fetchart": ("Albumhoezen ophalen (iTunes, Cover Art Archive, ...)", []),
    "embedart": ("Hoezen in het audiobestand embedden", []),
    "autobpm": ("BPM berekenen (librosa)", []),
    "replaygain": (
        "ReplayGain berekenen (ffmpeg, EBU R128)",
        [("targetlevel", "Doelniveau dB", False)],
    ),
    "convert": ("Lossless naar AIFF converteren bij import", []),
    "lastgenre": ("Genres via Last.fm", []),
    "lyrics": ("Songteksten ophalen", []),
    "scrub": ("Rommelige tags wissen voor het schrijven", []),
    "singles": (
        "Deze pipeline (maandmap, key, hoes voor losse nummers)",
        [("inbox", "Inbox-map", False), ("batch_size", "Batchgrootte", False)],
    ),
    "web": ("Deze webinterface", []),
}
ALWAYS_ON = {"web", "singles"}

bp = flask.Blueprint(
    "singles", __name__, url_prefix="/singles", template_folder="templates"
)

STATE: dict = {
    "status": "idle",
    "log": deque(maxlen=500),
    "done": 0,
    "total": 0,
    "attempted": set(),
    "proc": None,
    "stop": False,
    "current": [],
}
_lock = threading.Lock()


def config_path() -> Path:
    return Path(config.user_config_path())


def load_yaml() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save_yaml(data: dict) -> None:
    # ponytail: safe_dump drops YAML comments; fine for a generated config.
    config_path().write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def enabled_plugins(cfg: dict) -> list[str]:
    raw = cfg.get("plugins") or []
    return raw.split() if isinstance(raw, str) else list(raw)


def apply_plugin_form(cfg: dict, form: dict) -> dict:
    """Pure helper: toggle plugins and store settings from the form."""
    on = {n for n in PLUGINS if form.get(f"on:{n}")} | ALWAYS_ON
    others = [n for n in enabled_plugins(cfg) if n not in PLUGINS]
    cfg["plugins"] = others + [n for n in PLUGINS if n in on]
    for name, (_, fields) in PLUGINS.items():
        for key, _, _ in fields:
            value = (form.get(f"{name}.{key}") or "").strip()
            if not value:
                continue  # empty input keeps the stored value
            section = cfg.get(name) or {}
            section[key] = int(value) if value.isdigit() else value
            cfg[name] = section
    return cfg


def inbox_dir() -> Path:
    return Path(str(config["singles"]["inbox"].get()))


def inbox_files() -> list[Path]:
    root = inbox_dir()
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in AUDIO_EXTS
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def _run(batch_size: int, loop: bool) -> None:
    try:
        while not STATE["stop"]:
            files = [f for f in inbox_files() if f not in STATE["attempted"]]
            batch = files[:batch_size]
            if not batch:
                STATE["log"].append("Inbox leeg of alles al geprobeerd.")
                break
            STATE["attempted"].update(batch)
            STATE["current"] = [f.name for f in batch]
            STATE["log"].append(f"--- batch van {len(batch)} bestanden ---")
            cmd = [sys.executable, "-m", "beets"]
            if config_path().exists():
                cmd += ["-c", str(config_path())]
            cmd += ["import", "-s", "-q", *map(str, batch)]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
            STATE["proc"] = proc
            assert proc.stdout
            for line in proc.stdout:
                STATE["log"].append(line.rstrip())
            proc.wait()
            STATE["done"] += len(batch)
            if not loop:
                break
    finally:
        STATE["proc"] = None
        STATE["current"] = []
        STATE["status"] = "stopped" if STATE["stop"] else "idle"


@bp.route("/")
def dashboard() -> str:
    files = inbox_files()
    return flask.render_template(
        "singles.html",
        inbox=inbox_dir(),
        files=files[:50],
        inbox_count=len(files),
        batch_size=config["singles"]["batch_size"].get(int),
        state=STATE,
    )


@bp.route("/start", methods=["POST"])
def start() -> flask.Response:
    with _lock:
        if STATE["status"] != "running":
            form = flask.request.form
            batch_size = max(1, int(form.get("batch_size") or 1))
            loop = bool(form.get("loop"))
            if form.get("reset"):
                STATE["attempted"].clear()
                STATE["done"] = 0
            STATE.update(status="running", stop=False, total=len(inbox_files()))
            threading.Thread(
                target=_run, args=(batch_size, loop), daemon=True
            ).start()
    return flask.redirect(flask.url_for("singles.dashboard"))


@bp.route("/stop", methods=["POST"])
def stop() -> flask.Response:
    STATE["stop"] = True
    if proc := STATE["proc"]:
        proc.terminate()
    return flask.redirect(flask.url_for("singles.dashboard"))


@bp.route("/status.json")
def status() -> flask.Response:
    return flask.jsonify(
        status=STATE["status"],
        done=STATE["done"],
        total=STATE["total"],
        current=STATE["current"],
        inbox_count=len(inbox_files()),
        log="\n".join(STATE["log"]),
    )


@bp.route("/plugins", methods=["GET", "POST"])
def plugins_page() -> str:
    cfg = load_yaml()
    saved = False
    if flask.request.method == "POST":
        cfg = apply_plugin_form(cfg, flask.request.form)
        save_yaml(cfg)
        saved = True
    return flask.render_template(
        "plugins.html",
        catalogue=PLUGINS,
        enabled=set(enabled_plugins(cfg)),
        cfg=cfg,
        saved=saved,
        path=config_path(),
        always_on=ALWAYS_ON,
    )


def register() -> None:
    from beetsplug import web

    if "singles" not in web.app.blueprints:
        web.app.register_blueprint(bp)
