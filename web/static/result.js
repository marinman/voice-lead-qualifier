// Shared rendering for the result card, score breakdown, and transcripts.
// Used by the landing page (voice, text, reviewer mode) and the dashboard.

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function renderTranscript(turns) {
  return (turns || [])
    .map((t) => `<div class="msg ${t.role === "user" ? "user" : "assistant"}">${esc(t.text)}</div>`)
    .join("");
}

function renderBreakdown(rec) {
  if (!rec.score_breakdown) return "";
  const rows = rec.score_breakdown
    .map((b) => `<tr><td>${esc(b.label)}<div class="v">${b.value_label ? esc(b.value_label) : "<i>no answer</i>"}</div></td><td>${b.points} / ${b.max}</td></tr>`)
    .join("");
  return `<table class="breakdown">${rows}</table>`;
}

// Score bar with ticks at the Warm and Hot thresholds.
function renderBar(rec, tiers) {
  const max = rec.max_score || 100;
  const pct = Math.max(0, Math.min(100, (rec.score / max) * 100));
  const ticks = tiers
    ? [tiers.warm, tiers.hot].map((t) => `<span class="tick" style="left:${(t / max) * 100}%" title="${t}"></span>`).join("")
    : "";
  return `<div class="bar"><i style="width:${pct}%"></i>${ticks}</div>`;
}

function renderNextStep(rec, { interactive = true } = {}) {
  const n = rec.next_step || {};
  if (rec.needs_review) {
    return `<div class="next"><h3>${esc(n.headline)}</h3><div class="small">Extraction failed, so the transcript was saved with no score and flagged for review.</div></div>`;
  }
  let actions = "";
  if (n.cta_url) actions += `<a class="btn primary" href="${esc(n.cta_url)}" target="_blank" rel="noopener">${esc(n.cta_label)}</a>`;
  if (n.secondary_url) actions += `<a class="btn" href="${esc(n.secondary_url)}" target="_blank" rel="noopener">${esc(n.secondary_label)}</a>`;
  let email = "";
  if (n.email_capture && interactive) {
    email = `<form class="email-form" data-cid="${esc(rec.id)}">
        <input type="email" required placeholder="you@company.com" aria-label="Work email">
        <button class="btn" type="submit">Send it</button>
      </form><div class="small email-msg"></div>`;
  }
  return `<div class="next"><h3>${esc(n.headline)}</h3><div class="row">${actions}</div>${email}</div>`;
}

function renderResult(rec, tiers, opts = {}) {
  const tierLabel = rec.tier || "Needs review";
  const tierClass = rec.tier || "review";
  const flag = rec.incomplete ? `<span class="flag" title="${esc(rec.end_reason)}">⚠ Incomplete</span>` : "";
  const score = rec.score == null ? "—" : rec.score;
  const method = rec.extraction_method ? ` · extracted by ${rec.extraction_method === "llm" ? "LLM" : "keyword rules"}` : "";
  return `<div class="result">
      <div class="result-top">
        <span class="tier ${tierClass}">${esc(tierLabel)}</span>
        <span class="score">${score}<small> / ${rec.max_score || 100}</small></span>
        ${flag}
      </div>
      ${rec.score == null ? "" : renderBar(rec, tiers)}
      ${renderBreakdown(rec)}
      ${renderNextStep(rec, opts)}
      <div class="meta">Outcome: <span class="mono">${esc(rec.outcome)}</span>${method} · source <span class="mono">${esc(rec.utm_source)}</span></div>
    </div>`;
}

// Email capture on nurture outcomes (event delegation, works for any rendered card).
document.addEventListener("submit", async (e) => {
  const form = e.target.closest(".email-form");
  if (!form) return;
  e.preventDefault();
  const input = form.querySelector("input");
  const msg = form.nextElementSibling;
  const res = await fetch("/api/nurture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: form.dataset.cid, email: input.value }),
  });
  if (res.ok) {
    form.replaceWith(Object.assign(document.createElement("div"), { className: "small", textContent: "Saved. The recap is on its way. (Demo: saved to the nurture table, no email sent.)" }));
    if (msg) msg.remove();
  } else {
    const err = await res.json().catch(() => ({}));
    msg.textContent = typeof err.detail === "string" ? err.detail : "Please enter a valid email.";
  }
});
