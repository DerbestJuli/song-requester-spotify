# Jugend-Jukebox – Song-Requester (Spotify Edition)

Gäste wünschen sich Songs über eine Weboberfläche, ein Admin/DJ prüft
und gibt frei (oder legt eigene Songs direkt in die Warteschlange),
die Musik läuft über den **Spotify-Premium-Account** des Admin-Geräts.

## Features

- Nur jugendfreundliche Musik: Spotifys `explicit`-Kennzeichnung wird
  geblockt, dazu eine Wortliste gegen Hassrede, Rassismus, Sexismus usw.
  (in `content_filter.py`)
- Cover-Bilder direkt aus Spotify
- Suchfeld leert sich nach jeder Suche/Anfrage automatisch
- Doppelte Songs werden dem Gast direkt am Treffer angezeigt
  (läuft gerade / in Warteschlange / wartet auf Freigabe)
- QR-Code für Gäste unter `/qr`
- Laufende Musik wird **nie** unterbrochen, wenn ein neuer Song
  freigegeben oder in die Warteschlange gelegt wird
- Getrennte Gäste-Seite (`/`) und passwortgeschützte Admin-Seite (`/admin`)
- Admin sieht alle Anfragen und muss sie manuell bestätigen
- **DJ-Direktzugriff**: der Admin kann eigene Songs ohne Freigabe-Umweg
  sofort in die Warteschlange legen
- Wiedergabe läuft komplett über Spotify (Web Playback SDK) – keine
  Werbung, keine "Song nicht gefunden"-Probleme wie bei YouTube

## Voraussetzungen

