# Pipeline Flow

## Full graph

```
                        ┌─────────────────────────────────┐
                        │  Controller types a question     │
                        └────────────────┬────────────────┘
                                         │
                                         ▼
                        ┌────────────────────────────────┐
                        │  1. INGEST                      │
                        │  Clear state, init tool calls,  │
                        │  repair counter, citations      │
                        └────────────────┬───────────────┘
                                         │
                                         ▼
                        ┌────────────────────────────────┐
                        │  2. CLASSIFY                    │
                        │                                 │
                        │  a) Pattern router (always)     │
                        │     35 regex rules → score      │
                        │     each of 28 intents          │
                        │                                 │
                        │  b) LLM classifier (if key set) │
                        │     may override router only if │
                        │     confidence margin > 0.15    │
                        │                                 │
                        │  → intent + confidence          │
                        └────────────────┬───────────────┘
                                         │
                                         ▼
                        ┌────────────────────────────────┐
                        │  3. RESOLVE                     │
                        │  Extract & validate every ID    │
                        │  against the world snapshot     │
                        │                                 │
                        │  C-XXXX  → crew.json            │
                        │  P-XXXX  → pairings.json        │
                        │  VT-DXx  → flights.json         │
                        │  DX###   → flights.json         │
                        │  BLR/DEL → stations             │
                        │  dates   → schedule window      │
                        │                                 │
                        │  Unknown ID → unresolved list   │
                        │  Missing ID → inferred from data│
                        └────────────────┬───────────────┘
                                         │
                                         ▼
                        ┌────────────────────────────────┐
                        │  4. ROUTE  (decision)           │
                        └──┬──────────┬──────────────────┘
                           │          │
              ┌────────────┘          └──────────────────┐
              │  compound / policy /                      │
              │  unresolved entity /                      │
              │  missing required slot                    │
              ▼                                           ▼
 ┌────────────────────────┐              ┌───────────────────────────┐
 │  CLARIFY               │              │  UNSUPPORTED intent       │
 │  Names both readings   │              │  or no plan exists        │
 │  of a compound Q.      │              │                           │
 │  Asks for the missing  │              │  ABSTAIN                  │
 │  slot by name.         │              │  States what it can do    │
 │  Points at Workbench   │              │  instead                  │
 │  for chained events.   │              └──────────────┬────────────┘
 └──────────┬─────────────┘                             │
            │                                           │
            └──────────────────┬────────────────────────┘
                               │
                               │  intent known, entities clean
                               ▼
                ┌──────────────────────────────┐
                │  5. PLAN                      │
                │  Look up compiled plan for    │
                │  this intent (plans.py)       │
                │                              │
                │  plan_source: "compiled"      │
                │  (LLM tool planning is the   │
                │  fallback for novel Qs only)  │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  6. EXECUTE                   │
                │  Run each tool in sequence    │
                │  against the in-memory world  │
                │                              │
                │  Every scalar → fact ledger  │
                │  Every rule verdict → logged  │
                │  ~1,800 facts on a Tier-3 Q   │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  7. COMPOSE  ◄── pure code    │
                │  Build structured answer from │
                │  tool results. No LLM.        │
                │                              │
                │  headline, options, costs,    │
                │  exclusion_summary, citations │
                │                              │
                │  This is what the UI renders. │
                │  Model never touches it.      │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  8. NARRATE                   │
                │                              │
                │  No LLM key →                │
                │    template_narration()       │
                │    correct, terse, code-only  │
                │                              │
                │  LLM key present →            │
                │    model writes prose         │
                │    ONLY from the RESULT JSON  │
                │    "do not compute anything"  │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  9. VERIFY                    │
                │  Scan prose against the       │
                │  fact ledger                  │
                │                              │
                │  ① every number grounded?    │
                │  ② every C-XXXX in ledger?   │
                │  ③ every RULE-* evaluated?   │
                │  ④ legality claim consistent? │
                └──────┬───────────────┬───────┘
                       │               │
                    PASS            FAIL (violations)
                       │               │
                       │               ▼
                       │   ┌───────────────────────┐
                       │   │  REPAIR (once)         │
                       │   │  Feed violations back  │
                       │   │  to model, rewrite     │
                       │   └───────────┬───────────┘
                       │               │
                       │          PASS │ FAIL
                       │               │    │
                       │               │    ▼
                       │               │  ┌──────────────────────┐
                       │               │  │  DOWNGRADE            │
                       │               │  │  Serve template prose │
                       │               │  │  + honest note to     │
                       │               │  │  controller           │
                       │               │  └──────────┬───────────┘
                       │               │             │
                       └───────────────┴─────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────┐
                        │  10. FINALISE                 │
                        │  Stamp trace metadata         │
                        │  intent, tier, confidence,    │
                        │  plan_source, verified        │
                        └──────────────┬───────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────┐
                        │  AdvisorAnswer                │
                        │  narration (prose)            │
                        │  structured (JSON for UI)     │
                        │  verification report          │
                        │  full span trace              │
                        │  fact ledger                  │
                        └──────────────────────────────┘
```

