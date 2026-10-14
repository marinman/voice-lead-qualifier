# Voice Lead Qualifier

A voice AI SDR on a landing page. It qualifies visitors out loud, scores them against a transparent rubric, routes them to a meeting, nurture, or self-serve, and attributes every conversation to its campaign.

It's built on **LiveKit Agents** (Python) and **LiveKit Cloud**, with a FastAPI token server, plain HTML/JS frontend, and SQLite.

- **Landing page** (`/`): the Voice AI Readiness Assessment. Talk to the agent, watch a live transcript, and get a result card (tier, score, breakdown, next step).
- **Dashboard** (`/dashboard/<DASHBOARD_TOKEN>`, private): funnel tiles, hot rate by source and campaign, every conversation with its transcript and points per rubric line.
- **Reviewer mode**: three buttons run Hot, Warm, and Low sample transcripts through the real extraction and scoring live. You don't need a mic or any keys.
- **Campaign package** (`/campaign`): brief, three follow-up emails, and the rubric in plain marketer language.

```mermaid
flowchart LR
  V[Visitor<br/>?utm_source=…] -->|UTMs| P[Landing page]
  P -->|POST /api/token| S[FastAPI]
  S -->|JWT + agent dispatch<br/>+ UTM metadata| P
  P <-->|WebRTC audio +<br/>live transcript| LK[(LiveKit Cloud)]
  LK <--> A[Agent worker<br/>STT · LLM · TTS]
  A -->|finish_qualification| Q[extract → score → route]
  Q --> DB[(SQLite)]
  A -->|lead_result text stream| P
  DB --> D[Dashboard]
  P -. mic denied .-> T[Text fallback] --> Q
  R[Reviewer mode<br/>/fixtures] --> Q
```

## Quick start

Requires Python 3.10–3.13. (3.14 lacks wheels for some agent dependencies.)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # fill in LiveKit keys for voice (optional)
```

**1. Web server.** This alone runs the landing page, text chat, reviewer mode, and dashboard. Set `DASHBOARD_TOKEN` in `.env` first; the dashboard is at `http://localhost:8000/dashboard/<that token>`.

```bash
.venv/bin/uvicorn web.server:app --port 8000
```

(`python3.12 run_web.py --port 8000` does the same without activating the venv.)

Open http://localhost:8000/?utm_source=linkedin&utm_medium=paid_social&utm_campaign=q4-readiness

**2. Voice agent.** Run it in a second terminal. It needs `LIVEKIT_*` in `.env`.

```bash
.venv/bin/python agent/agent.py download-files   # once: VAD model
.venv/bin/python agent/agent.py dev
```

