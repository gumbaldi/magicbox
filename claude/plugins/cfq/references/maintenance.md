# Maintenance Run

Only read when Step 11 finds `DUE <n>`.

1. Run `"<plugin-root>/bin/cfq" lang "<repo-root>"` — always, no plugin dependency.
   Its `missing`, `stray`, and `unfiled` arrays become findings.
2. `ponytail:ponytail-audit` — only when `usePonytailAudit` is `true` **and** the skill is
   available. Missing → the run continues with task 1 alone, no comment. The audit is a one-shot
   skill invocation and does not require ponytail's persistent mode. This is the only place cfq
   uses ponytail; outside a maintenance run cfq expects it dormant (`defaultMode: off`).
3. Findings from both tasks go into **one** combined list and **one** `AskUserQuestion`
   (multi-select) about what gets parked as a cleanup batch — one line per finding, each with an
   explicit recommendation (`queue it` / `fold into the current batch` / `ignore`) and a one-line
   reason. No selection is a valid answer: no batch, no second attempt.
4. Then run `"<plugin-root>/bin/cfq" maintenance stamp "<repo-root>"` — even when
   nothing was selected. The run happened either way.
