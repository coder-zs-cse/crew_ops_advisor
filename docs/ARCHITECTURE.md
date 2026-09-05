# The Boundary — Crew Ops Advisor system architecture

> The rendered version of this document — the same content as hand-drawn diagrams,
> themed for light/dark — is [`architecture_digram.html`](architecture_digram.html) in
> this same folder. Open it directly in a browser; it has no build step and no external
> dependency beyond a Google Fonts stylesheet (it degrades to system fonts offline).
> This file is the plain-text companion for reading on GitHub or in a terminal.

Every query enters through the same pipeline and crosses the same line: a language
model on one side that classifies and narrates, and **deterministic Python on the
other that computes every number, verdict, cost and ranking**. This document traces
that pipeline through all three question tiers, the mechanism that checks the model's
own words against what the code actually produced, the tool and cron-job inventory,
and the routing decision tree.

| | |
|---|---|
| Engine conformance | **46 / 46** — 38 questions (16 T1 / 14 T2 / 8 T3), 6 worked scenarios, 2 held-out scenarios used once. Calls `app.core` directly, no model, ~60ms total. |
| Live-agent conformance | **36 / 38 (94.7%)** — each question's own English through the real agent, model included, ~2 minutes wall time. |
| Automated tests | **117** passing in ~2s, gating every commit |
| Tools | **33** typed, traced, side-effect-free |
| Proactive watchers | **9**, on a virtual clock |
| Measured latency | 28ms, one Tier-3 recommendation, end to end |

---

## 0. Component view

Five layers, one hard line through the middle. Everything above the line proposes;
everything below it decides. The line isn't a design intention — it's a test
(`tests/test_core_purity.py`) that walks the import graph of `app/core` and fails the
build if it ever imports FastAPI, SQLAlchemy, LangGraph, or Anthropic's SDK.

```mermaid
flowchart TB
    UI["React console<br/>Console · Advisor · Workbench · Briefing · Traces · Scorecard · Rules"]
    API["FastAPI<br/>/api/chat · /api/simulate/* · /api/recommend/* · /api/runs/* · /api/eval"]
    AGENT["LangGraph agent — LANGUAGE ONLY<br/>ingest → classify → resolve → route → plan → execute → compose → narrate → verify<br/><i>proposes entities and prose · computes no number, no verdict</i>"]
    CORE["app.core — PURE PYTHON<br/>rules/ · duty · windows · candidates · positioning · costing · ranking · impact · rotation · closure · joint · world<br/><i>no fastapi · no sqlalchemy · no langgraph · no anthropic — enforced by tests/test_core_purity.py</i>"]
    JSON[("JSON snapshot<br/>read-only<br/>147 flights · 150 crew · 39 pairings")]
    DB[("Postgres / SQLite<br/>traces · decisions · alerts · eval runs")]
    SCHED["APScheduler<br/>9 watchers on a virtual clock"]

    UI -- "REST + SSE" --> API
    API -- "invokes the graph" --> AGENT
    AGENT == "THE BOUNDARY<br/>33 typed tools · JSON in / JSON out" ==> CORE
    CORE --> JSON
    CORE --> DB
    CORE --> SCHED
```

The operational world (flights, crew, rosters, duty clocks) is a read-only snapshot
loaded once into memory. The database only holds what the system *produces*: traces,
decisions, alerts, eval history. Nothing an answer depends on lives in a table that
could drift from the code that computed it.

---

## 1. The pipeline every question runs

One LangGraph, ten nodes, no exceptions. A lookup and a ranked recommendation enter the
same door — they only diverge for one step, `execute`, and only because they call
different tools. `compose` is pure code in every tier: the structured answer the UI
renders never passes through a model. Only `narrate` touches the LLM, and only to
describe what `compose` already decided.

