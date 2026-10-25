# ifq: Batch Review

Read only when `policy.batchReview` is not `off`.

## When it runs

Once, at **Batch Done**, after the last phase went green and before `bin/cfq finish`. Both modes.

## When it is skipped

Each case prints the `Review` line shown; a skipped review never blocks `bin/cfq finish`.

- `bin/cfq ctx` returns `WARN` or `STOP` → `➖ Review  skipped · context`.
- The preflight's `branch` data names no base branch (`branch.base` is `null`) →
  `➖ Review  skipped · no base to diff against`.
- `code-review` is not among the skills this session can invoke →
  `➖ Review  skipped · code-review not available`.

## How it is started

Invoke the `code-review` skill with the arguments `<policy.batchReview> <base>...<branch>` — the
batch's base branch and the batch branch, both from the preflight result already in hand. Never pass
`--fix` or `--comment`. The review runs in the background; print `Review` once as started, wait for
its result, ask nothing meanwhile.

## Findings, by `policy.batchReviewFindings`

- `park` → fix nothing.
- `fix` → fix every finding.
- `auto` → fix a finding only when it is small: the fix is at one location; the file is one a phase
  of this batch already changed (listed in a done phase's `## Affected Files`); it needs no new
  file, dependency or setting. Everything else is parked.

## How a fix is made

One finding at a time: edit, then re-run the `## Verification` command of every done phase of this
batch whose `## Affected Files` lists the edited file. Green → keep. Red → take that one fix back
with `git restore <file>` and park the finding with the failure as its reason. After the last
finding: `git add` the kept fixes, one commit with the subject `Fix batch review findings` and one
body line per finding, then `git push`. Nothing kept → no commit.

## How findings are parked

One `plan/` entry for all of them, through `"<plugin-root>/bin/cfq" note plan "<repo-root>"
"batch-review-findings" -` with the body on stdin: the batch name, the review level, and per
finding its `file:line`, the one-sentence defect, the failure scenario, and why it was not fixed
(`mode park`, `not small: <which condition>`, or `verification red`).

## Status line

`Review`, composed by the model: `✅ Review  low · no findings`, `✅ Review  low · 3 findings · 2
fixed · 1 parked`, or one of the skip lines above. The parked entry's path goes on a `   └ `
sub-line.
