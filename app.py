from __future__ import annotations

import os
import secrets
import socket
import threading
import time
import uuid
from functools import wraps
from io import BytesIO

import qrcode
import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from qrcode.image.svg import SvgPathImage

import spotify_client
from content_filter import is_blocked_text, reject_reason
from spotify_client import SpotifyConfigError

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
_ADMIN_PASSWORD_GENERATED = False
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(9)
    _ADMIN_PASSWORD_GENERATED = True

_lock = threading.Lock()
_pending: list[dict] = []
_queue: list[dict] = []
_now_playing: dict | None = None


def _lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _public_base() -> str:
    host = os.environ.get("PUBLIC_HOST") or _lan_ip()
    port = int(os.environ.get("PORT", "5000"))
    if port == 80:
        return f"http://{host}"
    return f"http://{host}:{port}"


def _track_from_spotify(item: dict) -> dict:
    artists = ", ".join(a.get("name") or "" for a in item.get("artists") or [])
    album = item.get("album") or {}
    images = album.get("images") or []
    artwork = images[0]["url"] if images else ""
    return {
        "spotify_id": item.get("id") or "",
        "spotify_uri": item.get("uri") or "",
        "spotify_url": (item.get("external_urls") or {}).get("spotify", ""),
        "title": item.get("name") or "",
        "artist": artists,
        "album": album.get("name") or "",
        "artwork": artwork,
        "duration_ms": item.get("duration_ms") or 0,
        "explicit": bool(item.get("explicit")),
    }


def _find_duplicates(spotify_id: str) -> list[str]:
    places: list[str] = []
    if _now_playing and _now_playing.get("spotify_id") == spotify_id:
        places.append("now")
    if any(s.get("spotify_id") == spotify_id for s in _queue):
        places.append("queue")
    if any(s.get("spotify_id") == spotify_id for s in _pending):
        places.append("pending")
    return places


def _public_song(item: dict | None, *, include_uri: bool = False) -> dict | None:
    if not item:
        return None
    # Songs aus unserer lokalen Request-Liste besitzen eine UUID unter `id`.
    # Songs, die direkt aus Spotify kommen (z.B. /me/player/queue), besitzen
    # dagegen nur `spotify_id`. Beides muss für die öffentliche API erlaubt sein.
    data = {
        "id": item.get("id") or item.get("spotify_id") or "",
        "title": item.get("title") or "",
        "artist": item.get("artist") or "",
        "album": item.get("album") or "",
        "artwork": item.get("artwork") or "",
        "duration_ms": item.get("duration_ms") or 0,
        "spotify_url": item.get("spotify_url") or "",
        "duplicate_in": item.get("duplicate_in"),
        "source": item.get("source", "spotify"),
    }
    if include_uri:
        data["spotify_id"] = item.get("spotify_id")
        data["spotify_uri"] = item.get("spotify_uri")
    return data


def _now_playing_set(song: dict | None) -> None:
    global _now_playing
    _now_playing = song


def _require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Nicht angemeldet"}), 401
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def _duplicate_message(places: list[str]) -> str:
    labels = {
        "now": "läuft gerade",
        "queue": "steht schon in der Warteschlange",
        "pending": "wurde schon angefragt und wartet auf Freigabe",
    }
    bits = [labels[p] for p in places if p in labels]
    extra = " und ".join(bits)
    return (
        f"Achtung: Dieser Song {extra}. "
        "Deine Anfrage wurde trotzdem aufgenommen – der Admin entscheidet."
    )


# ---------------------------------------------------------------------------
# Öffentliche Seiten
# ---------------------------------------------------------------------------

@app.route("/")
def user_page():
    return render_template("user.html")


@app.route("/qr")
def qr_page():
    return render_template("qr.html", user_url=_public_base() + "/")


@app.route("/qr.svg")
def qr_svg():
    url = _public_base() + "/"
    img = qrcode.make(url, image_factory=SvgPathImage, box_size=12, border=2)
    buf = BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


