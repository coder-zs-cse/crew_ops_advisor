# Crew Ops Advisor — Architecture & Build Plan

> dCortex hackathon · Carrier: dCortex Air · Hub BLR · Week 2026-09-14 → 2026-09-20
> Snapshot "now" = `2026-09-14T18:00:00Z` · All times UTC · Currency INR
> Stack: **React + FastAPI + PostgreSQL + LangGraph**

---

## Part 0 — Read of the problem (what actually wins)

### 0.1 The scoring gradient, decoded

The rubric is 20% AI Utilization + 15% Innovation + 15% Technical Excellence = **50% is
about the architectural boundary you drew**, not about feature count. Functionality is
only 15%. And the scoring principles are explicit:

> "Correctness outweighs coverage — answering ten questions correctly and saying
> 'I can't answer that reliably' on the eleventh scores higher than answering all
> eleven with three wrong."

So the strategy is: **a narrow, provably-correct deterministic core, an LLM confined to
language, and an observability layer that makes the correctness visible.** Everything we
build should serve one sentence in the demo: *"Every number on this screen came from
code, not from a model — and here is the receipt."*

### 0.2 The single most important discovery in the dataset

`generate.py` contains the resolver (`check_cover`, `cover_options`, lines 423–531) that
**produced every answer key**. The answer keys are not opinions — they are the output of
a specific 100-line algorithm. Our deterministic core must be a faithful re-implementation
of *that exact semantics*, including its quirks. Concretely:

| Semantic | Value / rule | Source |
|---|---|---|
| Report time | first departure − 60 min | `report_release()` |
| Release time | last arrival + 30 min | `report_release()` |
| FDP limit | `13.0 − 0.5 × max(0, sectors − 2)` | `fdp_limit()` |
| DUTY-02 window | 7 **calendar** days, inclusive of duty date; `daily_history` + planned roster duties, **minus** the excluded pairing's duties in-window, **plus** cover days with date ≤ d | `check_cover()` |
| REST-04 | ≥12h between consecutive `release → report` on a **merged sorted timeline** (roster + cover days) | `check_cover()` |
| Overlap | separate "double-booked" issue when `next.report < prev.release` | `check_cover()` |
| QUAL-05 | **short-circuits** — if no rating, that is the *only* reason returned | `check_cover()` |
| Reserve window | required **report** time (after any deadhead delay) must satisfy `start ≤ report ≤ end` on the report date | `cover_options()` |
| Deadhead | DEL→BLR only. Arrive 07:45Z on **even** dates (DX589), 08:45Z on **odd** (DX402). New report = arrival + 15 min. `delay_h = max(0, (arrival + 75min) − original_first_dep)` | `cover_options()` |
| Candidate pool | **all crew** with `rank == role` and `status == "active"`, excluding the sick crew — **not just reserves** | `cover_options()` |
| Cost | reserve → `reserve_callout_{pilot,cabin}`; non-reserve → `dayoff_callout_{pilot,cabin}`; + `deadhead_positioning` + `round(delay_h × delay_cost_per_duty_hour)` | `cover_options()` |
| Ranking | `sort by (cost_inr, crew_id)` ascending, then **append cancel option last**, then `rank = index + 1` | `cover_options()` |
| Cancel cost | `250000 × total legs across all pairing days` | `cover_options()` |

**Two traps most teams will fall into:**

1. **Only searching the reserve pool.** The answer keys are dominated by
   *day-off callouts* of ordinary line crew (₹24,000 pilot / ₹12,500 cabin). S1 ranks 2–5
   and S2 ranks 2–4 are all day-off callouts. A reserve-only search produces a short,
   wrong option list.
2. **Enforcing RULE-FLT-03 as a hard gate.** `check_cover()` lists `RULE-FLT-03` in
   `rules_checked` but **never actually evaluates it**. If we enforce it strictly we may
   exclude a candidate the answer key includes. Plan: implement it, run it as an
   **advisory** verdict, and let the conformance harness tell us whether hard enforcement
   diverges. Document it as a known ruleset discrepancy — exactly the "honest failure
   analysis" the brief rewards.

### 0.3 The explainability asset hiding in plain sight

Every answer key carries `excluded_candidates` with a reason string per crew:

```
"C-2087": "RULE-DUTY-02: would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)"
"C-3305": "reserve on-call window 00:00-05:30Z does not cover required report 06:00Z"
"C-2091": "RULE-QUAL-05: no A320 rating"
"C-5837": "RULE-REST-04: only 10.75h rest before P-2204 on 2026-09-17 (downstream conflict)"
```

Most teams will render the ranked options. **We render the rejections too.** For S2 the real
numbers are: 25 active captains, minus the sick one = **24 evaluated → 5 legal, 19 excluded**
(9 × REST-04, 8 × QUAL-05, 1 × DUTY-02, 1 × on-call window). We show that as a filterable
table of *why*, each row citing a rule and showing the arithmetic. That is the difference
between "a chatbot that answered" and "a decision aid a controller can challenge."

### 0.4 The boundary (the answer to the brief's central question)

> "What should the language model do, what should deterministic code do?"

**The LLM does four things and nothing else:**
1. Classify intent + tier from natural language.
2. Resolve fuzzy references to canonical IDs (**proposes**; code **validates** against DB).
3. Select/parameterise a tool plan — and only for queries outside the compiled-plan library.
4. Narrate a structured result into controller-readable prose.

**Deterministic code owns:** every arithmetic operation, every legality verdict, every
cost, every ranking, every entity existence claim, every date/time computation.

**Enforced, not just promised.** A `NumericProvenanceCheck` runs after narration: every
number, crew ID, flight ID and rule ID in the prose must appear in the run's append-only
**fact ledger**. Fail → one repair pass → fail again → we serve the structured answer with
"I produced an explanation I could not verify against my own computations." The model is
*structurally incapable* of shipping an unverified number.

---

## Part 1 — Tier-by-tier attack plan

### Tier 1 — Lookup & Retrieval (16 questions, mandatory)

Nothing here needs an LLM beyond intent + slots. Route to a **compiled plan**: a fixed
tool sequence per intent, zero LLM planning, sub-second.

