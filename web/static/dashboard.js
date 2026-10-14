const $ = (id) => document.getElementById(id);
let tiers = { hot: 70, warm: 40 };

const pct = (x) => `${Math.round(x * 100)}%`;
const when = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const tierPill = (t) => (t ? `<span class="tier ${t}">${t}</span>` : `<span class="tier review">Review</span>`);

function tile(k, v, s = "") {
  return `<div class="card tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
}

async function load() {
  const data = await (await fetch(`/api/conversations?include_samples=${$("samples").checked}`)).json();
  const s = data.stats;
  $("tiles").innerHTML =
    tile("Conversations", s.total, `${s.incomplete} incomplete · ${s.needs_review} need review`) +
    tile("Hot", s.hot, `score ≥ ${tiers.hot}`) +
    tile("Warm", s.warm, `${s.nurture_emails} nurture emails captured`) +
    tile("Hot rate", pct(s.hot_rate), "of scored conversations") +
    tile("Meeting offers", s.meeting_offers, "booking link shown");

  $("sources").innerHTML = data.by_source.length
    ? data.by_source.map((r) => `<tr><td class="mono">${esc(r.utm_source)}</td><td class="mono">${esc(r.utm_campaign)}</td><td class="num">${r.total}</td><td class="num">${r.hot}</td><td class="num">${r.warm}</td><td class="num">${r.low}</td><td class="num">${pct(r.hot_rate)}</td></tr>`).join("")
    : `<tr><td colspan="7" class="small">No conversations yet.</td></tr>`;

  $("rows").innerHTML = data.rows.length
    ? data.rows.map((r) => `<tr class="click" data-id="${esc(r.id)}">
        <td style="white-space:nowrap">${when(r.created_at)}</td>
        <td><span class="pill">${esc(r.channel)}</span>${r.incomplete ? ' <span class="pill" title="incomplete">⚠</span>' : ""}</td>
        <td class="mono">${esc(r.utm_source)}${r.utm_campaign ? " / " + esc(r.utm_campaign) : ""}</td>
        <td class="num">${r.score ?? "—"}</td>
        <td>${tierPill(r.tier)}</td>
        <td class="mono">${esc(r.outcome)}</td>
        <td class="uc" title="${esc(r.use_case)}">${esc(r.use_case) || "—"}</td></tr>`).join("")
    : `<tr><td colspan="7" class="small">No conversations yet. Run a reviewer sample or talk to the agent.</td></tr>`;
}

async function openDetail(id) {
  const rec = await (await fetch(`/api/conversations/${id}`)).json();
  const utm = [rec.utm_source, rec.utm_medium, rec.utm_campaign].filter(Boolean).join(" / ");
  $("drawer").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:start">
      <div><h2>Conversation ${esc(rec.id)}</h2>
      <div class="small">${when(rec.created_at)} · ${esc(rec.channel)} · ${rec.duration_seconds ?? "?"}s · ended: ${esc(rec.end_reason)}</div>
      <div class="small mono">${esc(utm)}</div></div>
      <button class="btn" id="close-drawer">Close</button>
    </div>
    <h3 class="sub">Score breakdown</h3>
    ${renderResult(rec, tiers, { interactive: false })}
    <h3 class="sub">Extracted fields</h3>
    <pre class="card mono" style="padding:12px;white-space:pre-wrap;margin:0">${esc(JSON.stringify(rec.extracted, null, 2))}</pre>
    <h3 class="sub">Transcript</h3>
    <div class="transcript">${renderTranscript(rec.transcript)}</div>`;
  $("drawer").classList.add("open");
  $("drawer-bg").classList.add("open");
  $("close-drawer").onclick = closeDetail;
}

function closeDetail() {
  $("drawer").classList.remove("open");
  $("drawer-bg").classList.remove("open");
}

$("rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) openDetail(tr.dataset.id);
});
$("drawer-bg").onclick = closeDetail;
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDetail());
$("samples").onchange = load;

(async () => {
  try { tiers = (await (await fetch("/api/config")).json()).tiers; } catch {}
  load();
  setInterval(load, 5000);
})();