```mermaid
flowchart LR
    ingest --> classify --> resolve --> route{route}
    route -- "out of scope / policy" --> abstain[ABSTAIN]
    route -- "compound / missing id" --> clarify[CLARIFY]
    route -- plan --> execute
    execute -- "Tier 1: 13 retrieval tools" --> t1["≈2ms"]
    execute -- "Tier 2: simulate_* + check_legality" --> t2["World.apply forks · ≈5ms"]
    execute -- "Tier 3: enumerate/resolve/solve_joint" --> t3["7-rule engine × candidates · ≈10-30ms"]
    t1 & t2 & t3 --> compose["compose (pure code)"]
    compose --> narrate["narrate (LLM)"]
    narrate --> verify{verify}
    verify -- "fail, ≤1 attempt" --> repair --> narrate
    verify -- "fail again" --> downgrade["DOWNGRADE<br/>engine's own figures + a note"]
    verify -- pass --> finalise[FINALISE]
    downgrade --> finalise
```

### What actually changes between tiers

Nothing about the graph. Only which tools `execute` calls and which schema `compose`
reaches for. A Tier-3 recommendation is not a bigger prompt — it's the same pipeline
pointed at a bigger deterministic computation.

| Tier | Example question | Tools called | `compose()` schema | Measured |
|---|---|---|---|---|
| 1 · Lookup | "Who is on reserve at BLR on 15 Sep, and what are their on-call windows?" | `get_reserves` | `reserve_list` | < 5 ms |
| 2 · Consequence | "BLR is closed 08:00–14:00Z on 17 Sep. Which flights are affected?" | `simulate_station_closure` | `closure` | ~8 ms |
| 3 · Recommendation | "Captain C-1042 is out for pairing P-2291. What should I do?" | `resolve_disruption` → 7-rule engine × 24 candidates | `recommendation` | 28 ms |

---

## 2. Inside the rule engine — the flagship case

The candidate pool is **every active crew member of the required rank** — not the
reserve list. Most answer-key options turn out to be day-off callouts of ordinary
line crew; a reserve-only search would return a short, wrong list.

Walking Captain C-1042's sick call for pairing P-2291 through every gate:

```mermaid
flowchart TD
    pool["CANDIDATE POOL<br/>25 active Captains − 1 sick = 24"]
    g1{"GATE 1 · RULE-QUAL-05<br/>type-rated for A320?"}
    g2{"GATE 2 · WINDOW + BASE-07<br/>on-call window covers the report?"}
    g3{"GATE 3 · seven-rule engine<br/>FDP-01 · DUTY-02 · FLT-03 · REST-04 · CERT-06"}
    legal["5 LEGAL CANDIDATES<br/>ranked & priced"]

    pool --> g1
    g1 -- "fail ×8, no A320 rating" --> excluded[/EXCLUDED — 19 of 24/]
    g1 -- "16 remain" --> g2
    g2 -- "fail ×1, window doesn't cover report" --> excluded
    g2 -- "15 remain" --> g3
    g3 -- "fail ×10 across DUTY-02, REST-04 …" --> excluded
    g3 -- "5 legal" --> legal
```

| Rank | Crew | Action | Cost | Delay |
|---|---|---|---|---|
| 1 | C-3310 | reserve callout | ₹18,500 | — |
| 2 | C-1526 | day-off callout | ₹24,000 | — |
| 5 | C-2210 | reserve + deadhead (DEL) | ₹41,200 | +3.0h |
| 6 | — | cancel all 6 legs (last resort) | ₹15,00,000 | — |

Every rejection carries a reason string with the rule and the exact arithmetic — not
"trust the model," but **"here are 19 names and the number that disqualified each
one."**

---

## 3. The verification loop

The model's prose is not trusted on arrival. Every scalar any tool produced during the
run — 1,831 of them, on this example — is recorded in an append-only fact ledger.
Before an answer ships, every number, crew id, flight id, pairing id and rule name in
the model's draft is checked against that ledger.

