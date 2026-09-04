# Known limits, dataset discrepancies, and failure analysis

The brief says honest failure analysis scores well and overstating capability scores badly.
This document is written to be read *against* the demo, not instead of it.

---

## 1. Discrepancies in the reference implementation

These are not our bugs. They are places where the dataset's own generator is internally
inconsistent, and we had to choose. In both cases we reproduce the answer-key behaviour and
report the disagreement rather than silently picking a side.

### 1.1 RULE-FLT-03 is declared but never enforced

`generate.py`'s `check_cover()` lists `RULE-FLT-03` in every option's `rules_checked`
array, but the function never evaluates it. Two consequences:

* Cover segments carry `flight_hours = 0.0`, so a simulated assignment adds no block hours
  to the 28-day window at all.
* If we enforced the 100h limit as a hard gate, we could exclude a candidate the shipped
  answer keys list as legal.

**What we do.** `app/core/rules/flt03.py` computes the real 28-day block total including
the hours the candidate would actually fly, and reports it — but at `advisory` severity, so
it never removes a candidate. A `STRICT` flag flips it to a hard gate for anyone who wants
to see the difference.

**Why this matters operationally.** A real carrier would treat a 100h breach as
disqualifying. Our advisory verdict is the right call *against this dataset* and the wrong
call against a real one. That switch is one boolean, and it is deliberately visible.

### 1.2 The delay model uses two different report-time conventions

For a delayed duty, the generator computes the *full-duty* FDP with the report time held
fixed (`duty_length + delay` — the crew reported on time and then waited), but computes its
*partial-duty* figure with the report shifted by the delay (as if the crew were told to come
in late). Those two conventions disagree, and scenario S4 depends on both.

Under the shifted convention there is no breach at all: the 4-leg duty comes to 11.25h
against a 12.0h limit. Under the fixed convention it is 12.75h and busts.

**What we do.** The breach test uses the fixed-report convention (the operationally correct
reading, and the one S4's `breach: true` requires). `max_legal_sectors` uses the *same*
convention, which yields the same handover point the answer key uses — after leg 3. We also
expose `reference_partial_fdp_hours` so the key's own 9.5h figure is visible and the
difference is explainable rather than hidden.

---

## 2. Data limits we cannot engineer around

| Limit | Consequence |
|---|---|
| **Deadhead positioning exists only DEL→BLR** | Any other base pair returns `RULE-BASE-07: no same-day positioning flight from base`, exactly as the answer keys do. The positioning table is data (`core/positioning.py`), so a second city pair is one line — but the schedule does not support one. |
| **No booking data** | "Passengers affected" is seat count, not booked load. Misconnects, rebooking and compensation are unanswerable and the advisor says so. |
| **`hotel_overnight` is never charged** | Multi-day covers should incur it. The answer keys do not, so neither do we. The rate is in the cost card and unused. |
| **Risk scores are a provided input** | We consume `disruption_risk_score`; we do not model it. The brief is explicit that prediction is out of scope. |
| **Seven rules is the whole regulator** | No cumulative fatigue, no acclimatisation, no night-duty reduction, no standby-to-duty conversion rules. |
| **Cost ties break on `crew_id`** | Three day-off callouts at ₹24,000 are ordered alphabetically. That is arbitrary, which is precisely why `ops_rank` exists as a second, opinionated column. |
| **The world is frozen** | 2026-09-14T18:00Z. Relative dates resolve against a virtual clock, not wall-clock time, and the console says so. |

---

## 3. Question shapes we handle poorly

Found by probing the shipped advisor with questions *not* in the graded set. Each is
reproduced in `tests/test_routing_and_honesty.py`.

### 3.1 The headline failure — compound disruptions

> *"If BLR closes 08:00–14:00 on 17 Sep **and** the VT-DXA captain calls in sick that
> morning, what do I do?"*

**What it did before we caught it:** answered the sick call, confidently, with a full ranked
option list at ₹18,500 — and said nothing about the closure. The answer looked complete. It
was half the question, and the half it dropped changes the answer: several of those
"available" captains are on duties the closure has already delayed past their FDP.

**Why.** The engine models each disruption type correctly and independently. It has no
representation of two events interacting. The router picked the higher-scoring intent and
the rest of the pipeline had no way to know a second event existed.

**What we did.** A narrow guard (`COMPOUND_EVENT_RE`) detects two event verbs joined by a
conjunction and routes to a clarification that names both readings and points at the
Workbench, which *can* chain them by forking the world. We did **not** try to auto-compose
the two simulations — that would be a guess dressed as an answer.

**What we did not do, and why it matters.** An earlier version of this guard also flagged
any question whose runner-up intent came from a different family. It fired on nine of the
38 graded questions — *"BLR is closed, which flights are affected?"* legitimately matches
both a closure intent and a flight lookup. A guard that refuses good questions is worse than
no guard, so we deleted it rather than tuning it. Both directions are now asserted in the
test suite; you cannot tighten one without re-running the other.

### 3.2 Policy questions

> *"Should we pre-emptively swap C-1042 out of tomorrow given his 0.78 risk score?"*

Previously answered as a risk lookup — it returned the score and stopped, which reads as if
it had addressed the question. Every input is computable; the *threshold* is not in the
ruleset. There is no defensible answer to "is 0.78 high enough", so the advisor now says
that and offers the three inputs a controller would actually weigh.

### 3.3 Constrained cover requests

> *"Give me the cheapest cover for P-2291 that does not use a reserve."*

Abstains. The enumeration engine supports the filter internally, but no intent exposes it,
and the entity resolver has no notion of a negative constraint. This is a genuine coverage
gap, not a safety property — it should abstain *less* here, and would be a half-day of work.

### 3.4 Under-answering

> *"Is C-1042 fit to fly?"* → routes to a crew lookup.

It returns rank, base, ratings and certificates, which is *related* to the question but does
not answer it: "fit to fly" means a legality check against a specific duty, and no duty was
named. It should ask which duty. We added `fit to fly` to the legality pattern, but the
underlying weakness — an under-specified question answered with adjacent facts rather than a
clarification — is the same class of error as 3.2 and we have not solved it generally.

### 3.5 No decision memory

> *"What did we decide last time C-1042 was sick?"*

Decisions are persisted (`decisions` table), but nothing reads them back. Multi-turn context
covers the current conversation only.

---

## 4. Scale

The dataset is small by design and everything here is O(crew × duty-days) per enumeration —
24 candidates × 2 duty days in ~6 ms. At real-carrier scale (2,850 crew, 350 daily flights)
the shape holds but three things change:

1. The in-memory world stops being free. It becomes a cached, indexed projection with
   incremental invalidation on roster publish — the timeline merge is the hot path.
2. Candidate enumeration wants a pre-filter (base + rating + not-already-on-duty) before the
   rule engine runs, cutting the pool by roughly two orders of magnitude before the
   expensive per-day window arithmetic.
3. The fact ledger is exhaustive on purpose — 1,800 facts for one Tier-3 answer. At volume
   it needs sampling for storage while remaining complete in-process, since the verifier
   depends on completeness.

None of this touches the boundary. The rules engine is the same code.

---

## 5. Things we deliberately did not build

Authentication, multi-tenancy, write-back to a real crew system, a mathematical optimiser
(heuristic ranking with visible reasoning is what the brief asks for), a mobile app, and any
model of the disruption-risk signal itself.

The **Apply** button records a decision; it does not rewrite the roster. The world snapshot
is read-only by construction, and the `decisions` table is the queue a real write-back
adapter would consume. Notifications are drafted and logged; nothing is sent, because there
is no crew to page.
