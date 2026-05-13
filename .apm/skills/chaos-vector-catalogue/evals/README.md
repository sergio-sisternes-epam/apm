# chaos-vector-catalogue evals

Two complementary eval files live here. They are the ship gate
described in `plan.md` Step 6.

## 1. `evals.json` -- content evals

Three scenarios that pit the skill against itself with-vs-without
loading. Each scenario lists `with_skill_expected` behaviours,
`without_skill_likely` failure modes, and a `pass_criteria` line.

- `vector-pick-and-reproduction` -- proves the skill drives the
  agent to invoke the real binary (subprocess + captured stderr +
  exit code) instead of writing a Python-level YAML parser test.
- `deduplication-against-memory` -- proves the skill drives the
  agent to consult `memory/chaos-monkey/findings.md` before
  proposing a vector.
- `classification-discipline` -- proves the skill drives the
  agent to cite real captured evidence for graceful / silent /
  uncontrolled classification, and to respect the no-fix hard
  constraint.

**Ship gate:** on at least 2 of 3 scenarios, the with-skill output
must meet `pass_criteria` and the without-skill output must not.
If 0 or 1 scenarios show a delta, redesign or delete the skill.

## 2. `trigger-evals.json` -- dispatch description evals

Twenty queries split 60/40 train/val (12 train, 8 val). Validation
split is the ship gate.

- 10 should-trigger queries: failure-mode discovery, fuzzing,
  undocumented-input exploration, regression-trap framing.
- 10 should-not-trigger queries: PR review, generic coverage,
  docs, normal bugfix, AuthResolver explanation, release, triage.

**Ship gate:** rate >= 0.5 on should-trigger validation split AND
< 0.5 on should-not-trigger validation split.

## When to re-run

- After any change to the skill `description` frontmatter.
- After any change to sibling persona / skill dispatch
  descriptions in this repo (DISPATCH COLLISION risk).
- After `seed-finding` produces a real trace (REAL-TASK
  REFINEMENT may surface new should-trigger queries to add).
