# Grilling: the Thorough Interview Path

Only read when the user picked "Thorough grilling" or "Grilling with docs" in Step 1. Start with the
mode switch:

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

## With-Docs Path

Only on the third option from Step 1. The interview above runs unchanged; this adds the written
paper trail.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/cfq-settings.sh" get useMattpocockGrilling
```

`useMattpocockGrilling = true` **and** both `mattpocock-skills:grilling` and
`mattpocock-skills:domain-modeling` available → call both and follow them. (`grill-with-docs` itself
carries `disable-model-invocation: true` and cannot be called; it is nothing but a one-line delegation
to those two.)

Otherwise → the step-by-step procedure above, extended by these techniques, which cost nothing but
attention:

- **Challenge against the glossary.** A term the user uses that conflicts with an existing `CONTEXT.md`
  gets called out on the spot, not silently reinterpreted.
- **Sharpen fuzzy language.** Overloaded words get a proposed canonical term — "you say account: the
  Customer or the User? Those are different things."
- **Stress-test with scenarios.** Invent concrete edge cases that force precision about where one
  concept ends and the next begins.
- **Cross-reference with code.** When the user states how something works, check whether the code
  agrees, and surface contradictions immediately.

And these writing rules:

- `CONTEXT.md` at the repo root is a **glossary and nothing else** — no implementation details, no
  spec, no scratch notes. A term goes in the moment it resolves, not batched at the end.
- ADRs land under `docs/adr/` as `NNNN-slug.md`, and only when **all three** hold: hard to reverse ·
  surprising without context · the result of a real trade-off. Most sessions produce none, and that is
  the skill working correctly, not a failure.
- Create both lazily — no scaffolding before there is something to write.

**Check before leaving this path.** The upstream docs report that the writing half silently does not
happen when `domain-modeling` runs inside another orchestration layer — which is exactly what cfq is.
So verify afterwards whether `CONTEXT.md` and `docs/adr/` were actually touched, and say what came out,
including "nothing qualified" as a legitimate result. Never claim a paper trail you did not confirm on
disk.

---

Adapted from Matt Pocock's skills (MIT) — <https://github.com/mattpocock/skills>. The design-tree /
frontier model comes from `grilling`, the glossary-and-ADR discipline from `domain-modeling`, and the
combination of the two from `grill-with-docs`. cfq's own additions are the one-question-per-round
format, the select-box protocol, and the fallback that keeps all of it working without the plugin.

- Grilling: <https://aihero.dev/skills-grilling>
- Grill with docs: <https://aihero.dev/skills-grill-with-docs>
- Domain modeling: <https://aihero.dev/skills-domain-modeling>
