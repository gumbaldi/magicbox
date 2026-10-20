# Design Notes

Why cfq's skills behave the way they do. Not loaded by any skill — history and rationale that used
to sit inline in skill/reference/agent prose, where every implementing session paid for it on every
turn. New rationale belongs here, not back in skill text.

## ifq: why a blocked-and-in-progress batch still waits

A batch that is both blocked and in-progress could in principle auto-resume, since it already has
work started. It doesn't: auto-resuming would restart work whose dependency reappeared after the
batch was started, so it waits like any other blocked batch instead.

## ifq: why the start gate was added

`SKILL.md` used to state plainly that invoking `/ifq` is itself the intent to start a batch, no
confirmation question — a deliberate choice, made to keep the session moving without an extra
round trip on every run. It was reversed on the user's request: the session now shows the batch
overview and the full queue and asks before touching anything, because "just start" gave no
chance to pick a different batch, or to notice a wrong one was about to be worked, before the lock
and branch were already committed to. A future reader finding the gate should not read it as
leftover caution to be trimmed back to the old behaviour — it replaced a decision that was tried
and explicitly walked back.

## ifq: why the WARN phase-announcement options changed

The three-option WARN prompt (Go/Handoff/Cancel) replaced an earlier version whose effective choice
was "start anyway, but it will hand off immediately without implementing" versus "cancel" — two
ways of not implementing, dressed up as a real choice. Handoff is the honest name for what used to
be the forced outcome of "start anyway".

## ifq: why the Stop Rule has only three triggers

A fourth trigger used to sit here — files changed that `## Affected Files` does not list. It fired
only after the phase had already gone green, which made the question it raised unanswerable in
practice: the work was done, the change was evidently necessary, and the only sensible answer was
"yes, continue". That made it a confirmation prompt, not a gate. **File-Scope Deviation** replaces
it: the same mechanical comparison, made mandatory and recorded instead of interrupted for.

## ifq: why cross-references are broken by step renumbering

Cross-references used to name steps by number (`Step 5`, `Step 9`). Every renumbering broke at
least one: Step 3 once claimed to have "resolved Steps 1, 2 and 3a"; Step 8 once pointed at "Step 5"
for a call that had moved to Step 9. Cross-references now name the step instead (`**Size Gate**`,
`**Batch Done**`), so a renumbering can't silently leave a stale reference behind. The `Section Map`
table is the one place step numbers still appear on purpose — it *is* the numbering.

## pfq: why Self-Critique of the Phase Cut exists

Observed in batch `009`: six phases were cut, the user said "write the plans", and only
afterwards, asked unprompted, did re-examining the cut within one turn produce a differentiated
answer — three phases clearly justified, one only a precondition, one delivering a different
benefit than assumed, one weak enough to drop. The batch went from six phases to five. Under the
rule this incident produced, the drop would still have prompted one question; the two narrowings
would have been made silently and reported. The specific failure mode: a phase enters the batch
because the user picked it from an option list the planner itself wrote, and a step that only asks
the user to review the plan cannot catch that — the user is reviewing a proposal built from their
own earlier answer.

## pfq/ifq: why decision questions explain their context first

In a `pfq` session (2026-09-23), the planner explained its hypothesis in a dense paragraph written
in code identifiers, then asked only "what should happen?". The user answered: "Ich verstehe den
context nicht. Wenn ich Entscheidungen treffen soll brauche ich mehr Details: worum geht es, was
ist das Problem, wie kann man es lösen." `interaction-policy.md`'s **Decision Question Context**
exists so a decision question always states what it's about, what the problem is, and what each
option costs, in the user's own terms, before asking — not just in `pfq`, since `ifq`'s branch and
self-critique questions have the same shape.

## ifq: why the base-branch question always fires

`new`-branch base resolution used to ask only for the `newerCandidate` case, picking
`highestBatch`/`main` silently the rest of the time. That hid a real decision: unmerged batches
chain onto each other, so which branch a new one builds on decides which earlier, still-unmerged
work it inherits — a silent pick could carry work the user didn't expect to see land in this batch,
with no chance to notice before the branch was already cut. Asking every time, with the derived
base recommended first, keeps that choice visible without changing which branch usually gets picked
in practice — decided in the same interview that added `resume`/`start`.

## ifq: why `.dependsOn` never picks the base branch