---

## The boundary

```
  ┌──────────────────────────────────────────────────────┐
  │  PROBABILISTIC  (LLM)                                │
  │                                                      │
  │  classify   — picks 1 of 28 intents                  │
  │  resolve    — proposes entity IDs (code validates)   │
  │  narrate    — writes prose from a pre-computed result│
  │  repair     — rewrites prose after a violation list  │
  └──────────────────────────────────────────────────────┘
                          │
              ════════════╪════════════ THE BOUNDARY
                          │
  ┌──────────────────────────────────────────────────────┐
  │  DETERMINISTIC  (pure Python, no LLM, no DB)         │
  │                                                      │
  │  resolve    — validates every ID against the world   │
  │  plan       — fixed tool sequence from plans.py      │
  │  execute    — 33 typed tools, JSON in / JSON out     │
  │  compose    — builds structured answer               │
  │  verify     — checks every number in the prose       │
  │  downgrade  — serves template if verify fails twice  │
  └──────────────────────────────────────────────────────┘
```

---

## Example: "C-1042 is sick — what should I do?"

```
  ingest      clear state

  classify    pattern router: COVER_RECOMMENDATION (score 2.5)
              LLM (if available): agrees, confidence 0.92

  resolve     C-1042 → found in crew.json ✓
              pairing → inferred: P-2291 (next pairing at snapshot date)
              role    → inferred: Captain (from crew record)

  route       intent known, entities clean → plan

  plan        compiled plan for COVER_RECOMMENDATION:
                step 1  resolve_disruption(crew_id, pairing_id)
                step 2  get_crew(crew_id)
                step 3  get_costs()

  execute     resolve_disruption:
                enumerate all 150 crew
                filter to Captains → 24 candidates
                run 7 rules against each
                  RULE-REST-04  ×9 excluded
                  RULE-QUAL-05  ×8 excluded
                  RULE-DUTY-02  ×1 excluded
                  on-call window ×1 excluded
                → 5 legal options, ranked by cost
              get_crew → C-1042 record
              get_costs → rate card
              → ~1,800 facts recorded in ledger

  compose     headline: "Assign C-3310 at ₹18,500 — cheapest of 5 legal
                         options from 24 candidates evaluated"
              options list, exclusion_summary, citations

  narrate     LLM writes explanation from the result JSON
              (template prose if no key)

  verify      all numbers grounded ✓
              all crew IDs in ledger ✓
              all RULE-* evaluated ✓
              legality claim consistent ✓
              → PASS

  finalise    verified=true, plan_source="compiled", tier=3
```

---

## Honesty guards (route decision)

```
  Question arrives at route
         │
         ├─ intent == UNSUPPORTED ──────────────────► abstain
         │
         ├─ policy_question == true ────────────────► clarify
         │    "should we pre-emptively swap X out?"
         │    ruleset has no threshold for this
         │
         ├─ compound == true ───────────────────────► clarify
         │    "BLR closes AND captain calls in sick"
         │    two events interact; answering one
         │    confidently is the dangerous outcome
         │
         ├─ unresolved entities ────────────────────► clarify
         │    "C-9999 is sick" → ID not in dataset
         │
         ├─ required slot missing ─────────────────► clarify
         │    "can this crew member cover?" → which one?
         │
         └─ all clear ─────────────────────────────► plan
```

---

## Verify detail

```
  Prose from narrate
         │
         ▼
  ┌─────────────────────────────────────────────────────┐
  │  build_fact_index(trace)                             │
  │  collect every value the tools produced:            │
  │    numbers (all forms: 61.33, 61, 20 min)           │
  │    C-XXXX, DX###, P-XXXX, VT-DXx, RULE-*           │
  └──────────────────────┬──────────────────────────────┘
                         │
         ┌───────────────┼───────────────┬──────────────┐
         ▼               ▼               ▼              ▼
   numeric          entity IDs      rule citations  legality
   provenance       grounded?       evaluated?      consistent?
         │               │               │              │
         └───────────────┴───────────────┴──────────────┘
                         │
                    any violation?
                    /           \
                  NO            YES (up to 1 repair)
                  │                      │
               finalise            feed violations
                                   back to model →
                                   rewrite prose →
                                   verify again →
                                   still fails →
                                   downgrade
```