| Question | Tool | Notes |
|---|---|---|
| Q01 reserves at base/date + windows | `get_reserves` | join reserve_pool → crew for rank |
| Q02 duty hours + headroom | `get_duty_clock` | must return **headroom** = 60 − 7d, cite RULE-DUTY-02 |
| Q03 / Q09 flights by station / route / date | `search_flights` | |
| Q04 certs expiring in 30d | `get_certifications(expiring_within_days)` | `as_of` matters |
| Q05 aircraft + seats for a flight | `get_flight` | |
| Q06 reserve window + reachability | `get_reserves` + `get_crew` | two-tool compose |
| Q07 base + ratings | `get_crew` | |
| Q08 pairing crew + roles | `get_pairing` | |
| Q10 flight count on date | `network_summary` | |
| Q11 captains at DEL | `search_crew(rank, base)` | |
| Q12 longest block time | `network_summary` | must return **all** ties |
| Q13 rank + 28d flight hours | `get_crew` + `get_duty_clock` | |
| Q14 nonstop destinations from BLR | `network_summary` | |
| Q15 SCC on a tail's pairing on a date | `get_pairing(tail, date)` | |
| Q16 risk score + drivers | `get_risk_signal` | |

**Gotchas:** Q12 needs tie handling; Q02 needs the *headroom framing*, not just the number;
Q04/Q26 are date-window arithmetic that must use calendar-day semantics.

### Tier 2 — Consequence & Simulation (14 questions, strongly expected)

Each maps to a **simulation primitive**, not to a generic RAG hop.

| Q | Primitive | Deterministic output |
|---|---|---|
| Q17 | `simulate_crew_unavailable` | uncovered day-1 legs, day-2 at-risk legs, pax 486 |
| Q18, Q28 | `check_legality(crew, cover_spec)` | per-rule verdicts + exact breach magnitude |
| Q19, Q29 | `simulate_station_closure` | affected set, per-flight min delay, FDP after delay vs limit |
| Q20 | `simulate_delay(tail, date, hours)` | FDP 12.75 vs limit 12.0 → breach |
| Q21 | `simulate_assignment` + `positioning` | legal via deadhead; ~3h delay to DX412 |
| Q22 | `check_legality` → CERT-06 | cert expired 17 Sep, duty 19 Sep |
| Q23 | `earliest_next_report(release)` | release + 12h |
| Q24 | `check_legality` over **both** pairing days | day 1 fits; day 2 breaches DUTY-02 by 8h15m (total 68.25h) — a candidate must be legal on *every* day of the cover |
| Q25 | `simulate_cancellation` | pax + ₹250,000 |
| Q26 | `duty_window_scan(date, threshold)` | includes *planned* duty that day → only C-2087 (51.83h) and C-3305 (50.0h) |
| Q27 | `enumerate_cover_candidates` (window + qual filter) | which reserve windows cover the callout |
| Q30 | `network_summary` | max-seats leg |

**Design principle:** every Tier-2 answer is an object with `{facts, rule_evaluations,
arithmetic_trace}`. The prose is generated *from* that object, never alongside it.

### Tier 3 — Recommendation & Action (8 questions, stretch — where we win)

| Q | Engine |
|---|---|
| Q31 | `enumerate_cover_candidates` + `rank_options` → the S2 flagship |
| Q32 | `solve_joint_assignment` — min total cost, no double-booking (S6) |
| Q33 | delay → FDP breach → partial re-crew vs cancel (S4). Note the remedy needs a **full reserve set** (CPT + FO + SCC + 3 CC = ₹75,000), not one pilot — so `enumerate_cover_candidates` must support a *complement* request, not just a single role |
| Q34 | cert lapse → cabin-crew cover enumeration (S5) |
| Q35 | closure → per-pairing recovery plan across 13 affected flights (S3) |
| Q36 | `draft_notification` — LLM prose, deterministic slots |
| Q37 | cheapest legal FO cover, VT-DXF, 20 Sep, callout 03:30Z |
| Q38 | morning briefing — 3 data points per aircraft line, justified |

**Ranking:** we expose **two** rankings and are explicit about it.
- `cost_rank` — `(cost_inr, crew_id)`, authoritative, matches the answer keys exactly.
- `ops_rank` — our opinionated score: cost, delay hours, reachability minutes, duty
  headroom remaining after the assignment, disruption-risk score, seniority. Shown as a
  secondary column with a "why this differs" explanation.

Showing both, and saying which one is graded, is more credible than silently inventing a
heuristic.

---

## Part 2 — System design

### 2.1 Layer diagram (the boundary is the deliverable)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  React Ops Console   chat · workbench · timeline · trace · eval scorecard │
└───────────────┬──────────────────────────────┬───────────────────────────┘
                │ REST + SSE                   │ SSE trace stream
