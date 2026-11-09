"""Own web UI for the singles pipeline (Flask, server-rendered, vanilla JS).

Started with ``beet singles-web [host] [port]``. Replaces the upstream
``web`` plugin UI entirely; nothing from it is reused.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import flask
import markupsafe
import yaml

from beets import config

AUDIO_EXTS = {
    ".flac", ".wav", ".aiff", ".aif", ".mp3", ".m4a", ".ogg", ".opus", ".wv", ".ape",
}  # fmt: skip

# Plugin catalogue for the settings page, grouped by function.
# name -> (group, description, [(config key, label, is_secret)])
PLUGINS: dict[str, tuple[str, str, list[tuple[str, str, bool]]]] = {
    "beatport4": (
        "Metadatabronnen",
        (
            "Beatport: beste bron voor elektronische muziek; zet mixnaam in de "
            "titel (onofficiële API via een geplakte OAuth-token)"
        ),
        [],  # the token is handled separately, see BEATPORT_TOKEN_FIELD
    ),
    "discogs": (
        "Metadatabronnen",
        "Discogs: label, catalogusnummer, remixers (vinyl, white labels)",
        [("user_token", "Personal access token", True)],
    ),
    "musicbrainz": ("Metadatabronnen", "Gratis basisbron; ISRC, ID's", []),
    "deezer": ("Metadatabronnen", "Gratis, geen sleutel nodig", []),
    "spotify": (
        "Metadatabronnen",
        "ISRC en populariteit",
        [
            ("client_id", "Client ID", False),
            ("client_secret", "Client secret", True),
        ],
    ),
    "bandcamp": (
        "Metadatabronnen",
        (
            "Bandcamp (beetcamp 0.26.0) werkt momenteel niet: bandcamp.com geeft "
            "geen JSON terug"
        ),
        [],
    ),
    "chroma": (
        "Herkenning",
        "AcoustID-fingerprint: herkent audio zonder bruikbare tags",
        [("apikey", "AcoustID API key", True)],
    ),
    "fromfilename": (
        "Herkenning",
        "Artiest en titel raden uit de bestandsnaam",
        [],
    ),
    "ftintitle": (
        "Verrijking",
        "'feat. X' van artiest naar titel verplaatsen",
        [],
    ),
    "fetchart": (
        "Verrijking",
        "Hoes ophalen (iTunes, Cover Art Archive, ...)",
        [],
    ),
    "embedart": ("Verrijking", "Hoes in het audiobestand opslaan", []),
    "autobpm": ("Verrijking", "BPM meten (librosa)", []),
    "replaygain": (
        "Verrijking",
        "Luidheidscorrectie (ffmpeg, EBU R128)",
        [("targetlevel", "Doelniveau (dB)", False)],
    ),
    "convert": ("Verrijking", "Lossless naar AIFF converteren bij import", []),
    "lastgenre": ("Verrijking", "Genres via Last.fm", []),
    "lyrics": ("Verrijking", "Songteksten ophalen", []),
    "scrub": ("Verrijking", "Oude, rommelige tags wissen", []),
    "singles": (
        "Pipeline",
        "Maandmap, toonsoort, hoes voor losse nummers (altijd aan)",
        [("inbox", "Inbox-map", False), ("batch_size", "Batchgrootte", False)],
    ),
}
ALWAYS_ON = {"singles"}
EDM_SOURCES = ("beatport4", "discogs")
# Plugins that prompt interactively (and so hang a quiet batch) when this
# credential is missing: only enable them once it is set.
NEEDS_CREDENTIAL = {
    "discogs": "user_token",
    "spotify": "client_id",
    "beatport4": "tokenfile",  # must point to a valid token file, see below
}
BEATPORT_TOKEN_FIELD = "beatport4.token_json"


def beatport_token_file(cfg: dict | None = None) -> Path:
    cfg = load_yaml() if cfg is None else cfg
    stored = (cfg.get("beatport4") or {}).get("tokenfile")
    return (
        Path(stored)
        if stored
        else Path(config.config_dir()) / "beatport_token.json"
    )


def parse_beatport_token(text: str) -> dict:
    """Validate the pasted /auth/o/token/ JSON; returns the normalised dict
    beets-beatport4 reads (access_token, refresh_token, expires_at)."""
    data = json.loads(text)
    for key in ("access_token", "refresh_token"):
        if not data.get(key):
            raise ValueError(f"'{key}' ontbreekt in de JSON")
    if "expires_at" not in data:
        if "expires_in" not in data:
            raise ValueError("'expires_in' of 'expires_at' ontbreekt")
        data["expires_at"] = time.time() + int(data["expires_in"])
    return data


def beatport_token_status(cfg: dict | None = None) -> dict:
    """{'ok': bool, 'expires': 'YYYY-MM-DD HH:MM' | None, 'message': str}."""
    path = beatport_token_file(cfg)
    if not path.exists():
        return {"ok": False, "expires": None, "message": "geen token geplakt"}
    try:
        data = parse_beatport_token(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        return {
            "ok": False,
            "expires": None,
            "message": f"tokenbestand ongeldig: {e}",
        }
    expires = time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(data["expires_at"])
    )
    ok = data["expires_at"] > time.time() + 60
    return {
        "ok": ok,
        "expires": expires,
        "message": f"token geldig tot {expires}"
        if ok
        else f"token verlopen op {expires}",
    }


TERMS = {
    "batch": (
        "Groep bestanden die beets in één keer importeert. Kleiner = sneller "
        "resultaat zichtbaar, groter = minder overhead."
    ),
    "singleton": (
        "Los nummer, geen onderdeel van een album; beets zoekt per nummer een "
        "match."
    ),
    "quiet": (
        "beets stelt geen vragen. Twijfelt het, dan slaat het het bestand over "
        "en blijft het in de inbox."
    ),
    "camelot": (
        "Toonsoort als wielnotatie (1A tot 12B) voor harmonisch mixen: buren op "
        "het wiel passen bij elkaar."
    ),
    "replaygain": (
        "Meet hoe hard een nummer klinkt en slaat een correctie op zodat alles "
        "even luid klinkt."
    ),
    "acoustid": (
        "Akoestische vingerafdruk van de audio zelf; herkent een nummer ook "
        "zonder tags."
    ),
}

app = flask.Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

GLOSSARY = {
    "ISRC": "Internationale opnamecode; maakt matchen tussen diensten betrouwbaar.",
    "AcoustID": TERMS["acoustid"],
    "EBU R128": "Luidheidsnorm voor de ReplayGain-meting.",
    "librosa": "Python-bibliotheek voor audio-analyse (hier: tempo).",
    "Personal access token": "Sleutel uit je Discogs-account (Settings > Developers).",
    "mixnaam": "Original Mix, Remix, Edit, Extended enz.",
}


@app.template_filter("abbr")
def abbr_filter(text: str) -> markupsafe.Markup:
    """Wrap known jargon in <abbr title> so its explanation shows on hover."""
    out = str(markupsafe.escape(text))
    for term, title in GLOSSARY.items():
        tag = f'<abbr title="{markupsafe.escape(title)}" tabindex="0">{term}</abbr>'
        out = out.replace(term, tag)
    return markupsafe.Markup(out)


STATE: dict[str, Any] = {
    "status": "idle",  # idle | running | stopped | done
    "log": deque(maxlen=500),
    "events": deque(maxlen=200),
    "skipped": {},  # path -> reason
    "attempted": set(),
    "done": 0,
    "added": 0,
    "added_paths": set(),
    "total": 0,
    "started_at": None,
    "finished_at": None,
    "current": [],
    "proc": None,
    "stop": False,
}
_lock = threading.Lock()


# --- config file ----------------------------------------------------------


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
    for name, (_, _, fields) in PLUGINS.items():
        for key, _, _ in fields:
            value = (form.get(f"{name}.{key}") or "").strip()
            if not value:
                continue  # empty input keeps the stored value
            section = cfg.get(name) or {}
            section[key] = int(value) if value.isdigit() else value
            cfg[name] = section
    on = {n for n in PLUGINS if form.get(f"on:{n}")} | ALWAYS_ON
    for name, key in NEEDS_CREDENTIAL.items():
        value = (cfg.get(name) or {}).get(key)
        if not value or (
            name == "beatport4" and not beatport_token_status(cfg)["ok"]
        ):
            on.discard(name)  # never let a plugin prompt inside a quiet batch
    others = [n for n in enabled_plugins(cfg) if n not in PLUGINS]
    cfg["plugins"] = others + [n for n in PLUGINS if n in on]
    return cfg


# --- inbox + runner -------------------------------------------------------


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


def _event(kind: str, text: str, file: str = "") -> None:
    STATE["events"].appendleft(
        {
            "t": time.strftime("%H:%M:%S"),
            "kind": kind,
            "text": text,
            "file": file,
        }
    )


SKIP_REASONS = {
    "Skipping.": "geen match gevonden",
    "This track is already in the library!": "staat al in de bibliotheek",
}


def parse_line(line: str, batch: set[str], current: str) -> str:
    """Pure helper: update events/skipped from one beets log line.
    Returns the (possibly new) current file path."""
    stripped = line.strip()
    if stripped in batch:
        return stripped
    if stripped in SKIP_REASONS and current:
        reason = SKIP_REASONS[stripped]
        STATE["added_paths"].discard(current)  # a later skip undoes "added"
        STATE["added"] = len(STATE["added_paths"])
        if STATE["skipped"].get(current) != reason:
            STATE["skipped"][current] = reason
            _event("skipped", reason, Path(current).name)
    elif (
        stripped.startswith(("Tagging track:", "Importing as-is.")) and current
    ):
        STATE["skipped"].pop(current, None)
        STATE["added_paths"].add(current)
        STATE["added"] = len(STATE["added_paths"])
        label = stripped.removeprefix("Tagging track:").strip()
        if label.startswith("Importing as-is"):
            label = "geen sterke online match: toegevoegd met eigen tags"
        _event("added", label, Path(current).name)
    elif stripped.startswith("Error in '"):
        plugin = stripped.split("'")[1].split(".")[0]
        _event(
            "warn", f"bron {plugin}: fout, overgeslagen voor dit bestand", ""
        )
    elif stripped.startswith("Could not fetch token") or (
        stripped.startswith("beatport4:")
        and any(
            w in stripped.lower()
            for w in ("error", "fail", "token", "401", "403")
        )
    ):
        _event("warn", "Beatport: inloggen mislukt, bron levert niets", "")
    elif stripped.startswith("** error loading plugin"):
        _event("warn", stripped.removeprefix("** ").capitalize(), "")
    elif (
        "error" in stripped.lower()
        and current
        and not stripped.startswith("  ")
    ):
        _event("error", stripped[:160], Path(current).name)
    return current


def _run(batch_size: int, loop: bool, rematch: bool = False) -> None:
    try:
        while not STATE["stop"]:
            if rematch:
                batch = unmatched_paths()
                loop = False
                label = f"opnieuw matchen van {len(batch)} nummers"
            else:
                files = [
                    f for f in inbox_files() if f not in STATE["attempted"]
                ]
                batch = files[:batch_size]
                label = f"batch van {len(batch)} bestanden gestart"
            if not batch:
                break
            STATE["attempted"].update(batch)
            STATE["current"] = [f.name for f in batch]
            _event("batch", label)
            STATE["log"].append(f"--- {label} ---")
            cmd = [sys.executable, "-m", "beets"]
            if config_path().exists():
                cmd += ["-c", str(config_path())]
            # an expired Beatport token would make the plugin prompt and
            # abort the quiet import: drop it from this run's plugin list
            cfg = load_yaml()
            plugs = enabled_plugins(cfg)
            if "beatport4" in plugs and not beatport_token_status(cfg)["ok"]:
                plugs.remove("beatport4")
                _event(
                    "warn", "Beatport-token verlopen: bron uit voor deze run"
                )
            if plugs:
                cmd += ["-p", ",".join(plugs)]
            cmd += ["import", "-s", "-q"]
            # re-import from the library by query; the files stay where they are
            cmd += (
                ["-L", "match_source:none"]
                if rematch
                else list(map(str, batch))
            )
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
            STATE["proc"] = proc
            assert proc.stdout
            names = {str(f) for f in batch}
            current = ""
            for line in proc.stdout:
                STATE["log"].append(line.rstrip())
                current = parse_line(line, names, current)
            proc.wait()
            STATE["done"] += len(batch)
            if not loop:
                break
    finally:
        STATE["proc"] = None
        STATE["current"] = []
        STATE["finished_at"] = time.time()
        STATE["status"] = "stopped" if STATE["stop"] else "done"
        _event("batch", "gestopt" if STATE["stop"] else "klaar")


def start_run(
    batch_size: int, loop: bool, reset: bool, rematch: bool = False
) -> bool:
    with _lock:
        if STATE["status"] == "running":
            return False
        if reset:
            STATE["attempted"].clear()
            STATE["skipped"].clear()
        pending = (
            unmatched_paths()
            if rematch
            else [f for f in inbox_files() if f not in STATE["attempted"]]
        )
        STATE.update(
            status="running",
            stop=False,
            done=0,
            added=0,
            added_paths=set(),
            total=len(pending),
            started_at=time.time(),
            finished_at=None,
        )
        threading.Thread(
            target=_run, args=(max(1, batch_size), loop, rematch), daemon=True
        ).start()
        return True


def stop_run() -> None:
    STATE["stop"] = True
    if proc := STATE["proc"]:
        proc.terminate()


# --- library --------------------------------------------------------------


def unmatched_paths() -> list[Path]:
    lib = app.config.get("lib")
    if lib is None:
        return []
    return [Path(str(i.filepath)) for i in lib.items("match_source:none")]


def edm_sources_active(cfg: dict | None = None) -> list[str]:
    """EDM metadata sources that are enabled *and* have credentials."""
    cfg = load_yaml() if cfg is None else cfg
    on = set(enabled_plugins(cfg))
    return [
        n
        for n in EDM_SOURCES
        if n in on and (cfg.get(n) or {}).get(NEEDS_CREDENTIAL[n])
    ]


def recent_tracks(limit: int = 12) -> list[dict]:
    lib = app.config.get("lib")
    if lib is None:
        return []
    out = []
    for item in lib.items("added-"):
        key = item.get("initial_key") or ""
        out.append(
            {
                "id": item.id,
                "artist": item.artist,
                "title": item.title,
                "source": item.get("match_source")
                or item.get("data_source")
                or "",
                "key": key,
                "camelot": item.get("camelot_key") or "",
                "bpm": item.bpm or "",
                "format": item.format,
                "bitdepth": item.bitdepth or "",
                "folder": Path(str(item.filepath)).parent.name,
            }
        )
        if len(out) >= limit:
            break
    return out


def library_count() -> int:
    lib = app.config.get("lib")
    return len(lib.items()) if lib is not None else 0


def status_payload() -> dict:
    s = STATE
    return {
        "status": s["status"],
        "done": s["done"],
        "added": s["added"],
        "total": s["total"],
        "skipped": [
            {"file": Path(p).name, "path": p, "reason": r}
            for p, r in s["skipped"].items()
        ],
        "current": s["current"],
        "started_at": s["started_at"],
        "finished_at": s["finished_at"],
        "inbox_count": len(inbox_files()),
        "library_count": library_count(),
        "unmatched_count": len(unmatched_paths()),
        "edm_sources": edm_sources_active(),
        "events": list(s["events"]),
        "log": "\n".join(s["log"]),
        "recent": recent_tracks(),
    }


# --- routes ---------------------------------------------------------------


@app.route("/")
def dashboard() -> str:
    return flask.render_template(
        "dashboard.html",
        page="dashboard",
        inbox=inbox_dir(),
        files=[f.name for f in inbox_files()[:200]],
        batch_size=config["singles"]["batch_size"].get(int),
        state=status_payload(),
        terms=TERMS,
    )


@app.route("/api/status")
def api_status() -> flask.Response:
    return flask.jsonify(status_payload())


@app.route("/api/start", methods=["POST"])
def api_start() -> flask.Response:
    data = flask.request.get_json(silent=True) or flask.request.form
    started = start_run(
        int(data.get("batch_size") or 1),
        bool(data.get("loop")),
        bool(data.get("reset")),
    )
    return flask.jsonify(started=started, **status_payload())


@app.route("/api/stop", methods=["POST"])
def api_stop() -> flask.Response:
    stop_run()
    return flask.jsonify(status_payload())


@app.route("/api/test/<plugin>", methods=["POST"])
def api_test(plugin: str) -> flask.Response:
    """Connection test with the settings from the form, saved or not; falls
    back to the stored values for fields left empty (secrets)."""
    from . import connect

    settings = dict(load_yaml().get(plugin) or {})
    settings.update(flask.request.get_json(silent=True) or {})
    if plugin == "beatport4" and not settings.get("token_json"):
        path = beatport_token_file()
        if path.exists():
            settings["token_json"] = path.read_text(encoding="utf-8")
    return flask.jsonify(connect.run_test(plugin, settings))


@app.route("/api/rematch", methods=["POST"])
def api_rematch() -> flask.Response:
    """Re-import every item imported without an online match."""
    started = start_run(1, False, False, rematch=True)
    return flask.jsonify(started=started, **status_payload())


@app.route("/api/retry", methods=["POST"])
def api_retry() -> flask.Response:
    data = flask.request.get_json(silent=True) or flask.request.form
    path = data.get("path")
    targets = [path] if path else list(STATE["skipped"])
    for p in targets:
        STATE["skipped"].pop(p, None)
        STATE["attempted"].discard(Path(p))
    if STATE["status"] != "running":
        start_run(len(targets) or 1, False, False)
    return flask.jsonify(status_payload())


@app.route("/art/<int:item_id>")
def art(item_id: int) -> flask.Response:
    lib = app.config.get("lib")
    item = lib.get_item(item_id) if lib is not None else None
    if item is None:
        flask.abort(404)
    try:
        import mediafile

        data = mediafile.MediaFile(str(item.filepath)).art
    except Exception:
        data = None
    if not data:
        flask.abort(404)
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    resp = flask.Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "max-age=86400"
    return resp


@app.route("/plugins", methods=["GET", "POST"])
def plugins_page() -> str:
    cfg = load_yaml()
    saved = None
    token_error = None
    if flask.request.method == "POST":
        pasted = (flask.request.form.get(BEATPORT_TOKEN_FIELD) or "").strip()
        if pasted:
            try:
                data = parse_beatport_token(pasted)
                path = Path(config.config_dir()) / "beatport_token.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                section = cfg.get("beatport4") or {}
                section["tokenfile"] = str(path)
                cfg["beatport4"] = section
            except ValueError as e:
                token_error = str(e)
        cfg = apply_plugin_form(cfg, flask.request.form)
        save_yaml(cfg)
        saved = time.strftime("%H:%M")
    groups: dict[str, list[str]] = {}
    for name, (group, _, _) in PLUGINS.items():
        groups.setdefault(group, []).append(name)
    return flask.render_template(
        "plugins.html",
        page="plugins",
        catalogue=PLUGINS,
        groups=groups,
        enabled=set(enabled_plugins(cfg)),
        cfg=cfg,
        saved=saved,
        path=config_path(),
        always_on=ALWAYS_ON,
        needs_credential=NEEDS_CREDENTIAL,
        edm_sources=edm_sources_active(cfg),
        testable=set(connect_tests()),
        beatport_token=beatport_token_status(cfg),
        token_error=token_error,
        terms=TERMS,
    )


def connect_tests() -> dict:
    from . import connect

    return connect.TESTS


def serve(lib: Any, host: str, port: int) -> None:
    app.config["lib"] = lib
    app.run(host=host, port=port, threaded=True)
