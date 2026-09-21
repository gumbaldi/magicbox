# Interview Depth: When Each Option Fits

## Model Gate

Read `planningPolicy.planModels`/`.allowAnyModel` from the preflight result. `allowAnyModel: true`
→ skip, `Model Check` is `➖ allowAnyModel`. Otherwise substring-match the running model (from the
system prompt) against `planModels`, like `ifq`'s gate — no match → warn naming the model and the
list, and continue; this never blocks, unlike `ifq`.

Read when weighing which `AskUserQuestion` option to recommend at **Start Block** — the option text itself
only needs one clause, the reasoning for *why* it's recommended lives here.

## Start Block Questions

Ask everything that belongs before research starts in one `AskUserQuestion` call, before anything
else, every time — never skip, never infer. Up to three independent questions:

- **Interview depth** (always) — three options, the recommendation derived from scope (components
  touched, how unclear the requirement is, how far consequences reach) and justified in the option
  text — don't always mark the same one:
  - **Quick interview** — a handful of targeted questions.
  - **Thorough grilling** — a design tree, round by round, until nothing is left open.
  - **Grilling with docs** — thorough grilling plus a `CONTEXT.md` glossary and ADRs under
    `docs/adr/`.
  Full rationale below.
- **Priority** (always) — "Should this batch be flagged high priority?" (picked first by `ifq`'s
  ordering, marked in the `/cfq` dashboard; not flagging is normal and needs no answer).
- **Config** — see `<plugin-root>/references/config-overview.md`'s **The Config Question**.

On **Thorough** or **Grilling with docs**, read `<plugin-root>/references/grilling.md` and follow
it. Print `Interview Depth` and `Priority` (omit detail when not flagged) status lines once
answered.

## Quick interview

Fits when the scope is manageable — a handful of targeted questions is enough to resolve it.

## Thorough grilling

A design tree, round by round, until nothing is left open. Costs noticeably more planning tokens
than Quick interview; recommended for complex reworks where a handful of questions would still
leave real ambiguity.

## Grilling with docs

Thorough grilling plus a paper trail: domain terms into a `CONTEXT.md` glossary, hard-to-reverse
or surprising trade-off decisions into ADRs under `docs/adr/`. The most expensive option — it
writes versioned files into the target repo — so recommend it only for genuinely new domain
vocabulary or decisions someone would otherwise have to re-derive later.