Get keys from a free [LiveKit Cloud](https://cloud.livekit.io) project (Settings → API keys). STT, LLM, and TTS run through **LiveKit Inference** and bill to the same project, so voice needs no other provider keys. Self-hosted `livekit-server --dev` also works: set `AGENT_PROVIDER=openai` and `OPENAI_API_KEY` to use the OpenAI plugins instead.

**3. Tests.** These are the acceptance checks, and they run with zero keys.

```bash
.venv/bin/python -m pytest -q
```

## Deploy (one public HTTPS URL)

The deliverable is a single public link, so nothing runs on your machine at review time. One **Fly.io** app runs everything: the page, the token endpoint, the private dashboard, and the agent worker. A persistent volume holds SQLite. [`start.sh`](start.sh) runs uvicorn and the worker side by side, so both write to the same database file. LiveKit Cloud provides the `wss://` URL, and the browser connects to it directly.

```bash
brew install flyctl
fly auth login
fly launch --no-deploy --copy-config      # pick a unique app name; keep fly.toml
fly volumes create vlq_data --size 1 --region iad
fly secrets set \
  LIVEKIT_URL=wss://<project>.livekit.cloud \
  LIVEKIT_API_KEY=<key> LIVEKIT_API_SECRET=<secret> \
  OPENAI_API_KEY=<key> \
  DASHBOARD_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
fly deploy
```

Paste `https://<app>.fly.dev` into the application. Keep `https://<app>.fly.dev/dashboard/<DASHBOARD_TOKEN>` for yourself, or share it only with the reviewer. (`fly secrets list` shows names only, so save the token when you generate it.)

All secrets live in Fly's secret store. The repo only ships [`.env.example`](.env.example) with variable names. A custom domain is optional (`fly certs add`).

**Alternative layout:** frontend and token endpoint on Vercel, the agent on LiveKit Cloud Agents, and the database on Turso. That's more moving parts, and you'd need to swap the SQLite calls in `qualifier/storage.py` for libSQL.

### Cost guardrails

The link is public, so strangers can start sessions. Every limit is an environment variable. Change one with `fly secrets set NAME=value`, which restarts the machine but doesn't rebuild the code.

| Guardrail | Default | How it's enforced |
|---|---|---|
| Kill switch | `DEMO_ENABLED=true` | `false` makes the token and text-chat endpoints refuse new sessions. The page shows "paused", and reviewer mode keeps working |
| Max call length | `MAX_SESSION_SECONDS=300` | The agent wraps up, scores, and hangs up at 5 minutes. Text chat closes on the next message after the limit |
| Sessions per day | `MAX_SESSIONS_PER_DAY=50` | Counted in SQLite across voice and text, UTC day. Over the cap returns 429 with a friendly message |
| Sessions per visitor | `MAX_SESSIONS_PER_IP_PER_DAY=5` | Per client IP (`Fly-Client-IP`), stored as a hash |
| Reviewer samples | `MAX_SAMPLES_PER_IP_PER_DAY=30` | Samples cost at most one extraction call each |
| Room hygiene | built in | Tokens expire in 5 minutes, rooms allow 2 participants and close 60s after emptying |

**Set hard spend limits at the providers too, because the code can't do that part:**
- **LiveKit Cloud:** STT, LLM, and TTS bill here through LiveKit Inference. Stay on the free/Build plan, or set a usage limit in the project's billing settings.
- **OpenAI** (extraction, or `AGENT_PROVIDER=openai`): use a dedicated project key with a monthly budget limit under Settings → Limits.

Pause the demo instantly with `fly secrets set DEMO_ENABLED=false`.

### Dashboard access

The dashboard is served only at `/dashboard/<DASHBOARD_TOKEN>`, and its API needs the same token in an `X-Dashboard-Token` header. Wrong or missing tokens get a plain 404. If `DASHBOARD_TOKEN` is unset, the dashboard is off. Transcripts are never on a public page: the landing page has no dashboard link, and the dashboard is `noindex`, `no-referrer`, and `no-store`.

## How a call works

1. The page reads `utm_*` from the URL (none means `direct`) and asks for mic access *before* creating a room. If access is denied, it falls back to text chat.
2. `/api/token` mints a room token with an **explicit agent dispatch** (`lead-qualifier`), and the UTMs go in as dispatch metadata. Attribution travels with the session, so no form is needed.
3. The agent discloses itself, asks the five questions one at a time, and briefly confirms each answer. It answers product questions only from `config/faq.md`. For anything else it says "A human can follow up on that one."
4. After Q5 the LLM calls the `finish_qualification` tool. That tool runs the post-call pipeline: LLM extraction to JSON, deterministic scoring, routing, and saving. It pushes the result card to the browser over a LiveKit text stream (`lead_result`), then the agent speaks the routing line and closes the session.
5. The dashboard polls every 5 seconds, so the new row shows up within seconds.

## Scoring

The rubric lives in [`config/scoring.yaml`](config/scoring.yaml). The file is re-read on every score, so a marketer can change a weight and the **next** conversation uses it, with no code change and no restart. (On Fly the file ships in the image, so an edit goes live with `fly deploy`. It's still a config-only change.) The LLM only extracts answers. The points come from plain rules ([`qualifier/scoring.py`](qualifier/scoring.py)), so every score breaks down line by line. The reasoning for each line is in [`campaign/scoring-rubric.md`](campaign/scoring-rubric.md).

| Tier | Score | Outcome | UI |
|---|---|---|---|
| Hot | 70+ | `meeting_offered` | Booking link (`config/links.yaml`) |
| Warm | 40–69 | `nurture` | Email capture → `nurture` table |
| Low | <40 | `resource` | Docs + getting-started links |

## Edge cases

| Case | Behavior |
|---|---|
| Mic denied or no audio device | Text chat runs the same questions and the same `finalize()` pipeline, so the record has the same shape (`channel = text`) |
| 10s of silence | The agent prompts once (LiveKit `user_away_timeout`). After a second silence it wraps up and saves (`end_reason = silence`) |
| Visitor asks to stop | `stop_call` tool ends at once and saves the partial record |
| Visitor hangs up mid-call | The session-close hook scores what exists and saves it with `incomplete = true` |
| Extraction fails | Transcript saved, `score = null`, `needs_review = true`, outcome `needs_review` |
| Keys missing | App boots. The page shows "Voice not configured". Text chat and reviewer mode work |
| Public-link abuse | Daily and per-IP session caps, a 5-minute call limit, and the `DEMO_ENABLED` kill switch (see Deploy) |
| No `OPENAI_API_KEY` | Extraction uses deterministic keyword rules. The method is saved on each record and shown on the card |

## Data model

There's one row per conversation in `data/leads.db`, created at runtime:
`id, created_at, duration_seconds, channel, room_name, transcript (JSON), extracted (JSON), extraction_method, score, tier, outcome, score_breakdown (JSON), utm_source, utm_medium, utm_campaign, incomplete, needs_review, end_reason`. Captured emails go in a `nurture` table, and session starts for the guardrails go in a `usage` table (hashed IPs only).

## Layout

```
agent/agent.py        LiveKit Agents worker (voice SDR, tools, silence + stop handling)
web/server.py         FastAPI: pages, token endpoint, text chat, samples, dashboard API
web/static/           landing page, dashboard, vendored livekit-client
qualifier/            shared core: extraction, scoring, pipeline, storage, FAQ, text chat
config/               scoring.yaml · faq.md · links.yaml   ← marketer-editable
fixtures/             Hot / Warm / Low sample transcripts for reviewer mode
campaign/             brief.md · scoring-rubric.md · emails/
tests/                acceptance checks (no keys needed)
Dockerfile, fly.toml  one-app Fly.io deploy (web + agent + volume)
start.sh              container entrypoint: uvicorn + agent worker
data/                 SQLite, created at runtime
```

## Scope

**MVP:** no CRM sync, no real calendar (placeholder link), no email sending (templates and capture only), English only, one persona.
**Phase 2:** HubSpot sync, real booking, A/B script variants, multilingual.
