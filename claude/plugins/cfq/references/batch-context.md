# Batch Context File

Every batch gets `<batch-dir>/.batch-context.md`, written once during Step 9, alongside the phase
files. It carries batch-wide information — decisions and constraints that hold across every phase,
not any one phase's job — so it survives `/clear`, a phase finishing, the batch's move into
`impl/done/`, and a later `/ifq` resume, none of which touch phase files or read them again in full.

## Format

```
# Batch Context

## Goal
<1-3 sentences: what this batch achieves and why>

## Decisions
<only decisions that hold across phases. A decision that already got a full ADR under docs/adr/
is referenced by path, not repeated>

## Invariants
<only if there are batch-wide invariants an implementer must not break>

## Cross-Phase Contracts
<only if one phase's output is another phase's documented input>

## Non-Goals
<only if something was explicitly ruled out during the interview, or dropped at Step 7a's
self-critique — either way, state the reason>
```

`## Goal` is the only mandatory section, always at least one line of real content. Every other
section is written **only** when there is real content — an empty section is omitted entirely,
never filled with a placeholder like "None." or "-".

## What does NOT go here

Phase-specific detail stays in that phase's own `NN-slug.md`. `.batch-context.md` is for
information that would otherwise be duplicated across every phase file, or that belongs to none of
them individually.

## Not a duplicate of ADRs

`docs/adr/` (Grilling-with-docs path) holds permanent, versioned, repo-wide decisions with their
own reasoning for future contributors outside cfq. `.batch-context.md` is this batch's own,
gitignored coordination note, read only by `ifq`. When a decision already got a full ADR,
`.batch-context.md`'s `## Decisions` entry is one line pointing at it, not a restatement.
