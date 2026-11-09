/* Dashboard polling + actions. No framework, no reloads. */
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
  const btn = $("primary"), btnStop = $("stop");

  // remember loop choice
  try { if (localStorage.loop !== undefined) loopInput.checked = localStorage.loop === "1"; } catch (e) {}
  loopInput.addEventListener("change", () => { try { localStorage.loop = loopInput.checked ? "1" : "0"; } catch (e) {} ; renderButton(); });
  batchInput.addEventListener("input", renderButton);

  function renderButton() {
    const n = Math.max(1, parseInt(batchInput.value || "1", 10));
    const left = state.inbox_count;
    const running = state.status === "running";
    btn.hidden = running; btnStop.hidden = !running;
    if (running) return;
    if (left === 0) { btn.disabled = true; btn.textContent = "Niets te doen — inbox is leeg"; return; }
    btn.disabled = false;
    const verb = state.status === "stopped" ? "Doorgaan" : "Start";
    btn.textContent = loopInput.checked
      ? `▶ ${verb} — alle ${left} in batches van ${n}`
      : `▶ ${verb} — ${Math.min(n, left)} van ${left}`;
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
    badge.textContent = labels[cls] || cls;

    const pct = s.total ? Math.round(100 * s.done / s.total) : 0;
    $("bar").style.width = (running || s.done ? pct : 0) + "%";
    $("bar").parentElement.setAttribute("aria-valuenow", pct);
    let head;
    if (running) head = `${s.done} / ${s.total} · ${pct} %`;
    else if (s.status === "done") head = `${s.added} toegevoegd · ${s.skipped.length} overgeslagen`;
    else if (s.status === "stopped") head = `gestopt · ${s.done} / ${s.total} verwerkt`;
    else head = s.inbox_count ? `${s.inbox_count} bestanden wachten` : "inbox is leeg";
    $("progress_text").textContent = head;
    const el = s.started_at ? ((s.finished_at || Date.now() / 1000) - s.started_at) : 0;
    $("elapsed").textContent = s.started_at ? fmtTime(el) + (running ? " verstreken" : "") : "";
    $("now").textContent = running && s.current.length ? "Nu: " + s.current.join(", ") : "";

    if (running) { batchInput.disabled = true; loopInput.disabled = true; resetInput.disabled = true; }
    renderButton();

    // recent tracks
    const tr = $("tracks");
    tr.innerHTML = s.recent.length ? s.recent.map((t) => `
      <li class="track">
        <img src="/art/${t.id}" alt="" loading="lazy" onerror="this.outerHTML='<div class=&quot;cover--none&quot;>♪</div>'">
        <div>
          <div class="title" title="${esc(t.title)}">${esc(t.title)}</div>
          <div class="artist" title="${esc(t.artist)}">${esc(t.artist)}</div>
          <div class="chips">
            ${t.key ? `<span class="chip chip--key" title="toonsoort · Camelot">${esc(t.key)}${t.camelot ? " · " + esc(t.camelot) : ""}</span>` : ""}
            ${t.bpm ? `<span class="chip chip--bpm">${esc(t.bpm)} BPM</span>` : ""}
            <span class="chip">${esc(t.format)}${t.bitdepth ? " " + esc(t.bitdepth) + "-bit" : ""}</span>
            <span class="chip" title="maandmap">${esc(t.folder)}</span>
          </div>
        </div>
      </li>`).join("") : `<li class="muted">Nog niets in de bibliotheek.</li>`;

    // skipped
    const sk = $("skipped");
    sk.innerHTML = s.skipped.length ? s.skipped.map((k) => `
      <li><div><span class="path">${esc(k.file)}</span><span class="reason">${esc(k.reason)} · blijft in de inbox</span></div>
      <button class="btn btn--small" data-retry="${esc(k.path)}" ${running ? "disabled" : ""}>opnieuw</button></li>`).join("")
      : `<li class="muted" style="background:none;border:0">Niets overgeslagen.</li>`;
    $("retry_all").hidden = !s.skipped.length;
    $("retry_all").disabled = running;
    $("skipped_count").textContent = s.skipped.length;

    // events
    const icons = { added: "✓", skipped: "⚠", error: "✖", batch: "▶" };
    $("events_count").textContent = s.events.length;
    $("events").innerHTML = s.events.length ? s.events.map((e) => `
      <li class="ev-${e.kind}"><span class="t">${e.t}</span><span class="i">${icons[e.kind] || "·"}</span>
      <span class="f" title="${esc(e.file)}">${esc(e.file)}</span><span class="x">${esc(e.text)}</span></li>`).join("")
      : `<li class="muted">Nog geen gebeurtenissen.</li>`;

    // raw log, keep scroll unless at bottom
    const log = $("log");
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
    if (log.textContent !== s.log) { log.textContent = s.log; if (stick) log.scrollTop = log.scrollHeight; }
  }

  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    state = await r.json(); offline = false; render();
  }
  btn.addEventListener("click", () => post("/api/start", {
    batch_size: parseInt(batchInput.value || "1", 10), loop: loopInput.checked, reset: resetInput.checked,
  }).then(() => { resetInput.checked = false; $("events_panel").open = true; }));
  btnStop.addEventListener("click", () => { btnStop.disabled = true; btnStop.textContent = "Stoppen…"; post("/api/stop").then(() => { btnStop.disabled = false; btnStop.textContent = "■ Stop — breekt de huidige batch af"; }); });
  $("skipped").addEventListener("click", (e) => { const b = e.target.closest("[data-retry]"); if (b) post("/api/retry", { path: b.dataset.retry }); });
  $("retry_all").addEventListener("click", () => post("/api/retry", {}));

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
  setInterval(() => { if (state.status === "running") render(); }, 1000); // smooth elapsed clock
})();
