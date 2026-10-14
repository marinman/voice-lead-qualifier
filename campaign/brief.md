# Campaign brief: Voice AI Readiness Assessment

**Owner:** Demand Gen · **Motion:** always-on · **Primary KPI:** cost per Hot conversation

## The idea

The best proof that a voice AI platform works is talking to one. So the lead form *is* a voice agent. Visitors get a three-minute assessment and a next step that fits their project. We get a qualified, scored, attributed conversation instead of a five-field form, and the product demos itself on every visit.

## Audience

| Segment | Who | Why they come |
|---|---|---|
| Primary | Eng leaders and senior engineers at 50+ person companies shipping a voice agent in the next two quarters (contact center, healthcare intake, scheduling, voice-first products) | They need to choose infrastructure soon and want to know what "production-ready" takes |
| Secondary | Teams already on another voice provider and hitting latency, cost, or control limits | Evaluating a switch |
| Tertiary | Builders, startups, students | Learning. Served by self-serve resources, not sales time |

## Offer

**Free Voice AI Readiness Assessment.** Three minutes, out loud. You leave with a clear next step: a working session with an engineer (Hot), a readiness recap and build guide (Warm), or the quickstart (Low).

## Always-on motion

1. **Paid social (LinkedIn)** targets job titles plus company size and the voice/CX industries, linking to the assessment page. Creative leads with the hook "Talk to the form."
2. **Paid search** covers high-intent terms ("voice agent framework," "build AI voice agent," "[competitor] alternative," "low-latency voice AI") and sends clicks to the same page with UTMs per ad group.
3. **Retargeting** goes to visitors who landed but didn't talk, plus Warm leads who didn't open nurture. It drives to a **recorded 90-second walkthrough** of a real assessment, for people who won't talk to a bot cold.
4. **Organic and community:** a dev-community post on how the agent was built (the repo is the content), and an assessment link in docs and the newsletter.

Every link carries `utm_source / utm_medium / utm_campaign`. The page passes the UTMs into the voice session, so every scored conversation is attributed without a form.

## Routing and nurture

| Tier | Score | In-call | Follow-up |
|---|---|---|---|
| Hot | 70+ | Agent offers a meeting, booking link on screen | Email 1 at +24h if no booking. SDR task at +48h |
| Warm | 40-69 | Agent offers recap + build guide, email capture | Email 2 at once (recap), Email 3 at +5 days (guide + soft meeting ask) |
| Low | <40 | Agent points to docs and quickstart | Product newsletter only. Re-score on any return visit |

Incomplete calls get scored on the answers they did give and flagged. Failed extractions go to a human review queue rather than being dropped.

## Success metrics

| Metric | Why it matters | Starting target |
|---|---|---|
| **Cost per Hot conversation** | North-star efficiency metric across channels | Benchmark in the first 30 days, then cut 20% |
| **MQL → SQL rate** (Hot + Warm → sales-accepted) | Proves the rubric predicts real pipeline | Hot ≥ 40%, Warm ≥ 10% |
| Visit → conversation start | Measures how well the page and the "talk to the form" hook land | ≥ 15% |
| Conversation completion rate | Measures script quality and length | ≥ 70% |
| Hot rate by source/campaign | Where to shift budget | Reviewed weekly from the dashboard |
| Meeting booked rate (Hot) | Measures the in-call offer and follow-up | ≥ 35% |

## Operating cadence

- **Weekly:** shift budget toward the sources with the best Hot rate and cost per Hot. Read 10 transcripts from each tier.
- **Monthly:** compare rubric tiers with SQL outcomes and tune weights in `config/scoring.yaml`. Every change is a one-line diff with its reasoning.
- **Phase 2:** HubSpot sync, real booking, A/B test script variants (question order, disclosure wording), multilingual.
