"""Kapselt den Spotify-Zugriff."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

# Kein Web Playback SDK mehr: Spotify selbst spielt auf dem aktiven Gerät.
SCOPES = "user-read-email user-read-private user-modify-playback-state user-read-playback-state user-read-currently-playing"

SESSION_FILE = Path(__file__).resolve().parent / ".spotify_session.json"

_lock = threading.Lock()
_app_token: dict = {"access_token": None, "expires_at": 0.0}


class SpotifyConfigError(RuntimeError):
    """Fehlende Konfiguration oder kein gültiges Spotify-Login."""


def _client_id() -> str:
    value = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    if not value:
        raise SpotifyConfigError("SPOTIFY_CLIENT_ID fehlt – bitte in der .env eintragen.")
    return value


def _client_secret() -> str:
    value = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not value:
        raise SpotifyConfigError("SPOTIFY_CLIENT_SECRET fehlt – bitte in der .env eintragen.")
    return value


def redirect_uri() -> str:
    return os.environ.get(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/spotify/callback"
    ).strip()


def _basic_auth_header() -> dict[str, str]:
    raw = f"{_client_id()}:{_client_secret()}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


# ---------------------------------------------------------------------------
# App-Token – für die Songsuche, kein Nutzer-Login nötig
# ---------------------------------------------------------------------------

def get_app_token() -> str:
    with _lock:
        if _app_token["access_token"] and time.time() < _app_token["expires_at"] - 30:
            return _app_token["access_token"]
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers=_basic_auth_header(),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        _app_token["access_token"] = payload["access_token"]
        _app_token["expires_at"] = time.time() + payload.get("expires_in", 3600)
        return _app_token["access_token"]


def search_tracks(query: str, limit: int = 10) -> list[dict]:
    token = get_app_token()
    resp = requests.get(
        f"{API_BASE}/search",
        params={"q": query, "type": "track", "limit": limit, "market": "DE"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=8,
    )
    resp.raise_for_status()
    return ((resp.json().get("tracks") or {}).get("items")) or []


# ---------------------------------------------------------------------------
# User-OAuth – Spotify selbst übernimmt die Wiedergabe
# ---------------------------------------------------------------------------

def _load_session() -> dict | None:
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_session(data: dict) -> None:
    SESSION_FILE.write_text(json.dumps(data))
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": _client_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> None:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
        },
        headers=_basic_auth_header(),
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    with _lock:
        _save_session(
            {
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token"),
                "expires_at": time.time() + payload.get("expires_in", 3600),
            }
        )


def _refresh(session: dict) -> dict:
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        raise SpotifyConfigError("Kein Refresh-Token vorhanden – bitte erneut verbinden.")
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers=_basic_auth_header(),
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    session["access_token"] = payload["access_token"]
    session["expires_at"] = time.time() + payload.get("expires_in", 3600)
    if payload.get("refresh_token"):
        session["refresh_token"] = payload["refresh_token"]
    _save_session(session)
    return session


def is_connected() -> bool:
    return _load_session() is not None


def disconnect() -> None:
    with _lock:
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()


def get_user_token() -> str:
    """Liefert ein garantiert gültiges User-Access-Token."""
    with _lock:
        session = _load_session()
        if not session:
            raise SpotifyConfigError("Spotify ist noch nicht verbunden.")
        if time.time() >= session.get("expires_at", 0) - 60:
            session = _refresh(session)
        return session["access_token"]


def _user_request(method: str, path: str, **kwargs) -> requests.Response:
    token = get_user_token()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=8, **kwargs)


def add_to_queue(uri: str) -> None:
    """Legt einen Track in die echte Spotify-Warteschlange.

    Wichtig: Dieser Endpoint startet den Track NICHT. Spotify spielt ihn erst
    nach dem aktuell laufenden Track ab.
    """
    resp = _user_request("POST", "/me/player/queue", params={"uri": uri})
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"Spotify-Warteschlange fehlgeschlagen ({resp.status_code}): {resp.text[:200]}"
        )


def get_current_playback() -> dict | None:
    resp = _user_request("GET", "/me/player")
    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        raise RuntimeError(
            f"Spotify-Playerstatus fehlgeschlagen ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()


def skip_to_next() -> None:
    resp = _user_request("POST", "/me/player/next")
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"Spotify konnte nicht zum nächsten Song springen ({resp.status_code}): {resp.text[:200]}"
        )


def pause_playback() -> None:
    resp = _user_request("PUT", "/me/player/pause")
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"Spotify konnte nicht pausiert werden ({resp.status_code}): {resp.text[:200]}"
        )


def resume_playback() -> None:
    resp = _user_request("PUT", "/me/player/play")
    if resp.status_code not in (200, 204):
        raise RuntimeError(
            f"Spotify konnte nicht fortgesetzt werden ({resp.status_code}): {resp.text[:200]}"
        )


def get_queue() -> dict | None:
    resp = _user_request("GET", "/me/player/queue")
    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        raise RuntimeError(
            f"Spotify-Warteschlange konnte nicht geladen werden ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()