┌───────────────▼──────────────────────────────▼───────────────────────────┐
│  FastAPI       /api/chat  /api/simulate/*  /api/recommend/*  /api/runs/*  │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼───────────────────┐   ═══ THE BOUNDARY ═══
│  LangGraph Agent  (LANGUAGE ONLY) │   above: probabilistic
│  classify · resolve · plan ·      │   below: deterministic
│  execute · verify · narrate       │
└───────────────┬───────────────────┘
                │ typed tool calls, JSON in / JSON out
┌───────────────▼──────────────────────────────────────────────────────────┐
│  crewops.tools    30 typed, side-effect-free tools → ToolResult+facts     │
├──────────────────────────────────────────────────────────────────────────┤
│  crewops.core     PURE PYTHON · no LLM · no DB · no framework imports     │
│  rules/ (7 rules) · duty · windows · candidates · costing · ranking ·     │
│  impact · rotation · closure · joint · positioning · notification         │
├──────────────────────────────────────────────────────────────────────────┤
│  crewops.repo     SQLAlchemy repositories → domain dataclasses            │
├──────────────────────────────────────────────────────────────────────────┤
│  PostgreSQL       world snapshot + derived timelines + trace store        │
└──────────────────────────────────────────────────────────────────────────┘
        ▲                                     ▲
   APScheduler jobs                     Observability sink
   (alerts, briefings, MV refresh)      (spans, ledger, rule evals)
```

**Enforcement of the boundary is mechanical, not cultural:** `crewops/core/` has a unit
test that asserts its import graph contains no `fastapi`, `sqlalchemy`, `langchain`,
`langgraph`, `openai` or `anthropic`. If someone reaches across the line, CI fails.

### 2.2 Clean-architecture patterns we are deliberately using

| Pattern | Where | Why it earns marks |
|---|---|---|
| **Hexagonal / ports & adapters** | `core` ↔ `repo` ↔ `api` | The core is testable with plain dicts; the answer-key harness runs with no DB and no network. |
| **Immutable world + event overlay + fork** | `World.apply(event) -> World'` | Scenarios never mutate truth; chained disruptions are just repeated forks. Demo line: "we fork the world, we never edit it." |
| **Strategy per rule** | `rules/RULE_FDP_01.py` etc., one class each, `evaluate(ctx) -> RuleVerdict` | Rules are swappable, individually unit-tested, and each returns its own arithmetic trace. New regulator = new folder. |
| **Specification objects** | `CandidateFilter`, `DutySpec`, `CoverRequest` | Enumeration logic reads like the rulebook. |
| **Result object, never exceptions for business outcomes** | `RuleVerdict`, `ToolResult`, `Either[Answer, Abstention]` | "Illegal" is data, not a crash; abstention is a first-class return. |
| **Append-only fact ledger** | per agent run | Makes provenance checkable and the UI citable. |
| **Compiled plan library + LLM fallback** | agent planner | Known intents cost 1 LLM call; novel ones cost 3. Latency and correctness both improve. |
| **CQRS-lite** | read repos vs `decisions`/`alerts` write models | The operational world is read-only; only decisions and traces are written. |
| **Materialised timeline view** | `crew_duty_timeline` | One derived object that DUTY-02, REST-04 and overlap checks all read. Single source of truth for time math. |
| **Deterministic replay** | span input/output hashes | Any run can be re-executed and diffed. |

---

## Part 3 — Database models (PostgreSQL)

### 3.1 World tables (read-only after ETL)

| Table | Columns (key ones) |
|---|---|
| `stations` | `code` PK, `name` |
| `aircraft` | `tail` PK, `aircraft_type`, `seats` |
| `flights` | `flight_id` PK, `flight_no`, `date`, `dep_station`, `arr_station`, `dep_utc`, `arr_utc`, `block_hours`, `tail`, `aircraft_type`, `seats` |
| `crew` | `crew_id` PK, `name`, `rank`, `base`, `seniority`, `reachability_minutes`, `status` |
| `crew_ratings` | `(crew_id, aircraft_type)` PK — normalised from the `ratings` array |
| `pairings` | `pairing_id` PK, `tail` |
| `pairing_days` | `id` PK, `pairing_id`, `day_index`, `date`, `report_utc`, `release_utc`, `sectors`, `duty_hours`, `flight_hours` |
| `pairing_day_flights` | `(pairing_day_id, flight_id)`, `leg_seq` |
| `pairing_crew` | `(pairing_id, crew_id)`, `role` |
| `duty_clock_daily` | `(crew_id, date)` PK, `duty_hours`, `flight_hours` — the 28-day history |
| `duty_clock_summary` | `crew_id` PK, `as_of_utc`, `duty_hours_7d`, `flight_hours_28d`, `last_rest_ended` |
| `reserve_assignments` | `(crew_id, date)` PK, `base`, `oncall_start`, `oncall_end` |
| `certifications` | `id` PK, `crew_id`, `cert_type`, `valid_from`, `valid_to` |
| `rules` | `rule_id` PK, `text`, `params` jsonb |
| `cost_rates` | `key` PK, `value`, `currency` |
| `risk_signals` | `crew_id` PK, `as_of_utc`, `score`, `drivers` jsonb |
| `positioning_options` | `id`, `from_station`, `to_station`, `flight_no`, `arr_utc_time`, `date_parity` — the deadhead table, extracted from hardcode into data |

Indexes: `flights(date, dep_station)`, `flights(flight_no, date)`, `flights(tail, dep_utc)`,
`pairing_days(date)`, `pairing_crew(crew_id)`, `duty_clock_daily(crew_id, date)`,
`certifications(crew_id, valid_to)`.

### 3.2 Derived / materialised

- **`crew_duty_timeline`** (MV) — `crew_id, date, source ∈ {history, roster}, report_utc,
  release_utc, duty_hours, flight_hours, pairing_id`. The unified timeline every temporal
  rule reads. Rebuilt by a scheduler job.
- **`mv_duty_window`** — `crew_id, date, duty_hours_7d, flight_hours_28d` precomputed rolling
  sums for instant headroom queries and the "who is near a limit" scan (Q26).
- **`mv_pairing_fdp`** — `pairing_day_id, sectors, fdp_hours, fdp_limit, margin_hours` for
  the fragility watcher.
- **`mv_flight_pax`** — seats per leg, for impact totals.

### 3.3 Agent / ops tables (write side)

| Table | Purpose |
|---|---|
| `conversations` | `id`, `title`, `created_at` |
| `messages` | `id`, `conversation_id`, `role`, `content`, `answer_json`, `run_id` |
| `agent_runs` | `run_id`, `conversation_id`, `intent`, `tier`, `status`, `latency_ms`, `model`, `tokens_in/out`, `cost_usd`, `abstained`, `verification_passed`, `plan_source ∈ {compiled, llm}` |
| `agent_spans` | `span_id`, `run_id`, `parent_span_id`, `name`, `type ∈ {node,llm,tool,sql,rule,sim,verify}`, `started_at`, `ended_at`, `duration_ms`, `input` jsonb, `output` jsonb, `input_hash`, `output_hash`, `status`, `error` |
| `fact_ledger` | `fact_id`, `run_id`, `key`, `value`, `unit`, `source_span_id`, `citation` |
| `rule_evaluations` | `id`, `run_id`, `subject_crew_id`, `rule_id`, `verdict`, `actual`, `limit_value`, `margin`, `arithmetic` jsonb, `message` |
| `decisions` | `id`, `run_id`, `option_json`, `chosen_by`, `chosen_at`, `status ∈ {proposed,applied,reverted}` |
| `notifications` | `id`, `decision_id`, `crew_id`, `channel`, `body`, `status` |
| `alerts` | `id`, `type`, `severity`, `entity_ref`, `detected_at`, `payload` jsonb, `state ∈ {open,ack,resolved}` |
| `scenario_forks` | `id`, `parent_fork_id`, `base_snapshot`, `events` jsonb — persisted world forks for chained disruptions |
| `eval_runs` / `eval_results` | conformance scorecard per question/scenario, with diffs |

---

## Part 4 — The deterministic core (`crewops.core`)

This is the moat. Build it first, test it against the answer keys before a single line of
agent code exists.

### 4.1 Modules

| Module | Responsibility |
|---|---|
| `timeutil.py` | UTC parse/format, `hrs()` rounding to 2dp matching the generator, calendar-day windows, even/odd date parity |
| `duty.py` | `duty_period(day)`, `sectors()`, `fdp_hours()`, `fdp_limit(sectors)` |
| `windows.py` | `duty_hours_in_window(crew, end_date, days, overlay)`, `flight_hours_in_window`, timeline merge (history + roster + simulated cover), exclusion of a replaced pairing |
| `rules/` | One class per rule, each returning `RuleVerdict{rule_id, passed, actual, limit, margin, message, arithmetic[]}` |
| `overlap.py` | Double-booking detection across the merged timeline |
| `positioning.py` | `positioning_options(from_base, to_station, date)` → arrival, new report, delay hours, cost. Table-driven so a second city pair is data, not code |
| `candidates.py` | `enumerate_cover(pairing_days, role, sick_crew, exclude_pairing, callout_utc)` → `CandidateSet{eligible[], excluded[]}` |
| `costing.py` | `cost_of(option)` with an itemised breakdown (`callout`, `positioning`, `delay`, `hotel`) |
| `ranking.py` | `cost_rank` (answer-key-aligned) and `ops_rank` (multi-factor + S/B/C impact score) |
| `impact.py` | Uncovered legs by day, pairing break, pax at risk, downstream at-risk legs |
| `rotation.py` | Tail rotation graph, turn times, delay propagation leg-by-leg |
| `closure.py` | Station closure affected set, min delay to reopen+30, FDP recheck, per-flight verdict |
| `joint.py` | Min-cost joint assignment across simultaneous openings (brute force ≤ small N, Hungarian fallback) |
| `notification.py` | Deterministic slot extraction for the callout message |
| `world.py` | `World` (immutable), `Event`, `World.apply(event) -> World` |

### 4.2 The seven rules — exact semantics to implement

| Rule | Inputs | Computation | Message form |
|---|---|---|---|
| **RULE-FDP-01** | pairing day, delay_h | `fdp = release+delay − (report+delay)`; `limit = 13 − 0.5·max(0, sectors−2)` | `FDP 12.75h > 12.0h limit (4 sectors)` |
| **RULE-DUTY-02** | crew, duty date, overlay | `Σ duty over [d−6, d]` from history + roster − excluded pairing + cover days ≤ d | `would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)` |
| **RULE-FLT-03** | crew, duty date | `Σ block over [d−27, d]` vs 100h | **advisory** (see §0.2 trap 2) |
| **RULE-REST-04** | merged sorted timeline | for each consecutive pair, `rest = next.report − prev.release ≥ 12h`; tag `downstream` when the *later* duty is pre-existing and the earlier is the cover | `only 10.75h rest before P-2204 on 2026-09-17 (downstream conflict)` |
| **RULE-QUAL-05** | crew ratings, flight aircraft_type | membership; **short-circuits all other checks** | `no A320 rating` |
| **RULE-CERT-06** | 4 cert types, duty date | every cert must satisfy `valid_from ≤ date ≤ valid_to` | `certification invalid on 2026-09-19` |
| **RULE-BASE-07** | crew base vs departure station | same base → free; else require a positioning option, else exclude | `no same-day positioning flight from base` |

Plus the non-rule gates that behave like rules and must be reported as such:
- **Reserve on-call window** — `start ≤ required_report ≤ end`, evaluated *after* deadhead delay.
- **Double-booking** — overlap of duty periods.
- **Status** — `status != "active"` (leave/training) excludes silently from the pool.

### 4.3 Test strategy (build the harness before the engine)

```
tests/
  unit/            per-rule tables, boundary cases (exactly 12.0h rest, exactly 60.0h)
  conformance/
    test_questions.py   parametrised over all 38 questions.json entries
    test_scenarios.py   parametrised over all 6 scenarios.json answer keys
    test_holdout.py     internal/held_out_scenarios.json — run ONCE, at the end
    matchers.py         set-equality for flight lists, exact for cost/rank,
                        rule-id + magnitude match for exclusion reasons
  invariants/      import-graph purity, ETL round-trip vs validate.py
```

Target: **38/38 questions and 6/6 scenarios green** before the agent exists. The scorecard
is then a live product surface (see §8.7), not a test artifact.

---

## Part 5 — Tool layer (the agent's toolbelt)

30 tools, each: typed Pydantic in/out, side-effect-free, decorated with `@traced_tool`,
returning `ToolResult{data, facts[], citations[], arithmetic[], span_id}`.

### Retrieval (Tier 1)
1. `get_crew(crew_id | name)`
2. `search_crew(rank?, base?, rating?, status?, seniority_range?)`
3. `get_flight(flight_id | flight_no + date)`
4. `search_flights(date?, dep?, arr?, tail?, time_range?)`
5. `get_pairing(pairing_id | crew_id + date | tail + date)`
6. `get_roster_for_crew(crew_id, date_range)`
7. `get_duty_clock(crew_id, as_of_date)` → 7d/28d + **headroom** under DUTY-02 and FLT-03
8. `get_certifications(crew_id?, expiring_within_days?, as_of)`
9. `get_reserves(base?, date, covering_report_time?)`
10. `get_risk_signal(crew_id? | top_n)`
11. `get_rule(rule_id?)` — grounds every citation in real rule text
12. `get_costs()`
13. `network_summary(date?)` — counts, stations served, longest block (with ties), max-seat leg

### Legality & computation (Tier 2)
14. `compute_duty_period(pairing_id, day_index, delay_hours=0)`
15. `check_legality(crew_id, duty_spec, exclude_pairing?, delay_hours=0)` → all 7 verdicts
16. `check_rest(release_utc, next_report_utc)`
17. `simulate_duty_window(crew_id, date, added_duty_hours)` → 7d/28d before/after
18. `duty_window_scan(date, threshold_hours, include_planned=True)` → Q26
19. `explain_rule_arithmetic(rule_id, inputs)` → the formula trace for a citation popover

### Simulation (Tier 2)
20. `simulate_crew_unavailable(crew_id, from_utc, pairing_id?)`
21. `simulate_station_closure(station, start_utc, end_utc)`
22. `simulate_delay(tail, date, delay_hours)`
23. `propagate_rotation(tail, date, from_flight, delay_hours)` — leg-by-leg cascade
24. `simulate_assignment(crew_id, pairing_id, day_indexes?)` — the "if I move X onto Y" what-if
25. `simulate_cancellation(flight_ids)`

### Recommendation (Tier 3)
26. `enumerate_cover_candidates(pairing_id, role | complement[], sick_crew_id, callout_utc, day_indexes?)` → **the flagship**; returns `eligible[]` + `excluded[]` with reasons. Must support a *partial-day* cover (S4's tail-leg re-crew) and a *full complement* request (2 pilots + 4 cabin), not only a single role for a whole pairing
27. `rank_options(options, weights?)` → `cost_rank` + `ops_rank` + S/B/C impact score
28. `solve_joint_assignment(openings[])` → min total cost, no double-booking
29. `estimate_cost(action_spec)` → itemised
30. `draft_notification(crew_id, assignment_spec, channel)` → deterministic slots + LLM prose

### Meta
- `list_supported_capabilities()` — powers honest abstention
- `validate_answer(narration, fact_ledger)` — the provenance guard

---

## Part 6 — LangGraph agent design

### 6.1 State

```python
class AdvisorState(TypedDict):
    run_id: str
    conversation_id: str
    user_message: str
    history: list[Message]
    intent: Intent | None          # {name, tier, confidence}
    entities: ResolvedEntities     # validated against DB, never LLM-asserted
    plan: ToolPlan                 # compiled or LLM-generated
    tool_results: list[ToolResult]
    fact_ledger: list[Fact]        # append-only, provenance-tagged
    rule_evaluations: list[RuleVerdict]
    structured_answer: dict | None # tier-specific schema
    narration: str | None
    verification: VerificationReport | None
    abstention: Abstention | None
    repair_attempts: int
```

### 6.2 Graph

```
        ┌──────────┐
        │  ingest  │  normalise, load conversation context, start run span
        └────┬─────┘
             ▼
     ┌───────────────┐   LLM #1 — structured output
     │classify_intent│   → {intent, tier, confidence, missing_slots}
     └───────┬───────┘
             ▼
     ┌────────────────┐  LLM proposes ids; DETERMINISTIC resolver validates
     │resolve_entities│  fuzzy name → crew_id, "DX412 tomorrow" → flight_id
     └───────┬────────┘
             ▼
       ╔═════════════╗
       ║   router    ║──unsupported / unresolved / low-confidence──┐
       ╚══════╤══════╝                                              ▼
              │                                              ┌────────────┐
   ┌──────────┼──────────┐                                   │  abstain   │
   ▼          ▼          ▼                                   └──────┬─────┘
┌──────┐ ┌─────────┐ ┌────────────┐                                 │
│tier1 │ │ tier2   │ │  tier3     │  subgraphs                      │
│lookup│ │disrupt  │ │recommend   │                                 │
└──┬───┘ └────┬────┘ └─────┬──────┘                                 │
   └──────────┼────────────┘                                        │
              ▼                                                     │
     ┌─────────────────┐  compiled plan (known intent) OR            │
     │      plan       │  LLM #2 plan synthesis (novel query)        │
     └────────┬────────┘                                             │
              ▼                                                      │
     ┌─────────────────┐  parallel where independent; every call     │
     │  execute_tools  │  emits a span + facts into the ledger       │
     └────────┬────────┘                                             │
              ▼                                                      │
     ┌─────────────────┐  DETERMINISTIC — assembles the tier schema  │
     │ compose_answer  │  from tool results only                     │
     └────────┬────────┘                                             │
              ▼                                                      │
     ┌─────────────────┐  LLM #3 — prose, constrained to the ledger  │
     │    narrate      │                                             │
     └────────┬────────┘                                             │
              ▼                                                      │
     ┌─────────────────┐  numeric provenance · entity existence ·    │
     │     verify      │  rule citation · schema · contradiction     │
     └────┬───────┬────┘                                             │
     pass │       │ fail (≤1 repair)                                 │
          │       └────────► repair ──► narrate                      │
          ▼                                                          │
     ┌─────────────────┐◄─────────────────────────────────────────────┘
     │     persist     │  answer + trace + ledger + rule evals + metrics
     └─────────────────┘
```

### 6.3 Why this shape

- **Compiled plans for known intents.** The 38 question shapes and 6 scenario types have
  fixed tool sequences. `plan_source = "compiled"` means one LLM call for classification,
  one for narration — typically **1.5–3 s end to end**, well inside the "45 s is not a
  decision aid" bar. LLM planning is the fallback, not the default.
- **Entity resolution is validate-not-trust.** The LLM may propose `C-1042` from
  "Captain Nair"; the resolver hits the DB. Ambiguity (two Nairs) → clarification question,
  not a guess.
- **`compose_answer` is deterministic.** The tier-2/tier-3 JSON is assembled by code from
  tool results. The LLM never authors the structured payload — only the prose beside it.
- **Verify is a real gate.** Two failures = we downgrade to structured-only and say so.
- **Abstention is a node, not an exception.** It returns *what it would need*:
  "I can answer duty-limit questions for a named crew and date. I don't model passenger
  rebooking or hotel allocation."

### 6.4 Subgraph: disruption (Tier 2 → 3)

```
normalize_event → impact_analysis → candidate_enumeration → legality_sweep
   → cost_model → ranking → downstream_simulation → (joint_solver if multi-event)
```

Every step is a deterministic tool. The subgraph is reused verbatim by the REST simulation
endpoints, so the chat and the workbench cannot disagree.

### 6.5 Guardrails

| Guard | Mechanism |
|---|---|
| No invented numbers | fact-ledger provenance check on narration |
| No invented entities | every `C-####` / `DX###` / `P-####` must resolve in DB **and** appear in the ledger |
| No uncited rule claims | every `RULE-*` mentioned must have a `rule_evaluations` row for this run |
| No silent scope creep | intent allowlist per tier; tools outside the intent's toolset are not bound |
| No stale confidence | tool results carry `as_of`; answers state the snapshot date |
| Write safety | `READ` free · `WRITE` (assign/apply) inline confirm · `CRITICAL` (cancel flight) explicit modal + logged decision |

---

## Part 7 — Observability & tracing layer

This is what convinces judges. It must be a **product surface**, not a log file.

### 7.1 Instrumentation

- A `Tracer` context manager emits OpenTelemetry-shaped spans with `run_id`,
  `parent_span_id`, `type`, `attrs`, `input`, `output`, `duration_ms`.
- `@traced_tool` decorator wraps every tool: records args, result summary, facts emitted,
  and `input_hash`/`output_hash` for replay diffing.
- LangGraph node callbacks emit `node` spans; the LLM client emits `llm` spans with prompt,
  completion, model, token counts and cost.
- Every `RuleVerdict` emits a `rule` span **and** a `rule_evaluations` row.

**Dual sink:** PostgreSQL (durable, queryable, the primary) + an in-process pub/sub bus
that streams the same spans to the browser over SSE while the answer is still composing.
Optional OTLP export to Langfuse/LangSmith — but the demo must never depend on a SaaS being
reachable from the venue wifi.

### 7.2 Span taxonomy

| Type | Example | Recorded |
|---|---|---|
| `node` | `classify_intent`, `verify` | state delta |
| `llm` | intent classification | prompt, completion, model, tokens, cost, latency |
| `tool` | `enumerate_cover_candidates` | args, result summary, facts emitted, row counts |
| `sql` | repository query | statement, params, rows, ms |
| `rule` | `RULE-DUTY-02 @ C-2087 @ 2026-09-15` | actual, limit, margin, arithmetic, verdict |
| `sim` | `fork(world, SICK_CREW)` | event, entities touched, fork id |
| `verify` | provenance check | checks run, violations, pass/fail |

### 7.3 What the UI shows (three surfaces)

**A. Live reasoning stream** (inside chat, collapsible)
```
▸ classify_intent            120 ms   intent=cover_recommendation tier=3 conf=0.94
▸ resolve_entities            18 ms   C-1042 ✓  P-2291 ✓  callout 2026-09-15T05:00Z
▸ plan (compiled)              2 ms   4 tools
  ▸ get_pairing                 6 ms   P-2291 · 2 days · 6 legs
  ▸ simulate_crew_unavailable  11 ms   6 legs uncovered · 486 pax day 1
  ▸ enumerate_cover_candidates 74 ms   24 evaluated → 5 legal · 19 excluded
      ▸ RULE-REST-04   ×9 excluded
      ▸ RULE-QUAL-05   ×8 excluded
      ▸ RULE-DUTY-02   ×1 excluded
      ▸ reserve window ×1 excluded
  ▸ rank_options                4 ms   cheapest ₹18,500 · C-3310
▸ narrate                     810 ms   142 tokens
▸ verify                       21 ms   5/5 checks pass · 11 facts cited
```

**B. Run inspector** (`/runs/:run_id`)
- Span **waterfall** (Gantt), coloured by type, click to expand raw I/O.
- **Fact ledger** table: `key · value · source tool · span link · citation`. Hovering a
  number in the answer highlights its ledger row.
- **Rule evaluation** table: `crew · rule · actual · limit · margin · verdict · arithmetic`.
- **LLM calls**: full prompt + completion + tokens + cost.
- **Verification report**: each check, violations found, repair attempts.
- **Replay & diff**: re-run the deterministic plan against the same snapshot; show a diff.
  Proves the non-LLM path is reproducible.
- **Download reasoning receipt** (JSON) — the whole trace, ledger and rule evals.

**C. Metrics dashboard** (`/observability`)
- p50/p95 latency per node and per tool.
- Tool-call frequency histogram; compiled-plan vs LLM-plan split.
- Verification pass rate, repair rate, abstention rate.
- Token spend and INR/USD cost per answer.
- Eval scorecard trend across the hackathon.

### 7.4 The demo line

> "Ask it anything, then open the receipt. Every active captain in the fleet was evaluated
> in 74 ms. Here is every one we rejected, which rule rejected them, and the arithmetic.
> The model wrote the paragraph. It did not compute a single number in it — and we check
> that automatically before you ever see it."

---

## Part 8 — Frontend (React + TypeScript + Vite + Tailwind)

Design takeaways from Velaire we adopt (and only these): **dark cockpit** (default view is
quiet; absence of alerts is the signal), **exception-based** (surface only what needs a
human), **auditable calm** (confidence and provenance always reachable, never shouted),
**action classification** (READ / WRITE / CRITICAL with escalating confirmation), and the
**canonical exception card** shape: grounded entities → state → constraint proof → simulated
fork. We build our own components; we take the information architecture, not the code.

Libraries: TanStack Query (server state), Zustand (light UI state), Recharts + custom SVG
(charts), framer-motion (restrained), lucide-react (icons), react-router.

### 8.1 Ops Console (home)
- **Alert stack** (left) — scheduler output, severity-ordered, each expandable into the
  canonical exception card with a one-click "Ask the Advisor about this".
- **Tail-line Gantt** (centre) — 6 tails × 7 days, pairings as blocks, legs as segments.
  Overlay closure windows, delays, uncovered legs. Click a block → pairing detail.
- **KPI rail** (right) — coverage %, reserves available by rank/base, crew within 5h of a
  duty limit, certs expiring ≤30d, high-risk crew rostered in 24h.
- **Virtual clock control** — the dataset's "now" is fixed at 2026-09-14T18:00Z; a scrubber
  advances the simulated clock so schedulers and alerts can be demoed live.

### 8.2 Advisor chat (primary surface, `Cmd+J`)
- Streaming narration + structured result cards below it.
- **Citation chips** — `RULE-DUTY-02` renders as a chip; click → popover with the rule text,
  params, and *this run's* arithmetic for that crew.
- **"Show reasoning"** drawer → the live trace stream (§7.3A).
- Multi-turn context retention; follow-ups like "what about the second option?" resolve
  against the previous run's structured answer.
- Abstention renders as a distinct card: "Outside what I can compute reliably" + what it
  *can* do.

### 8.3 Disruption Workbench (the Tier-2/3 showcase)
Reachable from an alert, a Gantt block, or the scenario picker (S1–S6 + custom).
- **Event form** — sick / closure / delay / cert lapse / cancellation / multi-sick.
- **Impact panel** — uncovered legs by day, pairing broken, pax at risk, downstream at-risk
  legs on a mini timeline, cascade tree.
- **Options table** — rank, action, cost (itemised on hover), delay hours, coverage,
  reachability, legality badge. Toggle `cost_rank` ↔ `ops_rank`.
- **Excluded candidates table** — the differentiator. Grouped by rule, filterable, each row
  showing the arithmetic. "33 excluded: 18 QUAL-05, 11 REST-04, 3 DUTY-02, 1 window."
- **Option detail** — rule-by-rule proof card + before/after 7-day duty bar chart.
- **Apply** → WRITE confirm → decision logged → notification draft opens.
- **Chain another event** → forks the world again; breadcrumb shows the fork lineage.

### 8.4 Crew detail
Profile, ratings, cert timeline with expiry markers, 28-day duty/flight bar chart with the
60h/100h limit lines and a draggable 7-day rolling-window highlighter, roster strip, risk
score with drivers, reachability.

### 8.5 Flight / pairing detail
Legs with times and block, crew complement by role, FDP vs limit gauge, pax, tail rotation
context (what flies before and after).

### 8.6 Trace inspector (`/runs/:id`)
As specified in §7.3B.

### 8.7 Eval scorecard (`/eval`) — highest leverage per hour spent
A live table of all **38 questions** and **6 scenarios** with pass/fail against the shipped
answer keys, per-tier accuracy, and a diff viewer for any failure. Run it on stage.

> "We didn't just build an advisor. We built the grader, and we run it against your own
> answer keys on every commit. Here is our score, live: 38/38 Tier 1–3 questions, 6/6
> scenarios, and here is the one case we get wrong and why."

### 8.8 Morning briefing (`/briefing`) — Q38
Per aircraft line: FDP margin on today's pairing, reserve depth covering today's report
times, and the nearest limit/cert cliff in the next 72h — each with a one-line justification.

### 8.9 Rules reference (`/rules`)
The 7 rules with live calculators (enter sectors → see the FDP limit; enter a release time →
see earliest next report). Doubles as the citation popover source.

### 8.10 Interaction bar
`Cmd+K` palette, `Cmd+J` chat, `Esc` overlays, keyboard-navigable tables, WCAG AA focus
rings, `prefers-reduced-motion` respected, dark theme with a light fallback.

---

## Part 9 — Visualisation inventory (build these, in this order)

| # | Visual | Answers | Effort |
|---|---|---|---|
| 1 | **Duty-budget bar** — used vs limit vs proposed addition, overflow in red labelled "1h20m over" | The single most important image in the product. Makes RULE-DUTY-02 obvious in one glance | S |
| 2 | **Reserve on-call ribbon** — 24h strip per reserve, window shaded, required report as a marker | Visually explains why C-3305 fails and C-3310 passes | S |
| 3 | **Tail-line Gantt** — 6 tails × 7 days | The operational picture; closure/delay overlays | M |
| 4 | **Impact cascade tree** — sick crew → pairing → legs → downstream legs, with pax counts | "Consequence blindness", the stated pain point | M |
| 5 | **Candidate scatter** — cost (x) vs delay (y), colour = legal, size = reachability | Makes the trade-off spatial | S |
| 6 | **28-day duty/flight bars** with limit lines + rolling-window highlighter | Crew detail; before/after ghost bars for what-ifs | M |
| 7 | **Rule proof card** — the arithmetic, laid out as a receipt | Explainability, everywhere | S |
| 8 | **Trace waterfall** — spans as a Gantt, coloured by type | Observability surface | M |
| 9 | **Coverage ring** — crewed vs uncrewed legs for the selected day | Ambient KPI | S |
| 10 | **Exclusion sunburst / grouped bar** — 33 excluded by rule | Shows the breadth of the search | S |

Charting rules: one shared palette, colour-blind safe, dark/light parity, every chart has a
plain-text equivalent in the DOM for accessibility and for the LLM to cite.

---

## Part 10 — Scheduler jobs (APScheduler, virtual-clock aware)

The dataset's "now" is frozen, so jobs run against a **virtual clock** the demo can advance.

| Job | Cadence | Emits |
|---|---|---|
| `refresh_timelines` | on clock advance / 5 min | rebuilds `crew_duty_timeline`, `mv_duty_window`, `mv_pairing_fdp` |
| `duty_limit_watch` | 15 min | alert when projected 7d duty ≥ 90% of 60h within 48h |
| `flight_hour_watch` | hourly | 28d block hours ≥ 90% of 100h |
| `cert_expiry_watch` | daily | certs expiring ≤30d **and** any cert expiring *before a rostered duty date* — this catches S5 proactively, before compliance does |
| `reserve_coverage_watch` | hourly | per base × rank × date: how many reserve windows cover each pairing's report time; alert below threshold |
| `fdp_margin_watch` | daily | pairings whose planned FDP is within 0.5h of the limit — fragile to any delay (this is what makes S4 predictable) |
| `rotation_fragility_watch` | daily | tails with turn buffers below threshold — cascade risk |
| `risk_signal_watch` | daily | high `disruption_risk_score` crew rostered in the next 24h **with thin cover** → suggest pre-emptive standby |
| `morning_briefing_job` | 04:00Z daily | generates the Q38 briefing and pins it |
| `eval_nightly` | nightly | runs the full conformance suite, writes the scorecard |

Proactive alerting is an explicit "optional enhancement" in the brief, and it converts the
product from reactive Q&A into a *system of action* — which is exactly the founder's framing
in the video.

---

## Part 11 — Backend API surface (FastAPI)

### Chat / agent
- `POST /api/chat` → `{answer, structured, run_id, verification, abstained}`
- `POST /api/chat/stream` → SSE: `node_start`, `node_end`, `tool_call`, `tool_result`,
  `fact`, `rule_verdict`, `token`, `verification`, `done`, `error`
- `GET /api/conversations` · `GET /api/conversations/{id}`
- `POST /api/runs/{run_id}/feedback`

### Deterministic reads (also proves the boundary — the UI can bypass the LLM entirely)
- `GET /api/crew` · `/api/crew/{id}` · `/api/crew/{id}/timeline` · `/api/crew/{id}/duty-clock?as_of=`
- `GET /api/flights` · `/api/flights/{id}`
- `GET /api/pairings` · `/api/pairings/{id}`
- `GET /api/reserves?base=&date=&report_time=`
- `GET /api/certifications/expiring?within_days=&as_of=`
- `GET /api/rules` · `/api/rules/{id}`
- `GET /api/costs` · `GET /api/risk?top=`
- `GET /api/network/summary?date=`

### Simulation
- `POST /api/simulate/sick` `{crew_id, pairing_id?, reported_utc}`
- `POST /api/simulate/station-closure` `{station, start_utc, end_utc}`
- `POST /api/simulate/delay` `{tail, date, delay_hours}`
- `POST /api/simulate/assignment` `{crew_id, pairing_id, day_indexes?}`
- `POST /api/simulate/cancellation` `{flight_ids[]}`
- `POST /api/simulate/chain` `{fork_id, event}` → chained disruption

### Recommendation
- `POST /api/recommend/cover` `{pairing_id, role, sick_crew_id, callout_utc}`
- `POST /api/recommend/joint` `{openings[]}`
- `POST /api/legality/check` `{crew_id, duty_spec, exclude_pairing?, delay_hours?}`

### Actions
- `POST /api/decisions` — apply an option (logs; mutates only a fork, never the base world)
- `POST /api/notifications/draft` · `POST /api/notifications/send` (simulated)

### Observability
- `GET /api/runs?limit=` · `GET /api/runs/{run_id}` (full trace tree)
- `GET /api/runs/{run_id}/spans` · `/facts` · `/rule-evaluations` · `/receipt` (download)
- `POST /api/runs/{run_id}/replay` → deterministic re-execution + diff
- `GET /api/metrics`

### Eval & scenarios
- `GET /api/scenarios` · `POST /api/scenarios/{id}/replay`
- `POST /api/eval/run?suite=questions|scenarios|holdout` · `GET /api/eval/latest`

### Alerts & briefing
- `GET /api/alerts` · `POST /api/alerts/{id}/ack` · `POST /api/alerts/{id}/resolve`
- `GET /api/briefing?date=`
- `GET /api/clock` · `POST /api/clock` (virtual clock control, demo only)

---

## Part 12 — Simulation scenario catalogue

### Provided (must pass)
| ID | Type | What it tests |
|---|---|---|
| S1 | `SICK_CREW` | ATR captain, clean reserve cover; QUAL-05 exclusions |
| S2 | `SICK_CREW` (2-day) | Flagship. Multi-day cover, DUTY-02 breach detection, deadhead costing |
| S3 | `STATION_CLOSURE` | 13 flights, per-flight min delay, FDP recheck after shift |
| S4 | `DELAY` | 90-min tech delay → FDP 12.75 vs 12.0 → partial re-crew vs cancel |
| S5 | `CERT_EXPIRY` | CERT-06, cabin-crew cover pool |
| S6 | `MULTI_SICK` | Joint assignment, scarce reserve, no double-booking |
| H1/H2 | held out | Generalisation — run **once** at the end, report honestly |

### Ours (generalisation demos)
| Type | Why |
|---|---|
| `SICK_CREW` for any role × any pairing × any callout time | Proves it is an engine, not six hardcoded answers |
| `STATION_CLOSURE` for any of the 8 stations × any window | Same |
| `CHAINED` — apply an option, then hit the new world with a second event | Explicit bonus in the brief; showcases the fork model |
| `RESERVE_DEPLETION` — what if we call out three reserves this morning? | Shows scarcity reasoning |
| `ROLLING_WEATHER` — closure + downstream delay together | Compound disruption |
| `CANCELLATION` — pax and cost of dropping a leg | Tier-2 Q25 generalised |

Every scenario is `World.apply(Event) -> World'`. Chaining is fork-of-fork. The base
snapshot is never mutated.

---

## Part 13 — Honest limitations (draft the README section now, not at hour 23)

1. **RULE-FLT-03 is advisory.** The dataset's own generator lists it in `rules_checked` but
   never evaluates it. Enforcing it strictly could contradict the shipped answer keys. We
   compute it, display it, and flag the discrepancy rather than silently pick a side.
2. **Deadhead positioning is DEL→BLR only.** That is all the data supports. Other base pairs
   return `RULE-BASE-07: no same-day positioning flight from base` — same as the answer keys.
3. **Station-closure delay model is single-shift.** The keys shift one leg to reopen+30 min.
   Our `propagate_rotation` produces a truer cascade; we show the key-aligned number as
   authoritative and the cascade as additional analysis, clearly labelled.
4. **Cost model omits hotel_overnight** for multi-day covers — as do the answer keys.
5. **Rank ties are broken by `crew_id`**, which is arbitrary. `ops_rank` exists precisely
   because cost-only ranking is not how a real desk decides.
6. **Passenger impact is seat count, not booked load.** No booking data exists.
7. **Pax rebooking, hotel allocation and payroll are out of scope** — the abstention node
   says so by name.
8. **Ambiguous entity references trigger a clarification**, not a guess. This will
   occasionally feel pedantic; it is the correct trade under the scoring principles.
9. **The failure case we will present** (deliverable #6): a compound query that mixes a
   what-if with a policy judgement — e.g. "should we pre-emptively swap C-1042 out of
   tomorrow given his 0.78 risk score?" The system can compute every input but the decision
   is a policy call the ruleset does not encode; it abstains with a structured brief instead
   of inventing a threshold. We will show the trace and explain why abstaining is right.

**PII note for Technical Excellence credit:** in production, crew identity would be a
tokenised reference; names, phone numbers and medical certificate *reasons* would live
behind a separate service with field-level encryption and purpose-bound access. The rules
engine only ever needs `crew_id`, rank, base, ratings, cert *validity dates* (never the
medical detail) and duty numbers — so the legality core can run entirely on pseudonymised
data, with re-identification confined to the notification adapter and gated by audit.

---

## Part 14 — Build order (24 hours, 4 people)

| Phase | Hours | Deliverable |
|---|---|---|
| **P0 Foundations** | 0–2 | Repo skeleton, docker-compose (Postgres), ETL from `data/*.json`, `validate.py` passing on our export, **conformance harness scaffold loaded with all 38 Q + 6 S (all failing)** |
| **P1 Core, Tier 1** | 2–6 | `crewops.core` timeutil/duty/windows, 7 rule classes, Tier-1 tools + repos. **16/16 Tier-1 green** |
| **P2 Core, Tier 2–3** | 6–11 | candidates, positioning, costing, ranking, impact, rotation, closure, joint. **38/38 + 6/6 green.** This is the moat — protect this window |
| **P3 Agent + API + traces** | 11–15 | LangGraph graph, compiled plans, verification, FastAPI + SSE, span store, receipt endpoint |
| **P4 Frontend** | 15–20 | Console + Gantt, chat + citations + live trace, disruption workbench, trace inspector, eval scorecard |
| **P5 Ops + polish** | 20–23 | Schedulers/alerts, morning briefing, notification drafting, architecture diagram, README, failure analysis, deck |
| **P6 Rehearsal** | 23–24 | Run H1/H2 holdout once, record the score, rehearse the 5-minute demo |

**Parallelisation**
- **A — Core engineer:** `crewops.core` + conformance harness. Owns correctness. Nothing
  else touches this package.
- **B — Platform engineer:** ETL, repos, FastAPI, LangGraph, observability, schedulers.
- **C — Frontend engineer:** console, chat, workbench, trace inspector, scorecard.
- **D — Data/eval + narrative:** fixtures, eval scorecard content, architecture diagram,
  README, deck, demo script. Also the second pair of eyes on answer-key matching.

**Hard gate:** if P2 is not green by hour 11, cut Tier-3 `ops_rank`, the cascade simulator
and the metrics dashboard — never cut the conformance harness or the trace inspector.

---

## Part 15 — The five-minute demo script

1. **The desk at 05:00.** Open the console. It is quiet — dark cockpit. One alert:
   `cert lapse: C-5417 rostered 19 Sep, recurrent training expires 17 Sep`. *Our scheduler
   found S5 before compliance did.*
2. **The sick call.** Type: *"Captain C-1042 just called in sick for tomorrow — what should
   I do?"* Answer streams in ~2 s: 6 legs uncovered, 486 pax at risk day 1, ranked options
   led by reserve C-3310 at ₹18,500.
3. **Open the receipt.** 24 captains evaluated in 74 ms → 5 legal, 19 excluded (9 REST-04,
   8 QUAL-05, 1 DUTY-02, 1 on-call window). Click C-2087: the duty-budget bar shows
   51.83 + 9.5 = **61.33** against the 60h limit — **1h20m over**. Click C-3305: the on-call
   ribbon shows the 00:00–05:30Z window against the 06:00Z required report — 30 minutes
   outside — and, if you ask about the full pairing, day 2 also busts DUTY-02 by 8h15m.
4. **The boundary.** Point at the verification badge: *5/5 checks passed, 11 facts cited.*
   Explain that the model wrote the paragraph and computed none of it — and that we check
   that automatically.
5. **Generalise.** Custom event: close HYD 05:00–09:00Z on 19 Sep — a scenario not in the
   pack. It answers. Then chain a second event onto the resulting world.
6. **The scorecard.** `/eval` — 38/38 questions, 6/6 scenarios, live, against dCortex's own
   answer keys. Then the one case we get wrong, and why we abstain instead of guessing.