# ---------------------------------------------------------------------------
# Admin-Login
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password") or ""
        if secrets.compare_digest(password, ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin_page"))
        error = "Passwort stimmt nicht."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@_require_admin
def admin_page():
    return render_template(
        "admin.html",
        user_url=_public_base() + "/",
        spotify_connected=spotify_client.is_connected(),
        spotify_error=request.args.get("spotify_error"),
    )


# ---------------------------------------------------------------------------
# Spotify-Login (Authorization Code Flow, einmalig pro Admin-Gerät)
# ---------------------------------------------------------------------------

@app.route("/spotify/login")
@_require_admin
def spotify_login():
    state = secrets.token_urlsafe(16)
    session["spotify_oauth_state"] = state
    try:
        url = spotify_client.build_authorize_url(state)
    except SpotifyConfigError as exc:
        return redirect(url_for("admin_page", spotify_error=str(exc)))
    return redirect(url)


@app.route("/spotify/callback")
@_require_admin
def spotify_callback():
    error = request.args.get("error")
    if error:
        return redirect(url_for("admin_page", spotify_error=error))
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state or state != session.get("spotify_oauth_state"):
        return redirect(url_for("admin_page", spotify_error="Ungültige Antwort von Spotify."))
    try:
        spotify_client.exchange_code(code)
    except Exception as exc:  # noqa: BLE001 — Fehlertext direkt anzeigen
        return redirect(url_for("admin_page", spotify_error=str(exc)))
    return redirect(url_for("admin_page"))


@app.route("/spotify/disconnect", methods=["POST"])
@_require_admin
def spotify_disconnect():
    spotify_client.disconnect()
    return redirect(url_for("admin_page"))


@app.route("/api/spotify/token")
@_require_admin
def api_spotify_token():
    try:
        token = spotify_client.get_user_token()
    except SpotifyConfigError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    return jsonify({"ok": True, "access_token": token})


# ---------------------------------------------------------------------------
# Gäste-API: Suche & Anfrage
# ---------------------------------------------------------------------------

@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": False, "error": "Bitte mindestens 2 Zeichen eingeben."}), 400
    blocked, reason = is_blocked_text(q)
    if blocked:
        return jsonify({"ok": False, "error": reason or "Suche nicht erlaubt."}), 400
    try:
        items = spotify_client.search_tracks(q, limit=10)
    except SpotifyConfigError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except requests.RequestException:
        return jsonify({"ok": False, "error": "Spotify-Suche gerade nicht erreichbar."}), 502

    results = []
    with _lock:
        for item in items:
            if reject_reason(item):
                continue
            track = _track_from_spotify(item)
            if not track["title"] or not track["artist"] or not track["spotify_id"]:
                continue
            places = _find_duplicates(track["spotify_id"])
            track["duplicate_in"] = places
            track["already_requested"] = bool(places)
            results.append(track)
            if len(results) >= 8:
                break

    return jsonify({"ok": True, "results": results})


@app.route("/api/request", methods=["POST"])
def api_request():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    spotify_id = (data.get("spotify_id") or "").strip()
    spotify_uri = (data.get("spotify_uri") or "").strip()
    if not title or not artist or not spotify_id or not spotify_uri:
        return jsonify({"ok": False, "error": "Songdaten unvollständig."}), 400

    blocked, reason = is_blocked_text(title, artist, data.get("album") or "")
    if blocked or data.get("explicit"):
        return jsonify({"ok": False, "error": reason or "Inhalt nicht jugendfreundlich"}), 400

    song = {
        "id": uuid.uuid4().hex,
        "title": title,
        "artist": artist,
        "album": (data.get("album") or "").strip(),
        "artwork": (data.get("artwork") or "").strip(),
        "spotify_id": spotify_id,
        "spotify_uri": spotify_uri,
        "spotify_url": (data.get("spotify_url") or "").strip(),
        "duration_ms": data.get("duration_ms") or 0,
        "requested_at": time.time(),
        "source": "request",
    }

    with _lock:
        places = _find_duplicates(spotify_id)
        song["duplicate_in"] = places
        _pending.append(song)
        pending_copy = _public_song(song)

    return jsonify(
        {
            "ok": True,
            "song": pending_copy,
            "already_requested": bool(places),
            "duplicate_in": places,
            "message": _duplicate_message(places)
            if places
            else "Anfrage ist beim Admin. Nach Freigabe kommt der Song in die Warteschlange.",
        }
    )


def _spotify_status() -> tuple[dict | None, list[dict]]:
    """Liest den aktuellen Spotify-Player und die echte Spotify-Warteschlange.

    Es gibt absichtlich keine eigene Server-Queue als Wahrheitsquelle: Spotify
    kann Songs auch außerhalb dieser Webseite hinzufügen/entfernen/abspielen.
    Die UI soll deshalb immer den tatsächlichen Spotify-Zustand anzeigen.
    """
    playback = spotify_client.get_current_playback()
    queue_data = spotify_client.get_queue() or {}

    current = None
    if playback and playback.get("item"):
        item = playback["item"]
        if item.get("type", "track") == "track":
            current = _track_from_spotify(item)

    # Spotify liefert bei /me/player/queue ebenfalls den aktuell laufenden
    # Track. Dieser Fallback ist wichtig, wenn /me/player gerade keinen
    # vollständigen Playback-State zurückgibt.
    if current is None:
        item = queue_data.get("currently_playing")
        if item and item.get("type", "track") == "track":
            current = _track_from_spotify(item)

    queue = []
    current_id = current.get("spotify_id") if current else None
    for item in queue_data.get("queue") or []:
        if item.get("type", "track") != "track":
            continue
        # Der aktuell laufende Track gehört nicht in „Als Nächstes".
        # Falls Spotify ihn über die Queue-API trotzdem mitliefert (teils
        # mehrfach), blenden wir diese Einträge in unserer Anzeige aus.
        if current_id and item.get("id") == current_id:
            continue
        track = _track_from_spotify(item)
        if track.get("spotify_id"):
            queue.append(track)

    return current, queue


@app.route("/api/status")
def api_status():
    try:
        current, queue = _spotify_status()
    except (SpotifyConfigError, RuntimeError):
        with _lock:
            current = None
            queue = []
    with _lock:
        return jsonify(
            {
                "ok": True,
                "now_playing": _public_song(current),
                "queue": [_public_song(s) for s in queue],
                "pending_count": len(_pending),
            }
        )


@app.route("/api/admin/state")
@_require_admin
def api_admin_state():
    try:
        current, queue = _spotify_status()
        spotify_error = None
        playback_state = spotify_client.get_current_playback() if spotify_client.is_connected() else None
    except (SpotifyConfigError, RuntimeError) as exc:
        current, queue = None, []
        playback_state = None
        spotify_error = str(exc)
    with _lock:
        return jsonify(
            {
                "ok": True,
                "spotify_connected": spotify_client.is_connected(),
                "now_playing": _public_song(current, include_uri=True),
                "queue": [_public_song(s, include_uri=True) for s in queue],
                "pending": [_public_song(s, include_uri=True) for s in _pending],
                "playback": {
                    "is_playing": bool((playback_state or {}).get("is_playing")),
                    "position_ms": int((playback_state or {}).get("progress_ms") or 0),
                    "duration_ms": int(((playback_state or {}).get("item") or {}).get("duration_ms") or 0),
                },
                "spotify_error": spotify_error,
            }
        )


@app.route("/api/admin/search")
@_require_admin
def api_admin_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": False, "error": "Bitte mindestens 2 Zeichen eingeben."}), 400
    try:
        items = spotify_client.search_tracks(q, limit=12)
    except SpotifyConfigError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    except requests.RequestException:
        return jsonify({"ok": False, "error": "Spotify-Suche gerade nicht erreichbar."}), 502

    results = []
    with _lock:
        for item in items:
            track = _track_from_spotify(item)
            if not track["title"] or not track["artist"] or not track["spotify_id"]:
                continue
            places = _find_duplicates(track["spotify_id"])
            track["duplicate_in"] = places
            results.append(track)
            if len(results) >= 10:
                break

    return jsonify({"ok": True, "results": results})


def _queue_song_in_spotify(song: dict) -> dict:
    """Legt den Song ausschließlich in die echte Spotify-Warteschlange."""
    spotify_client.add_to_queue(song["spotify_uri"])
    return _public_song(song, include_uri=True)


@app.route("/api/admin/queue-add", methods=["POST"])
@_require_admin
def api_admin_queue_add():
    """DJ-Direktzugriff: Song direkt in die echte Spotify-Warteschlange."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    spotify_id = (data.get("spotify_id") or "").strip()
    spotify_uri = (data.get("spotify_uri") or "").strip()
    if not title or not artist or not spotify_id or not spotify_uri:
        return jsonify({"ok": False, "error": "Songdaten unvollständig."}), 400

    song = {
        "id": uuid.uuid4().hex,
        "title": title,
        "artist": artist,
        "album": (data.get("album") or "").strip(),
        "artwork": (data.get("artwork") or "").strip(),
        "spotify_id": spotify_id,
        "spotify_uri": spotify_uri,
        "spotify_url": (data.get("spotify_url") or "").strip(),
        "duration_ms": data.get("duration_ms") or 0,
        "requested_at": time.time(),
        "source": "dj",
    }
    try:
        with _lock:
            snapshot = _queue_song_in_spotify(song)
    except (SpotifyConfigError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "song": snapshot, "started": False})


@app.route("/api/admin/approve", methods=["POST"])
@_require_admin
def api_admin_approve():
    data = request.get_json(silent=True) or {}
    song_id = data.get("id")
    with _lock:
        song = next((s for s in _pending if s["id"] == song_id), None)
        if not song:
            return jsonify({"ok": False, "error": "Anfrage nicht gefunden."}), 404
        try:
            snapshot = _queue_song_in_spotify(song)
        except (SpotifyConfigError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        _pending.remove(song)
        _queue.append(song)
    return jsonify({"ok": True, "song": snapshot, "started": False})


@app.route("/api/admin/reject", methods=["POST"])
@_require_admin
def api_admin_reject():
    data = request.get_json(silent=True) or {}
    song_id = data.get("id")
    with _lock:
        before = len(_pending)
        _pending[:] = [s for s in _pending if s["id"] != song_id]
        if len(_pending) == before:
            return jsonify({"ok": False, "error": "Anfrage nicht gefunden."}), 404
    return jsonify({"ok": True})


@app.route("/api/admin/advance", methods=["POST"])
@_require_admin
def api_admin_advance():
    """Überspringt den aktuellen Track direkt in Spotify."""
    try:
        spotify_client.skip_to_next()
    except (SpotifyConfigError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@app.route("/api/admin/pause", methods=["POST"])
@_require_admin
def api_admin_pause():
    try:
        spotify_client.pause_playback()
    except (SpotifyConfigError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@app.route("/api/admin/resume", methods=["POST"])
@_require_admin
def api_admin_resume():
    try:
        spotify_client.resume_playback()
    except (SpotifyConfigError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"User-Seite:  {_public_base()}/")
    print(f"Admin-Seite: {_public_base()}/admin")
    if _ADMIN_PASSWORD_GENERATED:
        print(f"Admin-Passwort (automatisch erzeugt, ADMIN_PASSWORD in .env setzen): {ADMIN_PASSWORD}")
    print(f"Spotify-Redirect-URI (muss exakt im Dashboard stehen): {spotify_client.redirect_uri()}")
    app.run(host="0.0.0.0", port=port, debug=False)
