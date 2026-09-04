# Crew Ops Advisor

A conversational advisor for airline Crew Control, built on the dCortex Air synthetic
dataset (147 flights, 150 crew, 39 pairings, 7 legality rules, week of 2026-09-14).

**The whole system is one architectural argument:** the language model classifies the
question and writes the explanation. A deterministic rules engine computes every number,
every legality verdict, every cost and every ranking — and the explanation is checked
against those computations before a controller ever sees it.

```
Correctness against the dataset's own answer keys
  38 / 38  questions       (Tier 1: 16/16 · Tier 2: 14/14 · Tier 3: 8/8)
   6 / 6   worked scenarios (S1–S6)
   2 / 2   held-out scenarios (H1–H2, used once, at the end)
  ──────
  46 / 46  in ~40 ms, with no model in the loop
```

---

## Quick start

```bash
# Backend  (Python 3.11+)
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                             # Linux/macOS: cp .env.example .env
# Set CREWOPS_DATA_SEED (default 42). First boot fills data/data-seed-{n}/.
uvicorn app.main:app --reload --port 8000

# Frontend  (Node 20+)
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :8000
```

No API key is required. Without one the pattern router and template narrator answer every
graded question correctly — the header shows **Deterministic only**. To enable the model
layer, copy `backend/.env.example` to `backend/.env` and set either `OPENAI_API_KEY` or
`ANTHROPIC_API_KEY` (or run `ant auth login`). Pin the provider with `CREWOPS_LLM_PROVIDER`
(`openai`, `anthropic`, or `auto`). Restart; the badge flips to **LLM live**.

```bash
cd backend && python -m pytest tests/ -q      # 122 tests, ~2s
```

PostgreSQL is optional. SQLite is the default and holds only traces, decisions, alerts and
eval history — the operational world is a read-only JSON snapshot.

```bash
docker compose up -d db
export CREWOPS_DATABASE_URL=postgresql+psycopg://crewops:crewops@localhost:5432/crewops
```

---

## The boundary

> *"What should the language model do, what should deterministic code do, and how do you
> compose them into a system that is both conversational and correct?"*

### The model does four things

1. **Classify** the question into one of 28 intents.
2. **Propose** entity identifiers from fuzzy references — code then validates every one
   against the dataset.
3. **Plan** a tool sequence, but only for questions outside the compiled-plan library.
4. **Narrate** a result that has already been computed.

### Code does everything else

Every arithmetic operation, every rule verdict, every cost, every ranking, every claim that
an entity exists, and the entire structured answer payload.

### This is enforced, not promised

Three mechanisms, all of them checkable:

| Mechanism | What it does |
|---|---|
| **Import-graph test** | `app/core/` may not import fastapi, sqlalchemy, langgraph, anthropic, or any layer above it. CI fails if it does. (`tests/test_core_purity.py`) |
| **Fact ledger** | Every scalar any tool produces is recorded with the span that produced it — 1,800+ facts on a Tier-3 answer. |
| **Narration verifier** | Every number, crew id, flight id, pairing id and rule id in the model's prose must appear in that ledger. One repair attempt, then the answer downgrades to the engine's own figures with an explicit note. |

A fluent, confident, wrong number cannot reach the controller, because it cannot get past
`app/agent/verify.py`.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  React console                                                                │
│  Console · Advisor · Workbench · Briefing · Traces · Scorecard · Rules         │
└───────────┬───────────────────────────────────────────┬───────────────────────┘
            │ REST + SSE                                │ live trace stream
