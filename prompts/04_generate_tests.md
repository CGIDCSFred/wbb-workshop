# Prompt 04 — Generate Tests & Test Data from the Spec

## How to use this prompt

The spec defines what "correct" means. This prompt turns it into an executable
regression suite and a golden test dataset — closing the governance loop:
regenerate, then prove with spec-derived tests on spec-derived data.

Open a fresh Claude context. Attach only:
- `spec/wbbaw_spec_v1.md`

Do NOT attach the original artifacts or any code. Tests and data must be derived
from the spec alone.

Then paste the prompt below.

---

You have a forensic specification for an analytics warehouse (WBBAW). Produce a
test suite and a golden test dataset that verify an implementation conforms to
this spec.

## Rules (inherited from the spec's discipline)

1. **Every test cites the spec.** Each test names the section it verifies, e.g.
   `# [Spec §4 Transformation Rules]`, `# [Spec §6 D1]`.
2. **Characterization, not aspiration.** Section 6 (Discrepancies) documents
   *as-built* behaviour. Write tests that assert the system behaves as-built —
   including the documented quirks. A test that asserts the "intended" behaviour
   instead of the documented one is wrong.
3. **Open Questions become skipped tests.** For anything in Section 7 the spec
   cannot pin down, emit a `@pytest.mark.skip(reason="Spec §7: unspecified — ...")`
   placeholder, so the gap is visible as missing coverage rather than silently
   absent.
4. **Golden data is designed, not random.** Cover the boundaries the spec
   implies, with the expected outcome the spec's rules dictate.

## What to produce

**Part 1 — Test suite (`tests/test_wbbaw_spec.py`, pytest).**
Group tests into:
- **Transformation rules** — grain (one fact row per eligible application),
  approval/decline flag logic, exclusions (test rows, abandoned applications),
  decision-day computation, surrogate-key uniqueness.
- **Characterization (as-built)** — one test per documented discrepancy in
  Section 6. For the WBBAW spec that means: the fact is keyed on submission date
  (not approval date); the segment concept carries source→warehouse under a
  renamed column; the decline reason is **not** persisted (no column); the job
  references a program that does not exist.
- **Equivalence** — the original and a regenerated implementation produce
  identical business answers (weekly volume, approval rate by segment) on the
  same input.

**Part 2 — Golden test dataset (`tests/golden_data.md` or a fixture).**
A small set of designed applications with their expected warehouse outcomes,
covering: a normal approval, a decline with a reason, an undecided application,
an abandoned application (excluded), a test customer (excluded), and a
week-boundary case (submitted one ISO week, decided the next — to pin the
submission-date keying). For each, state the expected fact row (or "excluded")
and cite the rule.

**Part 3 — How to run.** A short note on running the suite against an
implementation and reading the results — including the point that a failing
characterization test means someone changed the as-built behaviour (drift),
not that the test is wrong.