Reported from `/home/code/git/kankuri` (batch 031 depending on 028, 2026-09-28): the new branch was
recommended on the stale dependency branch `cfq/028-…` while newer unmerged batch branches
`cfq/029-…` and `cfq/030-…` already existed — `bin/cfq branch plan` used to derive the base from
`.dependsOn` first (two now-removed `baseSource` values named after the dependency chain itself)
and only fall back to the chain decision when no unmerged dependency branch
existed at all.

`.dependsOn` is a selection gate, not a base-branch signal: a batch whose dependency isn't yet in
`impl/done/` is already never offered by `/ifq` (**Batch Selection Rules** in
`references/ifq-batch-start.md`), so by the time a branch is actually cut for a batch, every
dependency it names is already implemented — its work is either already folded into the newest
unmerged batch branch (the routine case) or already merged into `main`. Basing on the dependency
branch itself could then only ever produce a base *older* than the one the chain decision would
already pick, exactly the kankuri incident. The fix removes both of those `baseSource` values
entirely — the chain decision is now the only base path, unconditional.

The rare case an unmerged dependency branch does diverge from the chain — most commonly a
non-numbered branch the chain logic never considers as a candidate at all, or one abandoned in
favor of a parallel branch — still needs a safety net rather than silently vanishing: every
`uncontained` entry gained a `dependency` boolean, `true` when that branch is also named by the
batch's own `.dependsOn` and is missing from the chosen base. An entry appended this way (one that
never became a chain candidate on its own) never flips `baseSource` — it's a warning surfaced in
the base-branch question, not a vote for a different base.

The base-branch question itself was later cut down to a short menu; see "ifq: why the base-branch
question offers at most three branches" below.

## ifq: why the base-branch question offers at most three branches

The previous question listed the base, two more candidates and `main` because they existed. The
user (2026-10-04) wanted nothing shown without a reason: the newest branch recommended, the newest
batch branch offered only when the newest branch is not one, an on-demand list of ten, and a
free-text field for anything else.

Among batch branches the batch number, not the commit date, decides "newest": the highest batch
normally contains every earlier one and loses least when an older branch gets a late commit. That
late commit is then offered as its own option and named in a warning in the first question.

A deviation from the recommendation that drops unmerged batch branches is confirmed in a second
question, because a new batch normally builds on all earlier ones and such a pick is almost always
a mistake. The recommendation itself is never confirmed twice: what it lacks is already stated in
the first question.

The list is its own `branch list` verb because the path is rare, and a preflight result that
carried eleven rows every time would cost tokens in every session.

## pfq/ifq: why framework findings never go through SendFeedback

Reported from `/home/code/git/kankuri` (2026-09-28), more than once: a session — typically in a
follow-up conversation after `/ifq` or `/pfq` had already finished — drafted a finding about cfq
itself through the general Claude Code `SendFeedback` tool instead of `bin/cfq note plan
--framework`. `SendFeedback` reaches the Claude Code product team, not the cfq maintainer, so the
finding was never seen; the most recent instance was the branch-base finding fixed in batch `047`
phase 01, itself first reported that way.

The rule already lived in `references/queue-entries.md`'s **Plan Entry** section, but that file is
a cold-path reference `ifq` only reads when actually parking out-of-scope work — it never covered
the follow-up-conversation case, since by then the parking step had already run or never runs
again. The fix states the rule in both worker `SKILL.md` files' opening paragraph, not only in the
reference: a `SKILL.md` stays in context for the whole conversation, follow-ups included, while the
reference is loaded only on the parking path itself.

## pfq: why Phase Quality's five rules exist

One `/ifq` phase burned far more tokens than the task itself required — not the logic, the
debugging: a raw `bash -x` trace dumped whole into context, and a dozen one-off shell smoke tests
instead of one test file. The five rules in `references/phase-quality.md` turn that incident into a
standing checkpoint, not a one-time lesson repeated only in a post-mortem.

## cfq: why the report portal is data files plus a fixed viewer, not one rendered page per batch

