const q = document.getElementById("q");
const form = document.getElementById("search-form");
const resultsEl = document.getElementById("results");
const searchMsg = document.getElementById("search-msg");
const clearSearch = document.getElementById("clear-search");
const nowCard = document.getElementById("now-card");
const nowEl = document.getElementById("now-playing");
const queueEl = document.getElementById("queue");
const queueEmpty = document.getElementById("queue-empty");

function art(url) {
  return url
    ? `<img src="${url}" alt="">`
    : `<img alt="" src="data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="88" height="88"><rect fill="#2a261f" width="88" height="88"/></svg>')}">`;
}

function dupLabel(places) {
  if (!places || !places.length) return "";
  const map = {
    now: "läuft gerade",
    queue: "schon in der Warteschlange",
    pending: "schon angefragt, wartet auf Freigabe",
  };
  return places.map((p) => map[p] || p).join(" · ");
}

function songHtml(song, button) {
  const dup = dupLabel(song.duplicate_in);
  return `
    ${art(song.artwork)}
    <div class="meta">
      <h3>${escapeHtml(song.title)}</h3>
      <div class="who">${escapeHtml(song.artist)}</div>
      ${dup ? `<span class="badge warn">${escapeHtml(dup)}</span>` : ""}
    </div>
    ${button}
  `;
}

function escapeHtml(s) {
  return String(s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function clearSearchResults() {
  q.value = "";
  resultsEl.innerHTML = "";
  searchMsg.textContent = "";
  searchMsg.className = "msg";
  q.focus();
}

if (clearSearch) clearSearch.addEventListener("click", clearSearchResults);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = q.value.trim();
  searchMsg.textContent = "Suche …";
  searchMsg.className = "msg";
  resultsEl.innerHTML = "";
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (!data.ok) {
      searchMsg.textContent = data.error || "Keine Treffer.";
      searchMsg.className = "msg bad";
      return;
    }
    if (!data.results.length) {
      searchMsg.textContent = "Nichts Passendes gefunden (oder nicht jugendfreundlich).";
      searchMsg.className = "msg warn";
    } else {
      searchMsg.textContent = `${data.results.length} Treffer`;
      searchMsg.className = "msg";
    }
    for (const song of data.results) {
      const row = document.createElement("article");
      row.className = "song";
      const btn = `<div class="actions"><button type="button">Wünschen</button></div>`;
      row.innerHTML = songHtml(song, btn);
      row.querySelector("button").addEventListener("click", () => requestSong(song, row));
      resultsEl.appendChild(row);
    }
  } catch {
    searchMsg.textContent = "Netzwerkfehler bei der Suche.";
    searchMsg.className = "msg bad";
  } finally {
    q.value = "";
    q.focus();
  }
});

async function requestSong(song, row) {
  const btn = row.querySelector("button");
  btn.disabled = true;
  try {
    const res = await fetch("/api/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(song),
    });
    const data = await res.json();
    searchMsg.textContent = data.message || data.error || "";
    searchMsg.className = data.ok ? (data.already_requested ? "msg warn" : "msg ok") : "msg bad";
    if (data.ok) {
      btn.textContent = "Gesendet";
      refreshStatus();
    } else {
      btn.disabled = false;
    }
  } catch {
    searchMsg.textContent = "Anfrage fehlgeschlagen.";
    searchMsg.className = "msg bad";
    btn.disabled = false;
  }
  q.value = "";
  q.focus();
}

function renderNow(song) {
  if (!song) {
    nowCard.hidden = true;
    return;
  }
  nowCard.hidden = false;
  nowEl.innerHTML = `${art(song.artwork)}<div class="meta"><h2>${escapeHtml(song.title)}</h2><div class="who">${escapeHtml(song.artist)}</div></div>`;
}

function renderQueue(list) {
  queueEl.innerHTML = "";
  queueEmpty.hidden = list.length > 0;
  for (const song of list) {
    const row = document.createElement("article");
    row.className = "song";
    row.innerHTML = songHtml(song, "");
    queueEl.appendChild(row);
  }
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (!data.ok) return;
    renderNow(data.now_playing);
    renderQueue(data.queue || []);
  } catch {
    /* ignore polling errors */
  }
}

refreshStatus();
setInterval(refreshStatus, 4000);