```mermaid
flowchart LR
    ledger[("FACT LEDGER<br/>append-only, this run<br/>⋮ 1,831 facts")]
    narrate["NARRATE (LLM)<br/>'use only these facts'"]
    draft["draft narration"]
    verify{"VERIFY<br/>7 checks vs. ledger"}
    shown["SHOWN TO CONTROLLER<br/>✓ 7/7 checks passed"]
    repair["repair (≤1)"]
    downgrade["DOWNGRADE<br/>engine's own figures + explicit note"]

    ledger -- context --> narrate --> draft --> verify
    verify -- pass --> shown
    verify -- "fail" --> repair --> narrate
    verify -- "fail again" --> downgrade
```

Illustrative catch: a draft claims "40 candidates." `evaluated_count` in the ledger is
24 — no fact matches 40 → rejected, repaired. `app/agent/verify.py` is the gate: a
fluent, confident, wrong number cannot reach the controller, because narration that
references a value the tools never produced fails this check — it is code, not a
style guideline.

---

## 4. Proactive watchers on a virtual clock

The desk in the brief is reactive — something breaks, then a controller reasons about
it. Nine watchers invert that where the data allows: they scan the forward schedule
for conditions that are already true and would otherwise become a 05:00 emergency.

Example — the first alert on the console at start-up: C-5417's recurrent training
expires 17 Sep; they're rostered on P-2213, 19 Sep → **CRITICAL** alert, raised on the
snapshot date, three days before it would otherwise surface as a pre-flight compliance
failure.

| Watcher | Fires when |
|---|---|
| `cert_expiry` | A certificate lapses *before* a duty the crew member is already rostered on |
| `cert_expiring_soon` | Any active crew member's certificate expires within 30 days |
| `duty_limit` | Projected 7-day duty reaches 90% of the 60h RULE-DUTY-02 ceiling within 48h |
| `flight_hours` | 28-day block hours reach 90% of the 100h RULE-FLT-03 ceiling |
| `fdp_margin` | A planned duty sits within 1h of its RULE-FDP-01 limit |
| `reserve_coverage` | Fewer than the needed reserves actually cover a base × rank × report time |
| `rotation_fragility` | A tail's turn time between two legs drops to 1h or under |
| `high_risk_thin_cover` | A high-risk crew member is rostered where legal cover would be scarce/expensive if they dropped out |
| `flagged_roster_exception` | The dataset's own flagged illegal assignment (scenario S5) |

---

## 5. The routing decision tree

Five decision points, evaluated in order, before a single tool ever runs. The first
two decide *who* picks the intent — the deterministic router or the model. The last
three decide whether the system is confident enough to act on it at all. Every one of
them is a plain `if`, not a model call — `app/agent/plans.py:route()` and
`app/agent/graph.py:route_decision()`.

```mermaid
flowchart TD
    router["PATTERN ROUTER<br/>scores every rule → argmax intent + confidence"]
    d1{"confidence < 0.35?<br/>router too unsure"}
    llmalone["LLM DECIDES ALONE<br/>forced override"]
    d2{"model disagrees,<br/>confidence ≥ router + 0.15?"}
    adopt["ADOPT THE LLM'S INTENT<br/>source = llm"]
    keep["KEEP THE ROUTER'S INTENT"]
    chosen["CHOSEN INTENT<br/>name · tier · confidence · source"]
    d3{"unsupported, or no<br/>compiled plan exists?"}
    abstain["ABSTAIN<br/>names what it CAN answer instead"]
    d4{"policy question, or a<br/>compound disruption?"}
    clarify1["CLARIFY<br/>names the judgement / splits the question"]
    d5{"a required entity is<br/>missing or unresolved?"}
    clarify2["CLARIFY<br/>asks for the missing crew id, date, station"]
    plan["PLAN → EXECUTE → … (§1)"]

    router --> d1
    d1 -- yes --> llmalone --> chosen
    d1 -- no --> d2
    d2 -- yes --> adopt --> chosen
    d2 -- no --> keep --> chosen
    chosen --> d3
    d3 -- yes --> abstain
    d3 -- no --> d4
    d4 -- yes --> clarify1
    d4 -- no --> d5
    d5 -- yes --> clarify2
    d5 -- no --> plan
```

