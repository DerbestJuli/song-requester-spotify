const pendingEl = document.getElementById("pending");
const pendingEmpty = document.getElementById("pending-empty");
const queueEl = document.getElementById("queue");
const queueEmpty = document.getElementById("queue-empty");
const nowEl = document.getElementById("now-playing");
const playerMsg = document.getElementById("player-msg");
const btnPlay = document.getElementById("btn-play");
const btnSkip = document.getElementById("btn-skip");
const playerArt = document.getElementById("player-art");
const playerTitle = document.getElementById("player-title");
const playerArtist = document.getElementById("player-artist");
const playerProgress = document.getElementById("player-progress");

let skipInFlight = false;

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function art(url) {
  return url
    ? `<img src="${url}" alt="">`
    : `<img alt="" src="data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="88" height="88"><rect fill="#2a261f" width="88" height="88"/></svg>')}">`;
}

function dupBadge(places) {
  if (!places || !places.length) return "";
  return `<span class="badge warn">Doppelt (${places.join(", ")})</span>`;
}

function songBlock(song, actions) {
  return `
    ${art(song.artwork)}
    <div class="meta">
      <h3>${escapeHtml(song.title)}</h3>
      <div class="who">${escapeHtml(song.artist)}</div>
      ${dupBadge(song.duplicate_in)}
    </div>
    <div class="actions">${actions}</div>
  `;
}

// ---------------------------------------------------------------------
// Spotify-Player: Die eigentliche Wiedergabe läuft in Spotify.
// ---------------------------------------------------------------------

function setPlayerStatus(playback) {
  if (!playback) return;
  btnPlay.textContent = playback.is_playing ? "Pause" : "Play";
  if (playback.duration_ms > 0) {
    playerProgress.style.width = `${Math.min(100, (playback.position_ms / playback.duration_ms) * 100)}%`;
  } else {
    playerProgress.style.width = "0%";
  }
}

async function spotifyAction(url) {
  try {
    const res = await fetch(url, { method: "POST" });
    const data = await res.json();
    if (!data.ok) playerMsg.textContent = data.error || "Spotify-Aktion fehlgeschlagen.";
    await refreshState();
  } catch {
    playerMsg.textContent = "Spotify-Aktion fehlgeschlagen.";
  }
}

// ---------------------------------------------------------------------
// Status-Polling (Freigabe / Warteschlange / Jetzt läuft)
// ---------------------------------------------------------------------

function renderNow(song) {
  if (!song) {
    nowEl.className = "empty";
    nowEl.innerHTML = "Nichts läuft.";
    return;
  }
  nowEl.className = "now small";
  nowEl.innerHTML = `${art(song.artwork)}<div class="meta"><h2>${escapeHtml(song.title)}</h2><div class="who">${escapeHtml(song.artist)}</div></div>`;
}

function renderPending(list) {
  pendingEl.innerHTML = "";
  pendingEmpty.hidden = list.length > 0;
  for (const song of list) {
    const row = document.createElement("article");
    row.className = "song";
    row.innerHTML = songBlock(
      song,
      `<button type="button" class="ok" data-act="ok">Freigeben</button>
       <button type="button" class="bad" data-act="no">Ablehnen</button>`
    );
    row.querySelector('[data-act="ok"]').onclick = () => act("/api/admin/approve", song.id);
    row.querySelector('[data-act="no"]').onclick = () => act("/api/admin/reject", song.id);
    pendingEl.appendChild(row);
  }
}

function renderQueue(list) {
  queueEl.innerHTML = "";
  queueEmpty.hidden = list.length > 0;
  for (const song of list) {
    const row = document.createElement("article");
    row.className = "song";
    row.innerHTML = songBlock(
      song,
      `<a class="ghost btn" href="${song.spotify_url}" target="_blank" rel="noopener">In Spotify öffnen</a>`
    );
    queueEl.appendChild(row);
  }
}

async function act(url, id) {
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  refreshState();
}

async function advance() {
  if (skipInFlight) return;
  skipInFlight = true;
  try {
    await fetch("/api/admin/advance", { method: "POST" });
    await refreshState();
  } finally {
    skipInFlight = false;
  }
}

async function refreshState() {
  try {
    const res = await fetch("/api/admin/state");
    if (res.status === 401) {
      window.location.href = "/admin/login";
      return;
    }
    const data = await res.json();
    renderPending(data.pending || []);
    renderQueue(data.queue || []);
    renderNow(data.now_playing);
    setPlayerStatus(data.playback);
    if (data.spotify_error) playerMsg.textContent = data.spotify_error;
    else if (data.now_playing) playerMsg.textContent = data.playback?.is_playing ? "Spotify spielt." : "Spotify pausiert.";
    else playerMsg.textContent = "Kein Track läuft. Starte Spotify auf dem gewünschten Gerät.";
  } catch {
    playerMsg.textContent = "Status nicht geladen.";
  }
}

if (btnSkip) btnSkip.addEventListener("click", advance);
if (btnPlay) {
  btnPlay.addEventListener("click", async () => {
    const label = btnPlay.textContent.toLowerCase();
    await spotifyAction(label.includes("pause") ? "/api/admin/pause" : "/api/admin/resume");
  });
}

// ---------------------------------------------------------------------
// DJ-Direktsuche
// ---------------------------------------------------------------------

const djForm = document.getElementById("dj-search-form");
const djInput = document.getElementById("dj-q");
const djResults = document.getElementById("dj-results");
const djMsg = document.getElementById("dj-msg");
const clearDjSearch = document.getElementById("clear-dj-search");

function clearDjSearchResults() {
  if (!djInput || !djResults || !djMsg) return;
  djInput.value = "";
  djResults.innerHTML = "";
  djMsg.textContent = "";
  djMsg.className = "msg";
  djInput.focus();
}

if (clearDjSearch) clearDjSearch.addEventListener("click", clearDjSearchResults);

if (djForm) {
  djForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = djInput.value.trim();
    djMsg.textContent = "Suche …";
    djMsg.className = "msg";
    djResults.innerHTML = "";
    try {
      const res = await fetch(`/api/admin/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      if (!data.ok) {
        djMsg.textContent = data.error || "Keine Treffer.";
        djMsg.className = "msg bad";
        return;
      }
      djMsg.textContent = data.results.length ? `${data.results.length} Treffer` : "Nichts gefunden.";
      for (const song of data.results) {
        const row = document.createElement("article");
        row.className = "song";
        row.innerHTML = songBlock(song, `<button type="button" data-act="add">In Warteschlange</button>`);
        row.querySelector('[data-act="add"]').onclick = () => addDirect(song, row);
        djResults.appendChild(row);
      }
    } catch {
      djMsg.textContent = "Netzwerkfehler.";
      djMsg.className = "msg bad";
    } finally {
      djInput.value = "";
      djInput.focus();
    }
  });
}

async function addDirect(song, row) {
  const btn = row.querySelector("button");
  btn.disabled = true;
  try {
    const res = await fetch("/api/admin/queue-add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(song),
    });
    const data = await res.json();
    if (data.ok) {
      btn.textContent = "Hinzugefügt";
      refreshState();
    } else {
      btn.disabled = false;
      djMsg.textContent = data.error || "Fehler beim Hinzufügen.";
      djMsg.className = "msg bad";
    }
  } catch {
    btn.disabled = false;
    djMsg.textContent = "Netzwerkfehler.";
    djMsg.className = "msg bad";
  }
}

// ---------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------

if (!window.SPOTIFY_CONNECTED && playerMsg) {
  playerMsg.textContent = "Erst mit Spotify verbinden (oben).";
}

refreshState();
setInterval(refreshState, 3000);
