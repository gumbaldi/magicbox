# Grilling: the Thorough Interview Path

Only read when the user picked "Thorough grilling" in Step 1. Start with the mode switch:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get grillMode
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get useMattpocockGrilling
```

- `grillMode = classic` **and** `useMattpocockGrilling = true` **and** the skill
  `mattpocock-skills:grilling` is available → call that skill and follow it. It saves context
  because it asks the whole frontier per round.
- Otherwise (default) → the step-by-step procedure below. If `classic` is configured but the
  plugin isn't available, fall back to the step-by-step procedure without fuss, and mention it
  once.

## Step-by-Step Procedure

Interview the user until you reach a shared understanding. Map the work as a **design tree**:
every decision branches into the decisions that hang off it. The **frontier** is every decision
whose prerequisites are already settled.

Work the frontier **one question per round**. Never two questions in one round, even when they
look independent — the user asked for it this way.

Each round:
1. State the question in prose first: what is being decided, what makes it non-obvious, what
   the trade-off is. Two or three sentences, no essay.
2. Give your recommendation explicitly, marked with `➡️`, before asking.
3. Ask it via `AskUserQuestion` with 3–4 options: the recommended one **first**, labelled
   `(Recommended)`, then the genuine alternatives with their real downsides, and always a final
   option "I have a follow-up question about this" so the user can dig in instead of deciding.
   The built-in "Other" entry covers free-text answers.
4. If the user picks the follow-up option, answer their question and re-ask the same decision
   afterwards.

Finding **facts** is your job, never the user's. When a question depends on something you could
look up — a file, a config, an installed tool, a remote — look it up before asking. Never ask
the user for anything the environment can tell you. A running lookup is an unsettled
prerequisite: skip that branch for now and ask a question that is ready instead.

The **decisions** are the user's. Put each to them and wait.

Each answer reshapes the tree: settled decisions push the frontier outward. Recompute, ask the
next single question. The session ends when the frontier is empty — then run the closing
question from step 5 of the skill before writing any plans.

---

Adapted from `mattpocock-skills:grilling` (MIT). The design-tree/frontier model is theirs; the
one-question-per-round format and the select-box protocol are cfq's addition.
