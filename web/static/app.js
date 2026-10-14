// Landing page: UTM capture, LiveKit voice session, text fallback, reviewer mode.

const $ = (id) => document.getElementById(id);
const LK = window.LivekitClient;

// ---- attribution -----------------------------------------------------------
const params = new URLSearchParams(location.search);
const utm = {
  utm_source: params.get("utm_source") || "direct",
  utm_medium: params.get("utm_medium"),
  utm_campaign: params.get("utm_campaign"),
};
$("utm-chip").textContent = `attribution · ${[utm.utm_source, utm.utm_medium, utm.utm_campaign].filter(Boolean).join(" / ")}`;

let config = { voice_configured: false, tiers: { hot: 70, warm: 40 } };
let room = null;
let roomName = null;
let gotResult = false;

function setStatus(text, live = false) {
  $("status-text").textContent = text;
  $("dot").classList.toggle("live", live);
}

// Drives the bar visualizer: idle | listening | thinking | speaking.
function setAgentState(state) {
  $("widget").dataset.state = state;
}

function show(view) {
  for (const v of ["idle", "live", "result"]) $(`view-${v}`).hidden = v !== view;
}

function addMsg(role, text, id) {
  const pane = $("transcript");
  let el = id ? pane.querySelector(`[data-seg="${CSS.escape(id)}"]`) : null;
  if (!el) {
    el = document.createElement("div");
    el.className = `msg ${role}`;
    if (id) el.dataset.seg = id;
    pane.appendChild(el);
  }
  el.textContent = text;
  pane.scrollTop = pane.scrollHeight;
}

function showResult(rec) {
  gotResult = true;
  setAgentState("idle");
  const v = $("view-result");
  v.innerHTML = renderVisitorResult(rec) +
    `<details><summary>Show transcript</summary><div class="transcript">${renderTranscript(rec.transcript)}</div></details>` +
    `<div class="controls"><button class="btn" id="restart-btn">Start over</button></div>`;
  $("restart-btn").onclick = () => location.reload();
  show("result");
  setStatus("Complete");
}

// ---- voice -----------------------------------------------------------------
async function startVoice() {
  $("talk-btn").disabled = true;
  setStatus("Checking mic");

  // Ask for the mic before creating a room, so a denial costs nothing and falls back to text.
  try {
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
    probe.getTracks().forEach((t) => t.stop());
  } catch (err) {
    return startText(`Couldn't use your microphone (${err.name}). Switched to text chat: same five questions, same scoring.`);
  }

  setStatus("Connecting");
  let tok;
  try {
    const res = await fetch("/api/token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(utm) });
    if (res.status === 429 || (res.status === 503 && config.voice_configured)) {
      return showLimit((await res.json()).detail);
    }
    if (!res.ok) throw new Error((await res.json()).detail);
    tok = await res.json();
  } catch (err) {
    return startText(`Voice is unavailable right now (${err.message}). Switched to text chat.`);
  }
  roomName = tok.room;

  room = new LK.Room({ adaptiveStream: true, dynacast: true });

  room.registerTextStreamHandler("lk.transcription", async (reader, participant) => {
    $("transcript").querySelector('[data-seg="connecting"]')?.remove();
    const role = participant.identity === room.localParticipant.identity ? "user" : "assistant";
    const seg = reader.info.attributes?.["lk.segment_id"] || reader.info.id;
    let text = "";
    for await (const chunk of reader) {
      text += chunk;
      addMsg(role, text, seg);
    }
  });

  room.registerTextStreamHandler("lead_result", async (reader) => {
    try { showResult(JSON.parse(await reader.readAll())); } catch (e) { console.error(e); }
  });

  room.on(LK.RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === "audio") document.body.appendChild(track.attach());
  });
  room.on(LK.RoomEvent.ParticipantAttributesChanged, (changed, p) => {
    const state = changed["lk.agent.state"];
    if (!state || p === room.localParticipant) return;
    setAgentState(state);
    if (gotResult) return; // keep "Complete" while the agent says its closing line
    setStatus({ listening: "Listening", thinking: "Thinking", speaking: "Speaking", initializing: "Agent joining" }[state] || state, true);
  });
  room.on(LK.RoomEvent.Disconnected, () => {
    $("voice-controls").hidden = true;
    setAgentState("idle");
    if (!gotResult) pollResult();
  });

  try {
    await room.connect(tok.url, tok.token);
    await room.localParticipant.setMicrophoneEnabled(true);
    await room.startAudio();
  } catch (err) {
    console.error(err);
    await room.disconnect();
    return startText(`Couldn't start the voice session (${err.message}). Switched to text chat.`);
  }

  show("live");
  $("voice-controls").hidden = false;
  setStatus("Agent joining", true);
  // The free LiveKit Cloud plan can cold-start the agent (10-20 seconds).
  addMsg("assistant", "Connecting you to the agent. This can take up to 20 seconds…", "connecting");
}