Two guard patterns feed decision 4: `POLICY_RE` catches phrasings like "should we
pre-emptively swap him out" — every input is computable, the threshold isn't in the
ruleset. `COMPOUND_EVENT_RE` catches two disruption verbs joined by "and" — answering
one half confidently is the failure mode this system exists to avoid. Both are
asserted in both directions in `tests/test_routing_and_honesty.py`: they must fire on
these shapes, and they must *not* fire on any of the 38 graded questions.

---

## 6. Tools & scheduled jobs

33 tools the agent can call — every one typed, traced, and side-effect-free — plus
`list_supported_capabilities`, the meta tool that powers honest abstention (decision
3 above). And 3 background jobs that keep the console honest between questions.

| Category | Tools |
|---|---|
| **Retrieval — 14** | `get_crew` · `search_crew` · `get_flight` · `search_flights` · `get_pairing` · `get_roster_for_crew` · `get_duty_clock` · `get_certifications` · `get_reserves` · `get_risk_signal` · `get_rule` · `get_costs` · `network_summary` · `duty_window_scan` |
| **Legality — 4** | `compute_duty_period` · `check_legality` · `check_rest` · `simulate_duty_window` — every one runs the same seven-rule engine as §2; a lookup never re-derives a verdict a different way |
| **Simulation — 6** | `simulate_crew_unavailable` · `simulate_station_closure` · `simulate_delay` · `propagate_rotation` · `simulate_assignment` · `simulate_cancellation` — each forks the world via `World.apply(event)`, so a second event can chain onto the result of the first |
| **Recommendation — 8** | `enumerate_cover_candidates` · `resolve_disruption` · `resolve_delay_breach` · `solve_joint_assignment` · `estimate_cost` · `score_impact` · `draft_notification` · `morning_briefing` |

| Cron job | Cadence | What it does |
|---|---|---|
| `sweep_alerts` | every 300s (virtual clock) | Runs all 9 watchers, upserts the alert board by stable id so an acknowledgement survives the next sweep, auto-resolves anything that no longer fires |
| `nightly_eval` | every 6h | Re-runs the engine conformance suite and records the score — a regression shows up on the scorecard before a person asks |
| `prune_traces` | every 12h | Keeps the last 500 runs; older traces/spans/facts/rule evaluations are dropped |

---

## 7. What makes "reliable" checkable, not asserted

| Mechanism | What it does | Where |
|---|---|---|
| Import-graph test | Walks every module under `app/core` and fails if it imports FastAPI, SQLAlchemy, LangGraph, Anthropic, or any layer above it | `tests/test_core_purity.py` |
| Narration verifier | Extracts every number, crew id, flight id, pairing id and rule name from the model's draft and checks each against the run's fact ledger before the answer ships | `app/agent/verify.py` |
| Honesty guards | A policy question and a compound disruption both route to a clarification instead of a confident half-answer — tested in both directions so a guard tight enough to catch them can't also refuse a real question | `tests/test_routing_and_honesty.py` |
| Deterministic replay | Every tool call is hashed on input and output; `/api/runs/{id}/replay` re-executes the same call against the same snapshot and diffs the hashes | `app/api/routes/observability.py` |

| Check | Result |
|---|---|
| Engine conformance | 46 / 46 — 38 questions (16/14/8 per tier), 6 worked scenarios, 2 held-out used once. `app.core` directly, no model, ~60ms total |
| Live-agent conformance | 36 / 38 (94.7%) sending each question's own English through the real agent, model included, ~2 min wall time. The 2 remaining are genuine model-classification variance on one borderline question — reported honestly rather than chased to a false 100% |
| Automated test suite | 117 tests passing in ~2 seconds |
| Live scorecard | Re-run on demand from the console (`/eval`), both suites above, against the same answer keys, on stage |

---

*Crew Ops Advisor · dCortex Air, hub BLR, week of 2026-09-14 · figures measured against
the shipped dataset and this repository's own test suite.*