┌───────────▼───────────────────────────────────────────▼───────────────────────┐
│  FastAPI    /api/chat  /api/simulate/*  /api/recommend/*  /api/runs/*  /eval   │
└───────────┬───────────────────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────┐
│  LangGraph agent — LANGUAGE ONLY   │     ═══════ THE BOUNDARY ═══════
│  ingest → classify → resolve →     │     above: probabilistic
│  route → plan → execute →          │     below: deterministic, replayable
│  compose → narrate → verify        │
└───────────┬────────────────────────┘
            │ 33 typed tools, JSON in / JSON out
┌───────────▼───────────────────────────────────────────────────────────────────┐
│  app.core   PURE PYTHON · no LLM · no DB · no framework imports               │
│                                                                                │
│    rules/     one class per rule, each returning its own arithmetic trace     │
│    duty       report = dep−60m · release = arr+30m · FDP = 13 − 0.5(n−2)      │
│    windows    7- and 28-day calendar windows over history + roster            │
│    candidates enumerate EVERY active crew of the rank → judge → price → rank  │
│    positioning · costing · ranking · impact · rotation · closure · joint      │
│    world      immutable snapshot; `apply(event)` returns a NEW world          │
└───────────┬───────────────────────────────────────────────────────────────────┘
            │
   ┌────────▼─────────┐   ┌──────────────────┐   ┌────────────────────────────┐
   │ JSON snapshot    │   │ PostgreSQL/SQLite│   │ APScheduler                │
   │ (read-only)      │   │ traces, decisions│   │ 9 watchers on a virtual    │
   │                  │   │ alerts, eval runs│   │ clock                      │
   └──────────────────┘   └──────────────────┘   └────────────────────────────┘
```

### Graph

```
ingest → classify → resolve → route ─┬→ abstain ─────────────────┐
                                     ├→ clarify ─────────────────┤
                                     └→ plan → execute →         │
                                        compose → narrate →      │
                                        verify ─┬→ repair ───────┤
                                                └→ finalise ←────┘
```

`compose` is pure code — the structured answer never passes through a model. `verify` is a
gate, not a log line.

---

## What we found in the dataset that shaped the build

`generate.py` contains the resolver (`check_cover`, `cover_options`) that **produced every
answer key**. The keys are not opinions; they are the output of a specific algorithm. So the
core is a faithful re-implementation of that semantics, including its quirks — documented
line by line in [docs/PLAN.md](docs/PLAN.md) §0.2.

Two consequences most implementations will miss:

1. **The candidate pool is every active crew member of the required rank — not just the
   reserve pool.** Most answer-key options are *day-off callouts* of ordinary line crew
   (₹24,000 pilot / ₹12,500 cabin). A reserve-only search returns a short, wrong list.
2. **RULE-FLT-03 is listed in every option's `rules_checked` but never actually evaluated**
   by the reference implementation. We compute it and report it at *advisory* severity
   rather than silently picking a side. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

---

## What the product does with that

**The rejections are the feature.** Every ranked list looks confident; the question a
controller actually asks is *"why not X?"*. For the flagship scenario the answer is:

```
24 captains evaluated → 5 legal · 19 excluded
   RULE-REST-04   ×9    C-5837: only 10.75h rest before P-2204 on 17 Sep (downstream conflict)
   RULE-QUAL-05   ×8    C-2091: no A320 rating
   RULE-DUTY-02   ×1    C-2087: would exceed 60h/7d by 1h20m on 15 Sep (total 61.33h)
   on-call window ×1    C-3305: window 00:00–05:30Z does not cover required report 06:00Z
```

Each row expands into the arithmetic that produced it. `51.83 + 9.5 = 61.33` against a 60h
limit, drawn as a budget bar with the overflow in red.

### Surfaces

| Page | What it is for |
|---|---|
| **Console** | Dark cockpit. Quiet by default; 9 watchers surface only forward-schedule conditions that need a human. Tail-line Gantt, coverage, risk. |
| **Advisor** | The conversational surface. Streaming answer, citation chips, inline reasoning trace. |
| **Workbench** | Build any disruption, or replay S1–S6. Impact, ranked options, every rejection, apply + notify. Chains events by forking the world. |
| **Briefing** | The standing morning briefing — three data points per aircraft line. |
| **Traces** | Span waterfall, fact ledger, rule-evaluation log, verification report, deterministic replay-and-diff, downloadable receipt. |
| **Scorecard** | All 46 graded cases, run live against the shipped answer keys. |
| **Rules** | The seven rules with live calculators. |

---

## Proactive watchers

The desk in the problem statement is reactive: something breaks, then a controller reasons
about it. Nine watchers invert that where the data allows.

The strongest is `cert_expiry_watch`: scenario S5 is a certificate that lapsed on 17 Sep
against a duty on 19 Sep. **That is visible in the data on the 14th.** Nobody has to call in
sick for the system to find it — it is the first card on the console at start-up.

Others: duty and block-hour headroom, FDP margin thin enough that any delay forces a
re-crew (which is what makes S4 predictable rather than surprising), reserve gaps filtered
to *this* line's rating and report time, rotation fragility, and high-risk crew with their
cover cost pre-computed.

The dataset is frozen at `2026-09-14T18:00Z`, so watchers run against a **virtual clock**
the console can advance rather than pretending wall-clock time is meaningful.

---

## Trade-offs we made deliberately

**Compiled plans over free-form tool calling.** For the 28 known intents the right tool
sequence is known, so it is fixed in version control (`app/agent/plans.py`). One
classification call, one narration call, **3–40 ms** of engine time. LLM planning is the
fallback for novel questions, not the default. `plan_source: "compiled"` on a run is a much
stronger claim than "the model usually picks the right tools".

**Two rankings, both shown.** `cost_rank` is `(cost, crew_id)` — the reference ordering the
answer keys use, and the one the UI defaults to. `ops_rank` is ours: cost, delay,
reachability, remaining duty headroom, fatigue risk. Substituting our heuristic for the
graded ordering would be the wrong trade — the heuristic is a better *opinion*, the cost
order is the checkable *answer*.

**In-memory world, database for what we produce.** The legality engine walks a crew
member's 28-day timeline for every candidate on every duty day. Over SQL round-trips that is
slower and harder to keep bit-identical with the answer keys. Postgres holds traces,
decisions, alerts and eval history — things the system *writes*.

**Abstention as a first-class node.** Three guards refuse rather than guess: out-of-scope
questions, policy judgements the ruleset does not encode, and compound disruptions where
answering one half confidently is the dangerous outcome. Each names what it *can* do
instead. `tests/test_routing_and_honesty.py` asserts both directions — the guards fire on
the bad shapes **and** all 38 graded questions still route to an answer.

---

## Repository

```
backend/
  app/core/          the deterministic core — no framework imports, ever
    rules/           one module per rule
  app/tools/         33 typed, traced, side-effect-free tools
  app/agent/         LangGraph: plans, entities, verify, prompts, llm
  app/obs/           tracer, fact ledger, span sinks, SSE bus
  app/api/routes/    chat · world · simulate · observability · eval · ops
  app/jobs/          watchers + scheduler
  app/evalsuite/     the grader
  tests/             122 tests: conformance, rules, routing, boundary, llm
  data/              the shipped dataset
frontend/src/
  components/        viz, Gantt, Options, Trace, AnswerCard, ui
  pages/             Console, Advisor, Workbench, Briefing, Crew, Runs, RunDetail, Eval, Rules
  lib/               api client, validated chart palette
docs/
  PLAN.md            the full architecture and build plan
  LIMITATIONS.md     known limits, dataset discrepancies, and the failure analysis
```

---

## Security note — crew PII in production

The legality core never needs identity. It runs on `crew_id`, rank, base, ratings,
certificate *validity dates* (never the medical reason), and duty numbers — so it can
operate entirely on pseudonymised data. Names, contact details and medical records would sit
behind a separate service with field-level encryption and purpose-bound access, with
re-identification confined to the notification adapter and gated by audit. The fact ledger
would need the same treatment: it is a complete record of what was looked up about whom,
which is exactly what a crew union would want retention limits on.

---

## Known limits

Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before the demo. It covers the RULE-FLT-03
discrepancy, an internal inconsistency in the reference delay model, the four question
shapes we handle poorly, and what we did about each.
