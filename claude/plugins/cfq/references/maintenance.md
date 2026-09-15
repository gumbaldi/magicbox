# Maintenance Run

Only read when pfq's **Maintenance** finds `DUE <n>`.

1. Run `"<plugin-root>/bin/cfq" lang "<repo-root>"` — always, no plugin dependency.
   Its `missing`, `stray`, and `unfiled` arrays become findings.
2. `ponytail:ponytail-audit` — only when `usePonytailAudit` is `true` **and** the skill is
   available. Missing → the run continues with task 1 alone, no comment. The audit is a one-shot
   skill invocation and does not require ponytail's persistent mode. It is cfq's one one-shot
   ponytail use, gated by `usePonytailAudit`. Outside it, cfq expects ponytail dormant
   (`defaultMode: off`).
3. Findings from both tasks go into **one** combined list. Zero findings → no entry, move to step
   4. One or more → write **one** `plan/` entry via `"<plugin-root>/bin/cfq" note plan
   "<repo-root>" "maintenance-findings" "<body-file>"` — one line per finding, each with an
   explicit recommendation (`queue it` / `ignore`) and a one-line reason. No question, no batch
   parked here.
4. Then run `"<plugin-root>/bin/cfq" maintenance stamp "<repo-root>"` — even when
   nothing was found. The run happened either way.
