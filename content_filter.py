"""Filter für jugendfreundliche Songanfragen (Gäste-Suche).

Blockiert Spotify-Treffer mit "explicit"-Kennzeichnung sowie Texte mit
Hasssprache, Rassismus, Sexismus, Gewaltverherrlichung u. ä. in Titel,
Interpret oder Album. Die manuelle Admin-Freigabe bleibt die zweite,
wichtigere Prüfung – dieser Filter ist eine erste Hürde, kein
vollständiger Moderationsdienst.
"""

from __future__ import annotations

# Begriffe in Kleinbuchstaben, Teilstring-Match nach Normalisierung.
BLOCKED_TERMS = {
    # Hass / Rassismus / Rechtsextremismus
    "nigger",
    "nigga",
    "negro",
    "faggot",
    "kike",
    "spic",
    "chink",
    "wetback",
    "kanake",
    "kanaken",
    "neger",
    "nazi",
    "hitler",
    "sieg heil",
    "heil hitler",
    "white power",
    "white pride",
    "kkk",
    "ku klux",
    "antisemit",
    "holocaust leug",
    "jude raus",
    "ausländer raus",
    "auslander raus",
    "döner-killer",
    "nsdap",
    "reichskanzler",
    "untermensch",
    "aryan",
    "14 words",
    "1488",
    # Schwere Beleidigungen / queerfeindlich
    "hurensohn",
    "huren sohn",
    "fotze",
    "schwuchtel",
    "tunte",
    "tranny",
    "shemale",
    # Sexuell explizit (Titel)
    "porn",
    "porno",
    "xxx",
    "onlyfans",
    "stripper",
    "blowjob",
    "handjob",
    "cumshot",
    "orgasm",
    "orgasmus",
    "masturbat",
    "hentai",
    "nsfw",
    "explicit lyrics",
    "parental advisory",
    # Drogenverherrlichung im Titel (grob)
    "cocaine",
    "kokain",
    "heroin",
    "methamphetamine",
    "crack cocaine",
}

_REPLACEMENTS = str.maketrans(
    {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "–": "-",
        "—": "-",
    }
)


def _normalize(text: str) -> str:
    t = (text or "").lower().translate(_REPLACEMENTS)
    return " ".join(t.split())


def is_blocked_text(*parts: str) -> tuple[bool, str | None]:
    blob = _normalize(" ".join(p for p in parts if p))
    if not blob:
        return False, None
    compact = blob.replace(" ", "")
    for term in BLOCKED_TERMS:
        nterm = _normalize(term)
        if " " in nterm:
            if nterm in blob:
                return True, "Inhalt nicht jugendfreundlich"
        else:
            if nterm in blob or nterm in compact:
                return True, "Inhalt nicht jugendfreundlich"
    return False, None


def reject_reason(track: dict) -> str | None:
    """track: ein Roh-Trackobjekt aus der Spotify-Suche (/v1/search)."""
    if track.get("explicit"):
        return "Titel ist als explizit gekennzeichnet"
    title = track.get("name") or ""
    artists = ", ".join(a.get("name") or "" for a in track.get("artists") or [])
    album = (track.get("album") or {}).get("name") or ""
    blocked, reason = is_blocked_text(title, artists, album)
    if blocked:
        return reason
    return None