The retired per-batch design (`bin/cfq report html` writing a standalone `<batch>.html`, plus a
second hand-rolled `index.html` listing them) meant every batch re-rendered its own copy of the
same header/table/section markup, and the "collected tree" (`reportDir`) and "repo-local" layouts
were two separately maintained code paths generating two different HTML shapes for the same data.
Splitting the page in two — one fixed viewer shell (`portal/index.html`, the `portal/*.js` scripts, `style.css`,
installed once per `reports/` root and version-stamped so a resync only recopies it when the
plugin's own version moved on) plus one plain data file per batch/entry — means a plan edit, a new
phase result, or a closed `todo/` card each touch exactly one small file, the shell never
regenerates, and there is exactly one rendering path (the viewer's own JS) instead of three
(per-batch HTML, collected-tree HTML, and now a second attempt at either). The `reportDir` mirror
and the repo-local copy stopped being two layouts for the same reason: both write the same data
shape, just to two different roots.

Data files are `.js`, not `.json`: browsers refuse `fetch()` of a local file under `file://`
(`CORS request not http`), which every one of these pages is opened as — no server, no build step,
just opening a path from a file manager or `/rfq`'s own printed URL. A `<script src="…">` tag has
no such restriction, so each data file registers its payload on `window.CFQ_DATA["<key>"]` as a
side effect of merely being loaded, and the viewer reads it back off that global instead of issuing
a request for it.

## pfq: why the plan review gate exists

A user saw only a truncated overview after `/pfq` had already released the batch, so they could
not judge the plan and did not know the plan files were plain Markdown they could edit. The gate
turns that around: `/pfq` prints a digest of the whole plan and holds the batch until the user
answers. It sits after the files are written and linted, not before, so what is shown is
byte-for-byte what `/ifq` will read and nothing is generated twice.

The gate has no off switch and no display-only mode — decided in the interview; adding one later
is a single schema entry. A `.review` marker has no staleness window, unlike `.planning`: a
`.planning` marker guards a session that may have crashed mid-write, so it expires, while an
unanswered review is a plan that is complete and waiting for a human, and expiring it would
release a batch nobody approved.

## pfq: why `changes-steps` is a warning, not a finding

`/ifq`'s Lint Gate ends the session on a finding, so making the numbered-steps rule a finding
would lock out every batch parked before the rule existed. The lint reports it as `warn:`, and
the digest falls back to a minimal rendering for such a batch.

The digest reads `## Changes` instead of a separate summary section on purpose: a second text
describing the change could drift from the instructions the implementer actually follows, whereas
the steps shown at the gate are the steps `/ifq` executes.

## cfq: why usage is counted per `message.id`

Claude Code writes one transcript line per content block of an API response, and every one of
those lines repeats that response's `usage`. Summing per line counted a response with a thinking
block, a text block and two tool calls four times, which made every recorded number roughly twice
too high. A turn is one response, so lines are collapsed to one entry per `message.id` before
anything is summed.

## cfq: why sub-agents are attributed through `toolUseId`, not a time window

A phase's worker runs inside the window between two records, but so does anything else that
happens in that window — a worker whose session spans a record boundary was either counted twice
or clipped, and a worker that outlived the commit by its closing message fell outside. The spawning
`Agent` tool call is an exact link: its id is written to the sub-agent's own `meta.json`, and the
call sits in exactly one record's span. A time window stays only as the fallback for a sub-agent
without a usable link.

## cfq: why settling happens on the next cfq mutation, not in a session-end hook

A record is written at commit time, and the session keeps producing turns after it (the worker's
closing message, the orchestrator's summary), so the first numbers are always a little low. A
session-end hook would fix that, but it is a new hook class: another place that can fail, that
every installation must wire up, and that does not fire when a session is killed. Settling on the
next mutating cfq verb in the repo needs no new wiring and happens in every case where the queue is
used again. The cost is that a record stays provisional until then, which the portal shows as such.

## cfq: why cost has no price table

Prices change, differ per plan and per cache tier, and a stale table makes a confident wrong
number. Turns and tokens per model are facts read off the transcript, comparable across batches, and
enough to see where a batch spent its effort. A currency figure would add a claim cfq cannot keep
correct.

## cfq: why flags are computed in Python with constant thresholds

The portal's flags (`warn`, `info`) are a property of the data, not of the viewer: computing them in
`cfq_lib/flags.py` makes them deterministic, testable without a browser and free of model tokens,
and lets the overview and the batch page agree by construction. The thresholds are constants, not
settings, because a setting nobody tunes is one more thing to document, migrate and keep
consistent; a threshold that proves wrong is a one-line change with a test.

## cfq: why old-count telemetry was deleted rather than migrated or marked

Records written before per-response counting are wrong by about a factor of two, and the transcripts
needed to recompute them are often gone. Migrating would have produced numbers that look exact and
are not; marking them would have meant a special case in the portal, the flags and every
aggregate for data that will never be correct. Deleting them once, with a one-off command that is
not part of the plugin, keeps every reader free of a legacy branch. The files are git-ignored, so
the deletion cannot be undone, which was accepted.

## cfq: why the portal writes one file per batch and derives every path from its key

A batch page needs its plan, results, cost and notes; one file per batch means a phase commit
rewrites one file and the viewer loads only what the route needs. The path is the payload's
`window.CFQ_DATA` key plus `.js`, with no lookup table in between: the data layer, the viewer, the
`reportDir` mirror and the tests all compute it the same way, so a path that disagrees with its key
is a bug a test finds, not a mapping somebody forgot to update. The earlier mismatch — the viewer
loading a nested `batch/<name>/…` path while the writer produced a dotted file name beside it —
left every batch page empty.

## cfq: why phase state lives in `status.json` and the directories only mirror it

Until now a phase's state was inferred from where its file lay: in the batch directory it was open,
in `done/` it was done. That left no place for a third state. A phase the user wanted to leave out
had to be deleted or faked as done, and a red phase was only visible in `report.json`. Every script
that needed a state globbed the directories and re-derived it, each a little differently. A status
file gives the state one writer (`cfq_lib/phase_state.py`) and one reader path, so every consumer
agrees by construction.

The directories stay as a mirror because they cost nothing and are what a person sees when they open
a batch. `status.json` wins when the two disagree: a file moved by hand or a crash between the move
and the write is then a recoverable mismatch that `batch verify` reports and `batch recover` fixes
by moving the file, whereas trusting the directory would let an accident rewrite the state. Only a
phase file with no entry at all is adopted by where it lies, since there is nothing to contradict.

`error` still blocks. It is retryable, not terminal, and the lowest-numbered open-or-error phase is
always the next phase, exactly as before this change; letting the batch step past a red phase on its
own would turn a failure into silent skipped work. The only way past it is an explicit skip.

A skip is user-only because skipping is a scope decision, and a cheap model working under a failing
verification is the worst place to make one. The model may suggest it; the verb, the argument and
the start-gate option all require the user to act. A skipped phase's plan is not thrown away: the
reason and the plan text go to the `plan/` inbox at the batch's end, so the next planning session
can pick the work up.

The migration of existing batches is a throwaway script under `tools/`, not a `bin/cfq` verb, a new
status or a read-time fallback. cfq runs on two machines, each repo needs the migration once, and a
verb, a `MIGRATION_REQUIRED` status or a derive-on-read branch would be framework code that lives
on in every reader long after its single use. A batch without a readable `status.json` is handled
the same way everywhere, whatever the cause: it is not offered and the verbs refuse. The script and
its README note are deleted together once both machines are migrated.

## ifq: why a phase ends in a script-rendered cost line

The user asked on 2026-10-04 to see what a phase cost when it closes. The `Cost` line is rendered by a
script because a model's own estimate of its token use is never trusted, the same rule as `pfq`'s
final report: the numbers come off the transcripts, the model only prints them.

It rides on `phase commit` (classic mode) and `worker verdict` (orchestrator mode) because both calls
already happen, so the line costs no extra turn. It shows the state at commit time; the report portal
shows the settled one once the session is over.

The ledger entry gets a script-stamped `finished` because a record's `wallclock_s` covers only the
session's own transcript and ends when a worker is spawned, which would make the duration of an
orchestrated phase far too short.

Classic mode's red path is left out: `phase record` prints a bare path, and `SKILL.md` is at its line
budget, so there is no room to tell the session to print a line there. Orchestrator mode shows the
cost for red phases anyway, through the verdict.

## cfq: why skill text is written in the present tense

Skill, reference and agent text describes what applies, not how it used to be. A clause such as
"overlap no longer asks" or "as before" costs every session tokens to read, says nothing the
current behaviour does not, and ages into a statement about a state nobody remembers.
`check_no_history_wording` in `tests/test_reference_paths.py` rejects the common phrasings.

Reasons worth keeping from clauses removed under that rule:

- `/rfq` mentions that a batch finished before reports existed has none. Reports arrived with
  v0.2, so older batches in `done/` never got one, and `index` correctly returns `[]` for them.
- `bin/cfq phase commit` adds the `CFQ-*` trailers itself; `changelog commit-message` is the
  script verb that composes them, and a session never calls it directly.
- `ifq`'s `resume` snapshot reuses the script that existed before the snapshot moved into the
  preflight; only the caller changed, not the fields it returns.

## cfq: why an item in `plan/` or `todo/` is called an entry

The files called the same thing "entry", "card" and "queue note". A reader, or a model, that sees
three words assumes three kinds of thing. The one term is "entry" (`plan/` entry, `todo/` entry,
merge entry). Script output, CLI verbs such as `note merge-todo` and `note sweep`, and Python
docstrings keep their wording, because renaming them is a behaviour change, not a prose fix.

## cfq: why every reference file is linked from an entry point

A reference file that only another reference file names risks a partial read: the session loads
the first file, sees a pointer, and may skip it. `check_references_linked_from_entrypoint` requires
at least one direct pointer from a `SKILL.md` or agent definition, with the condition for reading
the file. The pointers inside reference files stay; the rule adds a direct one and removes none.

## cfq: why the SKILL.md budget counts characters

The budget used to be 200 lines. A line count rewarded long lines: a `SKILL.md` stayed under it by
packing more text into each one, while the cost every session pays is the text itself. Claude Code
also re-attaches only the first 5,000 tokens of a skill after a context compaction, so what sits
past that point is silently lost in a long session. The budget is now 16,000 characters on the text
as loaded, with each `${CLAUDE_PLUGIN_ROOT}` counted at its expanded installed-path length.

## ifq: why the SKILL.md is mode-neutral

Orchestrator mode is the default, yet the classic per-phase loop was part of the `SKILL.md` and so
loaded by every session, including the ones that never ran it. The `SKILL.md` now carries only what
both modes share. The per-phase loop of each mode, the batch start, the branch handling and the
batch end each live in their own reference file, named in the `SKILL.md` together with the
condition under which it is read.

## cfq: why commands are Markdown and never share a skill's name

The `.toml` command files were never loaded: Claude Code reads command files as Markdown only. They
are replaced by `pfq.md` and `ifq.md`. A command with the same name as a skill also hides the
skill's description from the session's listing and shows the command's instead, so the four
commands (`cfq`, `pfq`, `ifq`, `rfq`) are short aliases and none repeats a skill name.

## cfq: why the skill prose has eval cases

Nearly all of cfq's behaviour lives in prose that no test exercised: the unit tests cover scripts,
not what a model does when it reads a `SKILL.md`. Each case in `evals/` comes from a recorded
incident, so it pins down a failure that happened once rather than one somebody imagined. A case
tests behaviour only up to the first user question, because nobody answers one in an eval run. The
cases run on demand and never in CI, because every run spends model usage.

## pfq/ifq: why the phase model uses implModels and no setting of its own

A phase names its model in an optional `## Model` heading, and the name must be an `implModels`
entry. A separate setting for "models a phase may use" was considered and rejected on the user's
rule: a model that may not implement may not be planned. One list therefore answers both questions,
and its first entry is the default for a phase without the heading.

## ifq: why a failed cheap phase retries on the default model, and escalation continues on the working tree

Two answers from the planning interview. A phase that failed on a smaller model than the default
runs on the default model the next time, because retrying the same model repeats the same failure.
A worker that judges its phase harder than planned escalates to the next stronger `implModels`
entry, and that model continues on the working tree with a handover note instead of starting over;
discarding the half-done work would throw away what the smaller model got right. The switch is
made by the orchestrator, which spawns a new worker: a running worker cannot change its own model.

## ifq: why the batch review's "small" is a fixed rule

`batchReviewFindings: auto` fixes small findings in the session and parks the rest. "Small" is a
fixed rule, not a judgment: the fix is at one location, the file is one a phase of the batch already
changed, and it needs no new file, dependency or setting. A judgment call would vary from run to run,
and a fix the reviewer calls small on one run and large on the next is not something a setting can
promise.

## pfq/ifq: why the preflight is not injected at load time

Injecting the preflight with the `` !`<command>` `` syntax would save one model turn per session.
It is not done: a load-time command that fails aborts the whole skill, and whether such commands run
at all under Plan Mode could not be verified from a planning session. Both skills carry a Plan-Mode
Gate that calls `ExitPlanMode` themselves, so a failure there would stop both from loading. The
manual check is parked in the planning inbox as a `plan/` entry, and the decision stays open until
it is done.

## cfq: why skill texts keep the full dispatcher path

The bare `cfq` command works on current Claude Code, and skill text would be shorter with it. The
user chose not to depend on the Claude Code version that provides it, so skill and reference texts
keep `"${CLAUDE_PLUGIN_ROOT}/bin/cfq"`, and `<plugin-root>/bin/cfq` inside reference files.

## pfq/ifq: why lint resolves a missing file against pending phases

A file that an earlier phase, or a batch listed in `.dependsOn`, creates does not exist when a later
phase is planned. Lint used to report it as `missing` when the later phase listed it bare, and as
`stale-new` once it existed and was marked `(new)`, so the file failed at every point in time.
Planners worked around it by hiding such bullets from lint and from the overlap check.

Lint now looks the path up in the plan data it reads anyway: only the creating phase marks the
file `(new)`, and later phases and dependent batches list it bare. There is no third marker,
because a marker is one more thing a planner can set wrongly, while the answer is derivable. A
missing file whose creating phase is done, skipped or numbered later stays a blocking finding that
names that phase, and two phases that both mark one file `(new)` are a `duplicate-new` finding.

`stale-new` is a warning only for the next pending phase of a batch that has left planning. A phase
interrupted after it created its files must be resumable, so its own `(new)` files existing is
expected. While `.planning` exists nothing has been implemented, so an existing "new" file is a
plan error and stays a finding.

## cfq: why the default branch is detected and has no setting

Batch finish and the merge entry assumed `main`. A repository whose default branch is `master`, or
another name, got a wrong comparison. `default_branch()` in `cfq_lib/proc.py` resolves it in one
place for every script: `origin/HEAD` first, then `main`, then `master`.

The remote state comes first because a local default branch can lag far behind it, and the finish
comparison must measure against what the remote holds. The local branch is the fallback. No fetch
is added, so the answer is as fresh as the last fetch the user made.

A `defaultBranch` setting is not added. It waits for a repository whose merge target differs from
its default branch, which none of the managed repositories is.

## ifq: why the start prints the batch overview only

`/ifq` printed the phases twice at its start: the batch overview, and a flat listing of all phases
below it. The listing repeated the overview and cost input and output tokens in every session. It is
dropped without a replacement, and `batch.briefText` leaves the preflight result.

Priority is already in the queue listing, which marks a flagged batch, and a batch `/ifq` offers has
no open dependency, so a header line for either would repeat or state nothing. The dashboard keeps
the flat listing through `bin/cfq brief --with-done`.

## ifq: why no merge entry is written

`/ifq` wrote a `todo/` entry at the end of every batch that asked the user to merge the batch
branch, with a `check:` line that closed it once the branch was merged. In a repository that keeps
its default branch untouched, the entries piled up and were never closed. Merging is the user's own
step and needs no reminder from cfq, so no entry is written and the `note merge-todo` verb is
removed with its tests and documentation. The closing report names the batch branch and the branch
it was cut from on a `Branch` line instead.

The report portal keeps its merged column and reads the state from Git: the batch's branch, or its
last recorded commit, is reachable from the default branch. A squash merge shows as not merged. The
portal raises no flag for an unmerged batch, because an unmerged batch is a normal state.

Rejected: keeping the entry with a setting that turns it off. The user wants it gone, and a setting
would keep the verb, its tests and its documentation alive for a behaviour nobody asked for.

## ifq: why the language checks at finish compare against the batch's base

The language checks at finish compared the batch's changes against the default branch. A chained
batch, cut from an unmerged predecessor, therefore re-reported every finding of its predecessors at
each finish. The comparison now uses the base branch recorded in the batch's changelog block, the
state on `origin` first. The default branch is the fallback when no base is recorded or the base
branch no longer exists.

Rejected: keeping the default branch as the only base. It is the right base for a batch cut from
it and the wrong one for every other batch.

## ifq: why the worker briefing is a file

The orchestrator passed the worker its briefing as the verbatim output of `worker brief`, and a rule
in the prose said to pass it unchanged. The rule did not hold: an orchestrator shortened the
briefing to save its own context, and the workers lost the recorded deviations of earlier phases.
`worker brief` now writes the briefing to `.worker-brief.json` in the batch directory, replaced per
phase, and the orchestrator passes only the path together with the fields it reads itself. A path
cannot be shortened.

Rejected: capping `priorDeviations` in the script, because the worker then no longer sees everything
a phase before it recorded. Also rejected: a hash check between `worker brief` and `worker verdict`,
which detects a shortened briefing after the fact and does not prevent it.

## pfq: why phase files start from a shipped template

`phase-quality.md` and `plan-park.md` referred to "the template" for phase files, but the plugin
shipped none. The planning model copied the format from an old batch, the format drifted from batch
to batch, and the drift cost tool calls in lint and in the phase announcement.
`references/phase-template.md` is now the one skeleton, and a test keeps it in line with
`cfq lint`, so the template cannot fall behind the checks.

Rejected: spelling the structure out in `phase-quality.md`. Every planning session reads that file
in full, and the skeleton is only needed at the moment a phase file is written.