- Python 3.10 oder neuer
- Ein **Spotify-Premium-Account**, mit dem am Abend abgespielt wird
- Ein kostenloser **Spotify-Developer-Account**
  ([developer.spotify.com/dashboard](https://developer.spotify.com/dashboard))
- Admin-Gerät (Mac/MacBook laut Plan) mit **Chrome oder Edge** –
  **Safari wird nicht empfohlen**, da die Spotify Web Playback SDK dort
  bekannte Aussetzer bei Play/Pause hat

## 1. Spotify-App im Dashboard anlegen

1. Auf [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
   einloggen, **"Create app"**.
2. Beliebigen Namen/Beschreibung eintragen.
3. Bei **Redirect URIs** exakt eintragen:
   ```
   http://127.0.0.1:5000/spotify/callback
   ```
   (Port anpassen, falls ihr `PORT` in der `.env` änderst.) Spotify
   erlaubt seit 2025 kein `localhost` mehr als Redirect-URI, nur die
   Loopback-IP `127.0.0.1` – das hier muss **zeichengenau** passen,
   sonst gibt es `INVALID_CLIENT: Invalid redirect URI`.
4. Unter **Which API/SDKs are you planning to use?** Web API und Web
   Playback SDK auswählen (falls abgefragt).
5. Speichern, dann in den App-Settings **Client ID** und **Client
   Secret** kopieren (Secret ggf. über "View client secret" anzeigen
   lassen).

## 2. Projekt einrichten

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
```

`.env` öffnen und ausfüllen:

```
SECRET_KEY=<langer zufälliger String>
ADMIN_PASSWORD=<euer Admin-Passwort>
SPOTIFY_CLIENT_ID=<aus dem Dashboard>
SPOTIFY_CLIENT_SECRET=<aus dem Dashboard>
SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/spotify/callback
```

Lasst ihr `ADMIN_PASSWORD` leer, erzeugt die App beim Start automatisch
eins und zeigt es einmalig in der Konsole an.

## 3. Starten

```bash
./run.sh
# oder: python3 app.py
```

Die Konsole zeigt euch die User- und Admin-Adresse im lokalen Netz.

## 4. Einmalig mit Spotify verbinden

**Wichtig:** Für den Spotify-Login muss der Browser wirklich über
`http://127.0.0.1:5000/admin` laufen (nicht über die LAN-IP!), weil
die Redirect-URI zeichengenau matchen muss.

1. `http://127.0.0.1:5000/admin` öffnen, mit `ADMIN_PASSWORD` einloggen.
2. Auf **"Mit Spotify verbinden"** klicken.
3. Mit dem Premium-Account einloggen und die Berechtigung bestätigen.
4. Ihr landet zurück auf der Admin-Seite, der Player verbindet sich
   automatisch (Meldung "Gerät bereit.").

Ab jetzt könnt ihr die Admin-Seite auch über die LAN-IP weiterbenutzen
(z. B. von einem zweiten Gerät für die Freigabe) – nur der einmalige
Spotify-Login selbst muss über `127.0.0.1` laufen. Die Verbindung
bleibt über einen Refresh-Token bestehen, ihr müsst euch nicht bei
jedem Serverstart neu einloggen (Token liegen lokal in
`.spotify_session.json`, die nie in Git landet).

## 5. Testen

- **Gast-Seite** (`/`): Song suchen, "Wünschen" klicken.
- **Admin-Seite** (`/admin`): Anfrage erscheint unter "Wartet auf
  Freigabe" → "Freigeben" → Song startet sofort (wenn nichts lief)
  oder landet in der Warteschlange.
- **DJ-Direktzugriff**: eigene Songs über das Suchfeld unter "Eigene
  Songs (DJ)" suchen und direkt "In Warteschlange" klicken.
- **Play/Pause/Nächster Song**: Buttons im Player-Bereich. Ein Song
  wird automatisch übersprungen, sobald er zu Ende ist.

## Für den Party-Abend

- **Energiesparen am Mac deaktivieren** (Systemeinstellungen → Energie
  sparen → nie in Ruhezustand, solange am Netzteil), sonst kann die
  Wiedergabe unterbrochen werden.
- Den Admin-Tab während des Abends offen und möglichst im Vordergrund
  lassen.
- Lautstärke einmal an Mac + Anlage einstellen.
- Admin-Gerät braucht durchgehend Internet.

## Bekannte Einschränkungen

- **Kein Speicher zwischen Neustarts**: Warteschlange, Pending und
  "jetzt läuft" liegen nur im Arbeitsspeicher. Ein Neustart des
  Servers während der Party leert die Listen (Spotify-Login bleibt
  aber bestehen).
- **Browser-Kompatibilität**: Web Playback SDK läuft zuverlässig in
  Chrome/Edge/Firefox, **nicht in Safari** (bekannte Bugs bei
  Play/Pause). Admin-Gerät entsprechend wählen.
- Der Content-Filter ist eine Wortliste + Spotifys `explicit`-Flag –
  eine erste Hürde, kein perfekter Moderationsdienst. Die manuelle
  Admin-Freigabe bleibt die wichtigere Kontrolle.
- Beim DJ-Direktzugriff wird der Filter bewusst **nicht** angewendet
  (der Admin ist die verantwortliche Aufsichtsperson und wählt selbst).

## Projektstruktur

```
app.py                 Flask-Routen, interne Warteschlange
spotify_client.py      Spotify-Suche + OAuth-Login + Wiedergabe-Aufruf
content_filter.py      Wortliste / Jugendschutz-Filter
templates/             HTML (Jinja)
static/                CSS + JS (inkl. Web Playback SDK-Anbindung)
.env.example           Vorlage für Zugangsdaten (kopieren nach .env)
```

## GitHub-Hinweis

`.env` und `.spotify_session.json` stehen in `.gitignore` und werden
nie committet – darin stecken Client Secret und Zugangstoken. Vor dem
Push kurz `git status` prüfen, falls ihr die `.gitignore` mal geändert
habt.


## Spotify-Wiedergabe

Die Jukebox verwendet **nicht mehr den Spotify Web Playback SDK**. Die Webseite spielt selbst keine Musik.

- Freigeben -> Track wird ausschließlich über `POST /me/player/queue` in die echte Spotify-Warteschlange gelegt.
- Ein freigegebener Track startet dadurch nicht sofort.
- Spotify spielt die Warteschlange auf dem aktiven Spotify-Gerät ab.
- Play/Pause und „Nächster Song“ werden über die Spotify Web API gesteuert.
- Die Anzeige von „Jetzt“ und der Warteschlange wird direkt aus Spotify gelesen.
- Das Entfernen einzelner Queue-Einträge ist über die aktuelle Spotify-Web-API nicht direkt vorgesehen; deshalb gibt es dafür keinen falschen lokalen Entfernen-Button mehr.

Beim ersten Einsatz muss Spotify auf dem gewünschten Gerät geöffnet und dort ein Track bzw. die Wiedergabe gestartet werden. Danach können freigegebene Songs von der Jukebox aus in die Spotify-Warteschlange gelegt werden.