// After a call ends without a pushed result (hang-up, network), the agent still
// saves the partial record. Poll for it.
async function pollResult() {
  setStatus("Scoring");
  for (let i = 0; i < 20 && !gotResult; i++) {
    const res = await fetch(`/api/rooms/${roomName}/result`);
    if (res.ok) return showResult(await res.json());
    await new Promise((r) => setTimeout(r, 1000));
  }
  if (!gotResult) setStatus("Call ended");
}

$("talk-btn").onclick = startVoice;
$("end-btn").onclick = () => room && room.disconnect();
$("mute-btn").onclick = async () => {
  const on = room.localParticipant.isMicrophoneEnabled;
  await room.localParticipant.setMicrophoneEnabled(!on);
  $("mute-btn").textContent = on ? "Unmute" : "Mute";
};

// ---- text fallback ---------------------------------------------------------
let textSession = null;

function showLimit(message) {
  show("idle");
  $("limit-note").textContent = message;
  $("limit-note").hidden = false;
  $("talk-btn").disabled = !config.voice_configured || !config.demo_enabled;
  setStatus("Unavailable");
}

async function startText(notice) {
  const res = await fetch("/api/text/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(utm) });
  const data = await res.json();
  if (!res.ok) return showLimit(data.detail || "The demo is unavailable right now.");
  show("live");
  $("live-viz").hidden = true;
  $("chat-form").hidden = false;
  $("voice-controls").hidden = true;
  setStatus("Text chat", true);
  if (notice) addMsg("assistant", notice);
  textSession = data.session_id;
  data.messages.forEach((m) => addMsg("assistant", m));
  $("chat-input").focus();
}

$("text-btn").onclick = () => startText();
$("chat-form").onsubmit = async (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", text);
  const res = await fetch("/api/text/message", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: textSession, text }) });
  const data = await res.json();
  if (!res.ok) return addMsg("assistant", data.detail || "Something went wrong.");
  data.messages.forEach((m) => addMsg("assistant", m));
  if (data.done) setTimeout(() => showResult(data.result), 900);
};

// ---- reviewer mode ---------------------------------------------------------
document.querySelectorAll("[data-persona]").forEach((btn) => {
  btn.onclick = async () => {
    document.querySelectorAll("[data-persona]").forEach((b) => (b.disabled = true));
    $("sample-result").innerHTML = `<div class="empty">Running extraction and scoring…</div>`;
    try {
      const res = await fetch(`/api/samples/${btn.dataset.persona}`, { method: "POST" });
      const rec = await res.json();
      if (!res.ok) {
        $("sample-result").innerHTML = `<div class="empty">${esc(rec.detail || "Something went wrong.")}</div>`;
        return;
      }
      $("sample-transcript").innerHTML =
        `<div class="card" style="padding:18px"><span class="eyebrow">${esc(rec.persona)} persona</span><div class="small" style="margin:4px 0 12px">${esc(rec.persona_description)}</div>` +
        `<div class="transcript" style="max-height:420px">${renderTranscript(rec.transcript)}</div></div>`;
      $("sample-result").innerHTML = renderResult(rec, config.tiers);
    } finally {
      document.querySelectorAll("[data-persona]").forEach((b) => (b.disabled = false));
    }
  };
});

// ---- boot ------------------------------------------------------------------
(async () => {
  try {
    config = await (await fetch("/api/config")).json();
  } catch {}
  $("max-min").textContent = Math.round((config.max_session_seconds || 300) / 60);
  if (config.demo_enabled === false) {
    $("talk-btn").disabled = true;
    $("text-btn").disabled = true;
    $("limit-note").textContent = "The live demo is paused right now. Reviewer mode below still shows the full system.";
    $("limit-note").hidden = false;
    setStatus("Paused");
  } else if (!config.voice_configured) {
    $("talk-btn").disabled = true;
    $("voice-note").hidden = false;
    setStatus("Voice off");
  }
})();
