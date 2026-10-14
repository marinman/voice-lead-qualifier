# Scoring rubric, in plain language

Every conversation scores 0-100 on five questions. The score decides what happens next:

- **70+ is Hot.** Offer a meeting with an engineer.
- **40-69 is Warm.** Send a recap and build guide, then a soft meeting ask.
- **Under 40 is Low.** Point to docs and the quickstart. No sales time.

The weights live in `config/scoring.yaml`. Change a number there and the next conversation uses it. There's no code to touch and no LLM making judgment calls. An LLM only turns the transcript into five answers. The points come from fixed rules, so any score can be explained line by line.

Why these weights: **size, timeline, and use case carry 25 points each** because together they tell you whether there's a real project with real budget soon. **Current stack (15)** tells you how ready they are to buy. **Role (10)** matters least, because the wrong person on a great project can still bring in the right one.

---

## Company size (25)

| Answer | Points | Why |
|---|---|---|
| 200+ people | 25 | Budget, volume, and procurement exist. Voice workloads at this size mean meaningful usage. |
| 50-199 | 20 | Often the sweet spot: real budget, fast decisions. |
| 11-49 | 12 | Can buy, but smaller usage and tighter budgets. |
| 1-10 | 5 | Usually self-serve. Great for community and the free tier, not for sales time. |

## Timeline (25)

| Answer | Points | Why |
|---|---|---|
| Under 1 month | 25 | Already choosing infrastructure. Speed to a conversation wins the deal. |
| 1-3 months | 18 | Actively building. Still time to shape the architecture. |
| 3-6 months | 10 | Planning stage. Nurture until it gets closer. |
| Exploring / 6+ months | 4 | No near-term decision. |

## Use case (25)

| Answer | Points | Why |
|---|---|---|
| Production voice agent | 25 | Real users, real traffic, real requirements (latency, scale, reliability). This is the core ICP. |
| Pilot / prototype | 15 | Likely to become production if the pilot works. Worth helping it work. |
| Curiosity / research | 5 | Learning. Docs serve them better than a meeting. |

## Current stack (15)

| Answer | Points | Why |
|---|---|---|
| Evaluating or replacing a vendor | 15 | Already has a budget line and a known pain. The shortest path to a deal. |
| Building in-house | 10 | Has engineering commitment. The pitch is to stop maintaining infrastructure. |
| Starting from zero | 5 | Open field, but needs education first. |

## Role (10)

| Answer | Points | Why |
|---|---|---|
| Decision maker (founder, C-level, VP, head of, director, budget owner) | 10 | Can say yes. |
| Practitioner (engineer, developer, PM) | 5 | Often the champion who picks the tool. Still valuable. |
| Unknown | 0 | Not enough signal yet. |

---

## Worked examples (the three reviewer samples)

| Persona | Size | Timeline | Use case | Stack | Role | Score | Tier |
|---|---|---|---|---|---|---|---|
| VP Eng, 600-person contact-center platform, replacing a vendor this month | 25 | 25 | 25 | 15 | 10 | **100** | Hot |
| Senior engineer, 120-person healthtech, intake pilot next quarter, in-house prototype | 20 | 10 | 15 | 10 | 5 | **60** | Warm |
| Developer on a 3-person side project, curious, no timeline, nothing built | 5 | 4 | 5 | 5 | 5 | **24** | Low |

## Rules for edge cases

- **No answer** to a question scores 0 for that line. The record is flagged *incomplete*, but still scored and routed.
- **If the transcript can't be read** (extraction fails), there's no score. The conversation is saved for human review.
- **Recalibrating:** once a month, compare tiers with what sales accepted (SQL). If Warm leads convert like Hot ones, raise the weights that separate them, or lower the Hot threshold. Document each change in the YAML comment.
