# Known limits, dataset discrepancies, and failure analysis

The brief says honest failure analysis scores well and overstating capability scores badly.
This document is written to be read *against* the demo, not instead of it.

---

## 1. Discrepancies in the reference implementation

These are not our bugs. They are places where the dataset's own generator is internally
inconsistent, and we had to choose. In both cases we reproduce the answer-key behaviour and
report the disagreement rather than silently picking a side.

### 1.1 RULE-FLT-03 was declared but never enforced — fixed, now a hard gate

`generate.py`'s `check_cover()` lists `RULE-FLT-03` in every option's `rules_checked`
array, but the function never evaluates it, so no scenario or question in the shipped
answer keys ever contains a FLT-03 breach.

**What we used to do.** `app/core/rules/flt03.py` computed the real 28-day block total
including the hours the candidate would actually fly, and reported it — but at `advisory`
severity, so it never removed a candidate. A `STRICT` flag flipped it to a hard gate "for
anyone who wants to see the difference."

**Why that was the wrong call, not just a cautious one.** It produced a live inconsistency
rather than a documented trade-off: `check_legality` / `enumerate_cover_candidates` would
call a genuine >100h/28d candidate "legal" (advisory verdicts don't count as breaches),
while `simulate_duty_window` — a separate, engine-free code path answering the same
question — reported a breach for the identical arithmetic. Two tools, one fact, two
verdicts. See the generalization suite's GQ16 for the reproduction.

**What we do now.** The advisory/strict toggle is gone. `RULE-FLT-03` is enforced exactly
like the other six: a breach makes the candidate illegal, full stop. We re-ran the full
answer-key suite (`tests/conformance/test_answer_keys.py` — all 6 scenarios, 38 questions,
2 held-out scenarios) with this enforced and every case still passes: none of the shipped
material comes anywhere near 100h/28d, so the risk the old comment warned about — "we could
exclude a candidate the shipped answer keys call legal" — never actually materialised. It
was a real risk worth naming when this was first built; it turned out not to be real, and
the honest response to that is to remove the escape hatch, not leave it wired in "just in
case." See `app/core/rules/flt03.py`'s module docstring and `tests/test_rules.py`'s
`test_flight_hour_breach_is_a_hard_gate_not_advisory`.

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

### 3.6 A name that isn't a crew_id silently became a different person — fixed

> *"Is Captain Nair legal to cover pairing P-2201?"*

`crew.json` has 7 different people named `*. Nair`. Entity resolution had no name-matching
logic at all — only `\bC-?(\d{4})\b`. Because the question also named a pairing and a rank,
`entities.py`'s "a pairing plus a role implies the crew member holding that role on it"
fallback fired, discarded the word "Nair" entirely, and returned P-2201's actual captain
(`C-5837, A. Sharma`) with no ambiguity or unresolved signal — a fluent, confident answer
about a person the question never named. Worse than a lookup miss, because a miss is
visible and this wasn't.

**What we did.** `resolve()` now checks a surname index built from `world.crew` before
falling back to that heuristic. A surname that narrows to exactly one crew member (by
surname, or by surname plus a stated rank) still resolves normally. One that stays
ambiguous is reported as such (`Entities.ambiguous`, `kind: "crew_name"`) instead of guessed.
One that matches a real surname but not at the stated rank is `unresolved`, not substituted
with someone of the wrong rank. See `tests/test_routing_and_honesty.py`'s
`test_ambiguous_surname_is_flagged_not_silently_substituted` and its two neighbours.

### 3.7 Direct legality checks skipped status and rank preconditions — fixed

> *"Captain C-1042 is on leave — can they legally cover this pairing?"* → `legal: true`.
> *"Can this First Officer legally hold the Captain's seat?"* → `legal: true`.

`enumerate_cover_candidates` / `resolve_disruption` filter candidates to *active* crew of
the *required rank* before anything reaches the seven-rule engine (`candidates.py`'s own
module docstring names this as the first gate). `check_legality` and `simulate_assignment`
— the tools for asking about one specific, named crew member — called the rule engine
directly and never passed through that filter, so both questions above came back legal,
because none of the seven numbered rules encodes "is on leave" or "holds the right rank."

**What we did.** Both checks now live in the rule engine itself
(`app/core/rules/precondition.py`), run first, short-circuiting exactly like RULE-QUAL-05
already does — every entry point enforces them identically instead of relying on whichever
caller happened to filter upstream. The rank check is opt-in (`required_role`, defaulting to
`None`): every one of the 38 shipped questions calls `check_cover` without ever naming a
seat, and stays bit-for-bit unchanged (`test_no_seat_named_keeps_every_prior_behaviour_
unchanged`). `check_legality`'s new `role` parameter, and `entities.py`'s new `seat_role`
(a second role named in the question that differs from the resolved crew member's own
rank), wire this through for the natural-language case that names one rank as the
candidate and a different rank as the seat.

**What we did not fully solve.** That NL wiring depends on `entities.py` already knowing
which named crew_id is *the candidate* when a question names two ("Captain C-1042 calls in
sick — can First Officer C-1694 cover the Captain's seat?"). Right now the first crew_id
mentioned always becomes `e.crew_id`, regardless of which one the sentence is actually
asking about — a real, separate gap in subject disambiguation, not the rank check itself.
The single-crew-id phrasing ("Can First Officer C-1694 legally cover the Captain's seat on
P-2291?") already works correctly end-to-end; the two-crew-id phrasing does not yet.

### 3.8 The policy-question guard is tuned to specific phrasings — partially addressed

> *"C-3940 is showing a 0.71 disruption-risk score for tomorrow's pairing — is keeping them
> on it a good idea?"*

`POLICY_RE` caught the three canned examples in `test_routing_and_honesty.py` because it was
built from their literal trigger words. This same-meaning paraphrase, with none of them, did
not set `policy_question`, and routed to a plain risk lookup instead of declining.

**What we did.** Widened the pattern to also catch generic evaluative-judgement language
("good/bad/wise idea," "makes sense to," "is it advisable") rather than adding one more
literal phrase. The full answer-key suite still passes with the wider net — no graded
question was caught by it. This phrasing is now correctly declined.

**What we did not do.** This is still a pattern match, not a semantic classifier. A further
paraphrase using none of the now-wider trigger words could slip through exactly the same
way this one did. The architecturally complete fix is routing evaluative-judgement
detection through the LLM-classifier fallback this codebase's own `plans.py` docstring
already describes as existing for "genuinely novel questions," rather than growing
`POLICY_RE` phrase by phrase indefinitely — not implemented here.

### 3.9 A closure on a station the network doesn't serve looked identical to one with nothing in the window — fixed

> *"PNQ is closed 08:00–14:00Z on 17 Sep — what's the crew impact?"*

`station_closure()` never checked its `station` argument against the network at all; it just
scanned `flights.json` for matches. A made-up station code and a real, served station that
simply has nothing happening in the window both produced `affected_flights: []` —
indistinguishable in shape, even though one is a true "nothing to report" and the other is
"this system has no data for that station at all."

**What we did.** `simulate_station_closure` now checks the station against `world.stations`
first and returns `found: false` with the actual station list, rather than silently
computing an empty-but-plausible-looking answer.

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
