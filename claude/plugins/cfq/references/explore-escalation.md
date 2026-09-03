# Explore Model Escalation

Shared by `plan-for-queue` Step 5 and `implement-for-queue`'s Research and Verification
Delegation (`<plugin-root>/references/queues.md`) — same rule, both places, worded identically:

> Run an Explore agent on `planExploreModel` / `implExploreModel` when the task is to **locate**:
> find a file, list the callers of a function, check a naming convention, count occurrences. Run it
> on `planExploreModelComplex` / `implExploreModelComplex` when the task is to **judge**: compare
> two files for consistency, name the rule behind a pattern, establish that something is *not*
> stated anywhere, weigh two implementations against each other. If the answer the agent must
> return is a list, the cheap model is right; if it is an assessment, it is not.

Both keys already ride on each skill's own preflight result (`pfq`'s Step 4, `ifq`'s Step 3)
(`planningPolicy.planExploreModel`/`.planExploreModelComplex` for `pfq`,
`policy.implExploreModel`/`.implExploreModelComplex` for `ifq`) — no `bin/cfq settings get` call at
either site.
