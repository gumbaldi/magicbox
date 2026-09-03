# Interview Depth: When Each Option Fits

## Model Gate

Read `planningPolicy.planModels`/`.allowAnyModel` from the preflight result. `allowAnyModel: true`
→ skip, `Model Check` is `➖ allowAnyModel`. Otherwise substring-match the running model (from the
system prompt) against `planModels`, like `ifq`'s gate — no match → warn naming the model and the
list, and continue; this never blocks, unlike `ifq`.

Read when weighing which `AskUserQuestion` option to recommend at Step 4 — the option text itself
only needs one clause, the reasoning for *why* it's recommended lives here.

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
