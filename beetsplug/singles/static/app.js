/* Dashboard polling + actions. No framework, no reloads. Lists are only
   rebuilt when their content changes, so nothing flickers and focus stays. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = $("dash");
  if (!root) return;

  const fmtTime = (s) => {
    s = Math.max(0, Math.floor(s));
    const m = Math.floor(s / 60), r = s % 60;
    return m >= 60 ? `${Math.floor(m / 60)}u ${m % 60}m` : `${m}m ${String(r).padStart(2, "0")}s`;
  };
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  let state = JSON.parse(root.dataset.state);
  let offline = false;

  const batchInput = $("batch_size"), loopInput = $("loop"), resetInput = $("reset");
  const btn = $("primary"), btnStop = $("stop"), btnText = $("primary_text"), stopText = $("stop_text");

  try { if (localStorage.loop !== undefined) loopInput.checked = localStorage.loop === "1"; } catch (e) {}
  loopInput.addEventListener("change", () => { try { localStorage.loop = loopInput.checked ? "1" : "0"; } catch (e) {} renderButton(); });
  batchInput.addEventListener("input", renderButton);

  // Replace a list's HTML only when its key changes; restore focus afterwards.
  function setList(el, key, html) {
    if (el.dataset.key === key) return;
    const active = document.activeElement, sel = active && active.dataset && active.dataset.retry
      ? `[data-retry="${CSS.escape(active.dataset.retry)}"]` : (active && active.id ? "#" + active.id : null);
    el.dataset.key = key;
    el.innerHTML = html;
    if (sel && el.contains(active) === false) { const n = el.querySelector(sel); if (n) n.focus(); }
  }

  function renderButton() {
    const n = Math.max(1, parseInt(batchInput.value || "1", 10));
    const left = state.inbox_count;
    const running = state.status === "running";
    btn.hidden = running; btnStop.hidden = !running;
    if (running) return;
    if (left === 0) { btn.disabled = true; btnText.textContent = "Niets te doen — inbox is leeg"; return; }
    btn.disabled = false;
    const verb = state.status === "stopped" ? "Doorgaan" : "Start";
    btnText.textContent = loopInput.checked
      ? `${verb} — alle ${left} in batches van ${n}`
      : `${verb} — ${Math.min(n, left)} van ${left}`;
    batchInput.disabled = false; loopInput.disabled = false; resetInput.disabled = false;
  }

  function render() {
    const s = state, running = s.status === "running";
    $("inbox_count").textContent = s.inbox_count;
    $("library_count").textContent = s.library_count;
    $("run_added").textContent = s.added;
    $("run_skipped").textContent = s.skipped.length;

    const badge = $("badge");
    const cls = offline ? "offline" : s.status;
    badge.className = "badge badge--" + cls;
    const labels = { idle: "Klaar om te starten", running: "Bezig", stopped: "Gestopt", done: "Klaar", offline: "Geen verbinding" };
    if (badge.textContent !== labels[cls]) badge.textContent = labels[cls] || cls;

    const pct = s.total ? Math.round(100 * s.done / s.total) : 0;
    $("bar").style.width = (running || s.done ? pct : 0) + "%";
    $("bar").parentElement.setAttribute("aria-valuenow", pct);
    let head;
    if (running) head = `${s.done} / ${s.total} · ${pct} %`;
    else if (s.status === "done") head = `${s.added} toegevoegd · ${s.skipped.length} overgeslagen · ${s.inbox_count} in inbox`;
    else if (s.status === "stopped") head = `gestopt · ${s.done} / ${s.total} verwerkt · ${s.inbox_count} in inbox`;
    else head = s.inbox_count ? `${s.inbox_count} bestanden wachten` : "inbox is leeg";
    if ($("progress_text").textContent !== head) $("progress_text").textContent = head;
    const el = s.started_at ? ((s.finished_at || Date.now() / 1000) - s.started_at) : 0;
    $("elapsed").textContent = s.started_at ? fmtTime(el) + (running ? " verstreken" : "") : "";
    const now = running && s.current.length ? "Nu: " + s.current.join(", ") : "";
    if ($("now").textContent !== now) $("now").textContent = now;

    if (running) { batchInput.disabled = true; loopInput.disabled = true; resetInput.disabled = true; $("verbose").disabled = true; } else { $("verbose").disabled = false; }
    renderButton();

    $("edm_hint").hidden = s.edm_sources.length > 0;
    $("unmatched_count").textContent = s.unmatched_count;
    $("rematch").hidden = !s.unmatched_count;
    $("rematch").disabled = running;
    setList($("tracks"), JSON.stringify(s.recent.map((t) => [t.id, t.key, t.bpm, t.source])), s.recent.length ? s.recent.map((t) => `
      <li class="track">
        <img src="/art/${t.id}" alt="" loading="lazy" onerror="this.outerHTML='<div class=&quot;cover--none&quot; aria-hidden=&quot;true&quot;>♪</div>'">
        <div>
          <div class="title" title="${esc(t.title)}">${esc(t.title)}</div>
          <div class="artist" title="${esc(t.artist)}">${esc(t.artist)}</div>
          <div class="chips">
            ${t.key ? `<span class="chip chip--key"><abbr title="Toonsoort en Camelot-code (1A–12B) voor harmonisch mixen" tabindex="0">${esc(t.key)}${t.camelot ? " · " + esc(t.camelot) : ""}</abbr></span>` : ""}
            ${t.bpm ? `<span class="chip chip--bpm">${esc(t.bpm)} BPM</span>` : ""}
            <span class="chip">${esc(t.format)}${t.bitdepth ? " " + esc(t.bitdepth) + "-bit" : ""}</span>
            <span class="chip" title="maandmap">${esc(t.folder)}</span>
            ${t.source === "none" ? `<span class="chip chip--none"><abbr title="Geen sterke online match gevonden; eigen tags van het bestand gebruikt. Klik op 'opnieuw matchen' zodra Beatport of Discogs aanstaat." tabindex="0">zonder online metadata</abbr></span>` : (t.source ? `<span class="chip" title="metadatabron">${esc(t.source)}</span>` : "")}
          </div>
        </div>
      </li>`).join("") : `<li class="muted">Nog niets in de bibliotheek.</li>`);

    setList($("skipped"), JSON.stringify([running, s.skipped.map((k) => k.path + k.reason)]), s.skipped.length ? s.skipped.map((k) => `
      <li><div><span class="path">${esc(k.file)}</span><span class="reason">${esc(k.reason)} · blijft in de inbox</span></div>
      <button class="btn btn--small" type="button" data-retry="${esc(k.path)}" ${running ? "disabled" : ""}>opnieuw</button></li>`).join("")
      : `<li class="muted" style="background:none;border:0">Niets overgeslagen.</li>`);
    $("retry_all").hidden = !s.skipped.length;
    $("retry_all").disabled = running;
    $("skipped_count").textContent = s.skipped.length;

    const icons = { added: "✓", skipped: "⚠", warn: "·", error: "✖", batch: "▶", sources: "≡" };
    $("events_count").textContent = s.events.length;
    setList($("events"), String(s.events.length) + (s.events[0] ? s.events[0].t + s.events[0].text : ""), s.events.length ? s.events.map((e) => `
      <li class="ev-${e.kind}"><span class="t">${e.t}</span><span class="i" aria-hidden="true">${icons[e.kind] || "·"}</span>
      <span class="f" title="${esc(e.file)}">${esc(e.file)}</span><span class="x">${esc(e.text)}</span></li>`).join("")
      : `<li class="muted">Nog geen gebeurtenissen.</li>`);

    const log = $("log");
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
    const q = $("log_filter").value.trim().toLowerCase();
    const text = q ? s.log.split("\n").filter((l) => l.toLowerCase().includes(q)).join("\n") : s.log;
    if (log.textContent !== text) { log.textContent = text; if (stick) log.scrollTop = log.scrollHeight; }
    $("log_mode").textContent = s.verbose ? "· uitgebreid (-v)" : "";
  }
  $("log_filter").addEventListener("input", render);
  try { if (localStorage.verbose !== undefined) $("verbose").checked = localStorage.verbose === "1"; } catch (e) {}
  $("verbose").addEventListener("change", () => { try { localStorage.verbose = $("verbose").checked ? "1" : "0"; } catch (e) {} });

  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    state = await r.json(); offline = false; render();
  }
  btn.addEventListener("click", () => post("/api/start", {
    batch_size: parseInt(batchInput.value || "1", 10), loop: loopInput.checked, reset: resetInput.checked, verbose: $("verbose").checked,
  }).then(() => { resetInput.checked = false; $("events_panel").open = true; if (!btnStop.hidden) btnStop.focus(); }));
  btnStop.addEventListener("click", () => {
    btnStop.disabled = true; stopText.textContent = "Stoppen…";
    post("/api/stop").then(() => { btnStop.disabled = false; stopText.textContent = "Stop — breekt de huidige batch af"; if (!btn.hidden) btn.focus(); });
  });
  $("skipped").addEventListener("click", (e) => { const b = e.target.closest("[data-retry]"); if (b) post("/api/retry", { path: b.dataset.retry }); });
  $("retry_all").addEventListener("click", () => post("/api/retry", {}));
  $("rematch").addEventListener("click", () => post("/api/rematch", { verbose: $("verbose").checked }).then(() => { $("events_panel").open = true; }));

  async function poll() {
    try {
      const r = await fetch("/api/status", { cache: "no-store" });
      state = await r.json(); offline = false;
    } catch (e) { offline = true; }
    render();
    setTimeout(poll, state.status === "running" ? 2000 : 10000);
  }
  render();
  setTimeout(poll, 2000);
  setInterval(() => { if (state.status === "running") $("elapsed").textContent = fmtTime(Date.now() / 1000 - state.started_at) + " verstreken"; }, 1000);
})();
