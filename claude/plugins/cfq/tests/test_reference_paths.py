"""Migrated from test-reference-paths.sh.

Guards the reference-file layout described in CLAUDE.md: one flat references/ directory, every
link ${CLAUDE_PLUGIN_ROOT}-qualified, no unexpanded token inside a reference file (the loader
never expands it there), every named script real. Four checks, grep-sweep style like
test-layout.sh check 8. Each check gets a synthetic minimal fixture
(test-no-duplicate-defaults.sh's style) rather than a full tree copy, so the self-test stays
cheap.
"""

import importlib.util
import re
import unittest

from cfq_testlib import PLUGIN_ROOT, CfqTestCase

LINK_RE = re.compile(r"(\$\{CLAUDE_PLUGIN_ROOT\}|<plugin-root>)/references/([A-Za-z0-9_-]+\.md)")
BARE_LINK_RE = re.compile(
    r"(\$\{CLAUDE_PLUGIN_ROOT\}/|<plugin-root>/)?references/[A-Za-z0-9_-]+\.md"
)
TOKEN_RE = re.compile(r"CLAUDE_PLUGIN_ROOT")
SCRIPT_NAME_RE = re.compile(r"cfq-[a-z-]+\.sh")
SHELL_MUTATION_RE = re.compile(r"\b(rm|mv|mkdir|rmdir|jq)\s")
SKILL_LINE_BUDGET = 200
CONTENTS_THRESHOLD = 100
CONTENTS_WINDOW = 30
HISTORY_RE = re.compile(
    r"\b(no longer|used to|as today|as before|now returning|now also|since v\d|is unchanged"
    r"|still unchanged|unchanged from)",
    re.IGNORECASE,
)
QUEUE_ITEM_TERM_RE = re.compile(r"\b(cards?|queue notes?)\b", re.IGNORECASE)


def _md_files(root):
    return sorted(root.rglob("*.md"))


# 1. Every ${CLAUDE_PLUGIN_ROOT}/references/<file>.md or <plugin-root>/references/<file>.md link
#    resolves under <root>/references/ -- SKILL.md uses the expanded env var, a reference file
#    (never itself expanded at runtime) uses the literal <plugin-root> token instead.
def check_links_resolve(root):
    fails = []
    for f in _md_files(root):
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            for m in LINK_RE.finditer(line):
                name = m.group(2)
                if (root / "references" / name).is_file():
                    continue
                fails.append(f"FAIL: {f}:{lineno} dangling reference link: {m.group(0)}")
    return fails


# 2. No bare `references/....md` link survives outside CLAUDE.md/docs/ (repo-root-relative there).
def check_no_bare_relative(root):
    fails = []
    for f in _md_files(root):
        rel = f.relative_to(root)
        if str(rel) == "CLAUDE.md" or rel.parts[0] == "docs":
            continue
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            for m in BARE_LINK_RE.finditer(line):
                match = m.group(0)
                if match.startswith("${CLAUDE_PLUGIN_ROOT}/") or match.startswith(
                    "<plugin-root>/"
                ):
                    continue
                fails.append(f"FAIL: {f}:{lineno} bare relative reference link: {match}")
    return fails


# 3. No literal ${CLAUDE_PLUGIN_ROOT} token inside a reference file -- the loader never expands it
#    there.
def check_no_token_in_references(root):
    fails = []
    refs_dir = root / "references"
    if not refs_dir.is_dir():
        return fails
    for f in sorted(refs_dir.rglob("*.md")):
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            if TOKEN_RE.search(line):
                fails.append(
                    f"FAIL: {f}:{lineno} unexpanded ${{CLAUDE_PLUGIN_ROOT}} inside a reference file"
                )
    return fails


# 4. Inverted by Phase 02: bin/cfq's noun routing replaced per-script call sites, so no .md under
#    skills/ or references/ may name a cfq-*.sh at all any more. CLAUDE.md is the one
#    allow-listed exception (it legitimately discusses implementation files by name) and keeps
#    Phase 01's original existence check instead.
def check_no_scripts_named(root):
    fails = []
    for sub in ("skills", "references", "agents"):
        d = root / sub
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            for lineno, line in enumerate(f.read_text().splitlines(), start=1):
                for m in SCRIPT_NAME_RE.finditer(line):
                    fails.append(
                        f"FAIL: {f}:{lineno} names a script directly, route through bin/cfq's "
                        f"noun instead: {m.group(0)}"
                    )
    claude_md = root / "CLAUDE.md"
    if claude_md.is_file():
        for lineno, line in enumerate(claude_md.read_text().splitlines(), start=1):
            for m in SCRIPT_NAME_RE.finditer(line):
                match = m.group(0)
                if (root / "scripts" / match).is_file():
                    continue
                fails.append(f"FAIL: CLAUDE.md:{lineno} names missing script: {match}")
    return fails


# 5. Added by Phase 05: every mutation of `.claude/cfq/` runs through a `bin/cfq` subcommand now
#    (`phase record`/`reopen`, `trash put`, `note plan`/`todo`, `batch ready`,
#    ...) -- no skill or reference file may instruct rm/mv/mkdir/rmdir/jq
#    in command position again. A word followed by whitespace is "command position"; the same word
#    immediately followed by a closing backtick (prose naming it, e.g. "no `jq`") never matches.
def check_no_shell_mutations(root):
    fails = []
    files = (
        sorted(root.glob("skills/*/SKILL.md"))
        + sorted(root.glob("references/*.md"))
        + sorted(root.glob("agents/*.md"))
    )
    for f in files:
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            for m in SHELL_MUTATION_RE.finditer(line):
                fails.append(
                    f"FAIL: {f}:{lineno} instructs a shell mutation: {m.group(0).strip()}"
                )
    return fails


# 6. Added by Phase 08: docs/configuration.md's settings reference table must document every key
#    in cfq_settings.py's schema -- the schema is the one source of truth (CLAUDE.md's Conventions),
#    so a new setting that never made it into the table would go undetected otherwise.
def check_settings_documented(root):
    fails = []
    config_doc = root / "docs" / "configuration.md"
    settings_script = root / "scripts" / "cfq_settings.py"
    if not config_doc.is_file() or not settings_script.is_file():
        return fails
    spec = importlib.util.spec_from_file_location("cfq_settings_schema_check", settings_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = config_doc.read_text()
    for key in module.SCHEMA:
        if key not in text:
            fails.append(f"FAIL: {config_doc} missing settings key documented in cfq_settings.py: {key}")
    return fails


# 7. Added by Phase 04: CLAUDE.md's 200-line SKILL.md budget was a sentence nobody enforced, which
#    is how two skills drifted past it unnoticed. Whole-file `wc -l`-equivalent line count,
#    frontmatter included -- what a session actually pays for.
def check_skill_line_budget(root):
    fails = []
    for f in sorted(root.glob("skills/*/SKILL.md")):
        n = len(f.read_text().splitlines())
        if n > SKILL_LINE_BUDGET:
            fails.append(f"FAIL: {f}: {n} lines exceeds the {SKILL_LINE_BUDGET}-line SKILL.md budget")
    return fails


# 8. Added by Phase 02 (batch 033): `references/dashboard.md`'s todo action must delegate to
#    `note sweep` rather than instruct the model to do the work by hand -- that hand-instructed
#    prose is why 48 cards piled up in this repo's own queue. Assert the file contains `note
#    sweep`, and that it contains neither `move the file` nor `todo/done/` as a destination the
#    text tells the reader to write to. Narrow and anchored to this one file -- a repo-wide prose
#    grep would be brittle, and check 5 already owns the token-level shell-mutation rule for every
#    file.
def check_dashboard_todo_delegates(root):
    fails = []
    f = root / "references" / "dashboard.md"
    if not f.is_file():
        return fails
    text = f.read_text()
    if "note sweep" not in text:
        fails.append(f"FAIL: {f} todo action doesn't delegate to `note sweep`")
    if "move the file" in text:
        fails.append(f"FAIL: {f} todo action still instructs `move the file` by hand")
    if "todo/done/" in text:
        fails.append(f"FAIL: {f} todo action still names `todo/done/` as a destination to write to")
    return fails


# 9. Added by Phase 04 (batch 035), extended by Phase 05: `implement-for-queue/SKILL.md` must keep
#    its pointer to `ifq-batch-start.md`'s **Start Gate** section reachable, and
#    `plan-for-queue/SKILL.md` must keep its pointer to the `--overview` call that precedes its
#    `RESULT` header -- a later edit that drops either mention would silently remove it from the
#    session's read path while the reference section itself stays in place, undetected by any
#    other check. One shared assertion over both files, not two copies.
def check_start_gate_and_overview_mentioned(root):
    fails = []
    checks = (
        (root / "skills" / "implement-for-queue" / "SKILL.md", "Start Gate"),
        (root / "skills" / "plan-for-queue" / "SKILL.md", "--review"),
    )
    for f, needle in checks:
        if not f.is_file():
            continue
        if needle not in f.read_text():
            fails.append(f"FAIL: {f} no longer mentions {needle!r}")
    return fails


# 10. Added by Phase 03 (batch 053): every references/*.md is named, with its full
#     ${CLAUDE_PLUGIN_ROOT}/ or <plugin-root>/ path, in at least one skills/*/SKILL.md or
#     agents/*.md. A file reachable only through another reference file risks a partial read.
def check_references_linked_from_entrypoint(root):
    fails = []
    refs_dir = root / "references"
    if not refs_dir.is_dir():
        return fails
    entrypoints = sorted(root.glob("skills/*/SKILL.md")) + sorted(root.glob("agents/*.md"))
    named = set()
    for f in entrypoints:
        for m in LINK_RE.finditer(f.read_text()):
            named.add(m.group(2))
    for f in sorted(refs_dir.glob("*.md")):
        if f.name not in named:
            fails.append(
                f"FAIL: {f} is named by no skills/*/SKILL.md or agents/*.md, link it directly"
            )
    return fails


# 11. Added by Phase 03: a reference file longer than CONTENTS_THRESHOLD lines has a `## Contents`
#     heading within its first CONTENTS_WINDOW lines, and every other `## ` heading of the file
#     (outside code fences) appears text-identical as a `- ` bullet in that section.
def _h2_headings(lines):
    """Yield (index, heading text) for each `## ` heading outside a fenced code block."""
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("## "):
            yield i, line[3:].strip()


def check_long_references_have_contents(root):
    fails = []
    for f in sorted(root.glob("references/*.md")):
        lines = f.read_text().splitlines()
        if len(lines) <= CONTENTS_THRESHOLD:
            continue
        headings = list(_h2_headings(lines))
        contents_at = next(
            (i for i, text in headings if text == "Contents" and i < CONTENTS_WINDOW), None
        )
        if contents_at is None:
            fails.append(
                f"FAIL: {f} has {len(lines)} lines but no `## Contents` heading within its "
                f"first {CONTENTS_WINDOW} lines"
            )
            continue
        end = next((i for i, _ in headings if i > contents_at), len(lines))
        bullets = {l[2:].strip() for l in lines[contents_at + 1 : end] if l.startswith("- ")}
        for i, text in headings:
            if i != contents_at and text not in bullets:
                fails.append(f"FAIL: {f}: `## {text}` is missing from the `## Contents` bullets")
    return fails


# 12. Added by Phase 03: skill, reference and agent text states what applies, not how it used to
#     be -- history goes to docs/design-notes.md.
def _prose_files(root):
    return (
        sorted(root.glob("skills/*/SKILL.md"))
        + sorted(root.glob("references/*.md"))
        + sorted(root.glob("agents/*.md"))
    )


def check_no_history_wording(root):
    fails = []
    for f in _prose_files(root):
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            for m in HISTORY_RE.finditer(line):
                fails.append(f"FAIL: {f}:{lineno} history wording: {m.group(0)!r}")
    return fails


# 13. Added by Phase 03: one word, "entry", for an item in plan/ or todo/.
def check_single_term_for_queue_items(root):
    fails = []
    for f in _prose_files(root):
        for lineno, line in enumerate(f.read_text().splitlines(), start=1):
            for m in QUEUE_ITEM_TERM_RE.finditer(line):
                fails.append(f"FAIL: {f}:{lineno} use the term 'entry', not {m.group(0)!r}")
    return fails


# 14. Added by Phase 03: the frontmatter `description` of a skill or agent holds neither `<` nor
#     `>` in its text (the `>` opening a folded block is not part of the text).
def _frontmatter_description(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    front = lines[1:end]
    for i, line in enumerate(front):
        if not line.startswith("description:"):
            continue
        parts = [line[len("description:") :].strip()]
        for nxt in front[i + 1 :]:
            if nxt and not nxt[0].isspace():
                break
            parts.append(nxt.strip())
        if parts[0] in (">", ">-", ">+", "|", "|-", "|+"):
            parts = parts[1:]
        return " ".join(parts)
    return None


def check_descriptions_have_no_angle_brackets(root):
    fails = []
    for f in sorted(root.glob("skills/*/SKILL.md")) + sorted(root.glob("agents/*.md")):
        desc = _frontmatter_description(f.read_text())
        if desc and ("<" in desc or ">" in desc):
            fails.append(f"FAIL: {f} description contains '<' or '>'")
    return fails


def run_all(root):
    fails = []
    fails += check_links_resolve(root)
    fails += check_no_bare_relative(root)
    fails += check_no_token_in_references(root)
    fails += check_no_scripts_named(root)
    fails += check_no_shell_mutations(root)
    fails += check_settings_documented(root)
    fails += check_skill_line_budget(root)
    fails += check_dashboard_todo_delegates(root)
    fails += check_start_gate_and_overview_mentioned(root)
    fails += check_references_linked_from_entrypoint(root)
    fails += check_long_references_have_contents(root)
    fails += check_no_history_wording(root)
    fails += check_single_term_for_queue_items(root)
    fails += check_descriptions_have_no_angle_brackets(root)
    return fails


class ReferencePathsTest(CfqTestCase):
    def test_links_resolve(self):
        tmp = self._repos_dir
        bad = tmp / "f1-bad"
        good = tmp / "f1-good"
        (bad / "references").mkdir(parents=True)
        (good / "references").mkdir(parents=True)
        (bad / "references" / "real.md").touch()
        (good / "references" / "real.md").touch()
        (bad / "skill.md").write_text("read `${CLAUDE_PLUGIN_ROOT}/references/nope.md`\n")
        (good / "skill.md").write_text(
            "read `${CLAUDE_PLUGIN_ROOT}/references/real.md`\n"
            "read `<plugin-root>/references/real.md`\n"
        )

        out = check_links_resolve(bad)
        self.assertTrue(
            any("nope.md" in line for line in out),
            msg="check 1 self-test did not catch a dangling link",
        )
        out = check_links_resolve(good)
        self.assertEqual(out, [], msg=f"check 1 self-test false-flagged a resolving link: {out}")

    def test_no_bare_relative(self):
        tmp = self._repos_dir / "f2"
        (tmp / "docs").mkdir(parents=True)
        (tmp / "skill.md").write_text("read `references/maintenance.md`\n")
        (tmp / "CLAUDE.md").write_text("see `references/queues.md`\n")
        (tmp / "docs" / "configuration.md").write_text("see `references/doc-style.md`\n")
        (tmp / "reference.md").write_text("read `<plugin-root>/references/queues.md`\n")

        out = check_no_bare_relative(tmp)
        self.assertTrue(
            any("skill.md" in line for line in out),
            msg="check 2 self-test did not catch a bare relative link",
        )
        self.assertFalse(
            any(
                "CLAUDE.md" in line or "configuration.md" in line or "reference.md" in line
                for line in out
            ),
            msg="check 2 self-test flagged an excluded doc file or a <plugin-root>-qualified link",
        )

    def test_no_token_in_references(self):
        tmp = self._repos_dir
        bad = tmp / "f3-bad"
        good = tmp / "f3-good"
        (bad / "references").mkdir(parents=True)
        (good / "references").mkdir(parents=True)
        (bad / "references" / "r.md").write_text("run `${CLAUDE_PLUGIN_ROOT}/scripts/x.sh`\n")
        (good / "references" / "r.md").write_text("run `<plugin-root>/scripts/x.sh`\n")

        out = check_no_token_in_references(bad)
        self.assertTrue(
            out, msg="check 3 self-test did not catch a literal token in a reference file"
        )
        out = check_no_token_in_references(good)
        self.assertEqual(
            out, [], msg=f"check 3 self-test false-flagged the bound <plugin-root> token: {out}"
        )

    def test_no_scripts_named(self):
        tmp = self._repos_dir / "f4"
        (tmp / "skills" / "some-skill").mkdir(parents=True)
        (tmp / "references").mkdir(parents=True)
        (tmp / "scripts").mkdir(parents=True)
        (tmp / "scripts" / "cfq-real.sh").touch()
        (tmp / "skills" / "some-skill" / "SKILL.md").write_text("run `cfq-real.sh`\n")
        (tmp / "references" / "r.md").write_text("run `cfq-real.sh`\n")
        (tmp / "CLAUDE.md").write_text("discusses `cfq-real.sh` and `cfq-ghost.sh` by name\n")

        out = check_no_scripts_named(tmp)
        joined = "\n".join(out)
        self.assertIn(
            "SKILL.md", joined, msg="check 4 self-test did not catch a script named under skills/"
        )
        self.assertIn(
            "references/r.md",
            joined,
            msg="check 4 self-test did not catch a script named under references/",
        )
        self.assertTrue(
            any("CLAUDE.md" in line and "cfq-ghost.sh" in line for line in out),
            msg="check 4 self-test did not catch CLAUDE.md naming a missing script",
        )
        self.assertFalse(
            any("CLAUDE.md" in line and "cfq-real.sh" in line for line in out),
            msg="check 4 self-test false-flagged CLAUDE.md naming a real script",
        )

    def test_no_shell_mutations(self):
        tmp = self._repos_dir / "f5"
        (tmp / "skills" / "some-skill").mkdir(parents=True)
        (tmp / "references").mkdir(parents=True)
        (tmp / "skills" / "some-skill" / "SKILL.md").write_text(
            "Green -> move the file with `mv \"$f\" done/` (`mkdir -p` first).\n"
        )
        (tmp / "references" / "r.md").write_text(
            "Clean up with `rm -f` and pipe through `jq -c '.'`; prose only, no `jq`.\n"
        )

        out = check_no_shell_mutations(tmp)
        joined = "\n".join(out)
        self.assertIn(": mv", joined, msg="check 5 self-test did not catch `mv` in a SKILL.md")
        self.assertIn(": mkdir", joined, msg="check 5 self-test did not catch `mkdir` in a SKILL.md")
        self.assertIn(": rm", joined, msg="check 5 self-test did not catch `rm -f` in a reference file")
        self.assertIn(": jq", joined, msg="check 5 self-test did not catch `jq -c` in command position")
        self.assertEqual(
            4, len(out), msg=f"check 5 self-test false-flagged the trailing prose `jq` mention: {out}"
        )

    def test_settings_documented(self):
        tmp = self._repos_dir / "f6"
        (tmp / "scripts").mkdir(parents=True)
        (tmp / "docs").mkdir(parents=True)
        (tmp / "scripts" / "cfq_settings.py").write_text(
            "SCHEMA = {\n"
            '    "fooKey": {"type": "bool", "default": True},\n'
            '    "barKey": {"type": "string", "default": ""},\n'
            "}\n"
        )
        (tmp / "docs" / "configuration.md").write_text("| `fooKey` | ... |\n")

        out = check_settings_documented(tmp)
        joined = "\n".join(out)
        self.assertIn("barKey", joined, msg="check 6 self-test did not catch an undocumented setting")
        self.assertNotIn("fooKey", joined, msg="check 6 self-test false-flagged a documented setting")

    def test_skill_line_budget(self):
        tmp = self._repos_dir / "f7"
        (tmp / "skills" / "ok").mkdir(parents=True)
        (tmp / "skills" / "tight").mkdir(parents=True)
        (tmp / "skills" / "fat").mkdir(parents=True)
        (tmp / "skills" / "ok" / "SKILL.md").write_text("x\n" * 200)
        (tmp / "skills" / "tight" / "SKILL.md").write_text("x\n" * 199)
        (tmp / "skills" / "fat" / "SKILL.md").write_text("x\n" * 201)

        out = check_skill_line_budget(tmp)
        joined = "\n".join(out)
        self.assertIn(
            "fat", joined, msg="check 7 self-test did not catch a SKILL.md over the line budget"
        )
        self.assertIn("201", joined, msg="check 7 self-test did not name the line count in its failure")
        self.assertNotIn(
            "ok/SKILL.md",
            joined,
            msg="check 7 self-test false-flagged a SKILL.md exactly at the budget",
        )
        self.assertNotIn(
            "tight/SKILL.md",
            joined,
            msg="check 7 self-test false-flagged a SKILL.md under the budget",
        )
        self.assertEqual(
            1, len(out), msg=f"check 7 self-test should only flag the over-budget file: {out}"
        )

    def test_dashboard_todo_delegates(self):
        tmp = self._repos_dir / "f8"
        (tmp / "references").mkdir(parents=True)
        (tmp / "references" / "dashboard.md").write_text(
            "1. List every entry under `todo/*.md`.\n"
            "2. Exit `0` -> done, move the file to `todo/done/`.\n"
        )

        out = check_dashboard_todo_delegates(tmp)
        joined = "\n".join(out)
        self.assertIn(
            "note sweep", joined, msg="check 8 self-test did not catch a missing `note sweep` delegation"
        )
        self.assertIn(
            "move the file",
            joined,
            msg="check 8 self-test did not catch `move the file` hand-instructed prose",
        )
        self.assertIn(
            "todo/done/",
            joined,
            msg="check 8 self-test did not catch `todo/done/` named as a write destination",
        )

        good = self._repos_dir / "f8-good"
        (good / "references").mkdir(parents=True)
        (good / "references" / "dashboard.md").write_text(
            'Run `"<plugin-root>/bin/cfq" note sweep "<repo-root>" --text` and show its output.\n'
        )
        out = check_dashboard_todo_delegates(good)
        self.assertEqual(
            out, [], msg=f"check 8 self-test false-flagged a delegating dashboard.md: {out}"
        )

    def test_start_gate_and_overview_mentioned(self):
        tmp = self._repos_dir / "f9"
        (tmp / "skills" / "implement-for-queue").mkdir(parents=True)
        (tmp / "skills" / "plan-for-queue").mkdir(parents=True)
        (tmp / "skills" / "implement-for-queue" / "SKILL.md").write_text(
            "no pointer to the gate here\n"
        )
        (tmp / "skills" / "plan-for-queue" / "SKILL.md").write_text(
            "no pointer to the review call here\n"
        )

        out = check_start_gate_and_overview_mentioned(tmp)
        joined = "\n".join(out)
        self.assertIn(
            "implement-for-queue",
            joined,
            msg="check 9 self-test did not catch a missing Start Gate mention",
        )
        self.assertIn(
            "plan-for-queue",
            joined,
            msg="check 9 self-test did not catch a missing --review mention",
        )

        good = self._repos_dir / "f9-good"
        (good / "skills" / "implement-for-queue").mkdir(parents=True)
        (good / "skills" / "plan-for-queue").mkdir(parents=True)
        (good / "skills" / "implement-for-queue" / "SKILL.md").write_text(
            "read ...ifq-batch-start.md's **Start Gate** section...\n"
        )
        (good / "skills" / "plan-for-queue" / "SKILL.md").write_text(
            'print `bin/cfq brief "<batch-dir>" --review` as returned...\n'
        )
        out = check_start_gate_and_overview_mentioned(good)
        self.assertEqual(
            out,
            [],
            msg=f"check 9 self-test false-flagged SKILL.md files that mention both: {out}",
        )

    def test_references_linked_from_entrypoint(self):
        tmp = self._repos_dir / "f10"
        (tmp / "skills" / "s").mkdir(parents=True)
        (tmp / "agents").mkdir(parents=True)
        (tmp / "references").mkdir(parents=True)
        for name in ("direct", "viaagent", "indirect"):
            (tmp / "references" / f"{name}.md").write_text("x\n")
        (tmp / "skills" / "s" / "SKILL.md").write_text("read `${CLAUDE_PLUGIN_ROOT}/references/direct.md`\n")
        (tmp / "agents" / "a.md").write_text("read `<plugin-root>/references/viaagent.md`\n")
        # edge case: named only by another reference file
        (tmp / "references" / "direct.md").write_text("see `<plugin-root>/references/indirect.md`\n")

        out = check_references_linked_from_entrypoint(tmp)
        joined = "\n".join(out)
        self.assertIn("indirect.md", joined, msg="check 10 self-test did not catch a reference named only by another reference")
        self.assertNotIn("direct.md is", joined.replace("indirect.md is", ""), msg="check 10 self-test false-flagged a directly linked reference")
        self.assertNotIn("viaagent", joined, msg="check 10 self-test false-flagged a reference named by an agent")
        self.assertEqual(1, len(out), msg=f"check 10 self-test should flag only the indirect file: {out}")

    def test_long_references_have_contents(self):
        tmp = self._repos_dir / "f11"
        (tmp / "references").mkdir(parents=True)

        def body(headings, total, contents=None):
            lines = ["# T", "", "Opening paragraph.", ""]
            if contents is not None:
                lines += ["## Contents"] + [f"- {h}" for h in contents] + [""]
            for h in headings:
                lines += [f"## {h}", "text"]
            lines += ["```", "## Not a heading", "```"]
            lines += ["filler"] * (total - len(lines))
            return "\n".join(lines) + "\n"

        (tmp / "references" / "good.md").write_text(body(["A", "B"], 101, ["A", "B"]))
        (tmp / "references" / "missing-bullet.md").write_text(body(["A", "B"], 101, ["A"]))
        (tmp / "references" / "no-contents.md").write_text(body(["A", "B"], 101))
        # edge case: 100 lines, no Contents
        (tmp / "references" / "short.md").write_text(body(["A", "B"], 100))

        out = check_long_references_have_contents(tmp)
        joined = "\n".join(out)
        self.assertIn("missing-bullet.md", joined, msg="check 11 self-test did not catch a heading missing from Contents")
        self.assertIn("no-contents.md", joined, msg="check 11 self-test did not catch a long file without Contents")
        self.assertNotIn("good.md", joined, msg="check 11 self-test false-flagged a complete Contents")
        self.assertNotIn("short.md", joined, msg="check 11 self-test false-flagged a 100-line file")
        self.assertNotIn("Not a heading", joined, msg="check 11 self-test counted a fenced heading")
        self.assertEqual(2, len(out), msg=f"check 11 self-test flagged the wrong set: {out}")

    def test_no_history_wording(self):
        tmp = self._repos_dir / "f12"
        (tmp / "references").mkdir(parents=True)
        (tmp / "references" / "bad.md").write_text(
            "The overlap prompt no longer asks.\nThat part is unchanged.\nSince v0.2 it works.\n"
        )
        (tmp / "references" / "good.md").write_text(
            "The interview runs unchanged.\nOverlap sets the field automatically.\n"
        )
        out = check_no_history_wording(tmp)
        joined = "\n".join(out)
        self.assertIn("no longer", joined, msg="check 12 self-test did not catch 'no longer'")
        self.assertIn("is unchanged", joined, msg="check 12 self-test did not catch 'is unchanged'")
        self.assertIn("Since v0", joined, msg="check 12 self-test did not catch 'since v<digit>'")
        self.assertNotIn("good.md", joined, msg="check 12 self-test false-flagged plain 'unchanged'")

    def test_single_term_for_queue_items(self):
        tmp = self._repos_dir / "f13"
        (tmp / "references").mkdir(parents=True)
        (tmp / "references" / "bad.md").write_text("Park a Card.\nWrite a queue note.\n")
        (tmp / "references" / "good.md").write_text("Park an entry. Discard the draft.\n")
        out = check_single_term_for_queue_items(tmp)
        joined = "\n".join(out)
        self.assertEqual(2, len(out), msg=f"check 13 self-test flagged the wrong set: {out}")
        self.assertNotIn("good.md", joined, msg="check 13 self-test false-flagged 'discard'")

    def test_descriptions_have_no_angle_brackets(self):
        tmp = self._repos_dir / "f14"
        (tmp / "skills" / "bad").mkdir(parents=True)
        (tmp / "skills" / "good").mkdir(parents=True)
        (tmp / "agents").mkdir(parents=True)
        (tmp / "skills" / "bad" / "SKILL.md").write_text(
            "---\nname: bad\ndescription: >\n  Work off <repo>/.claude/cfq/ plans.\nargument-hint: x\n---\nbody\n"
        )
        (tmp / "skills" / "good" / "SKILL.md").write_text(
            "---\nname: good\ndescription: >\n  Plain text only.\nargument-hint: <briefing>\n---\nbody > <\n"
        )
        (tmp / "agents" / "a.md").write_text(
            "---\nname: a\ndescription: Spawned by x <plugin-root>/y.\ntools: Read\n---\n"
        )
        out = check_descriptions_have_no_angle_brackets(tmp)
        joined = "\n".join(out)
        self.assertIn("bad/SKILL.md", joined, msg="check 14 self-test did not catch '<' in a folded description")
        self.assertIn("a.md", joined, msg="check 14 self-test did not catch '<' in a single-line description")
        self.assertNotIn("good/SKILL.md", joined, msg="check 14 self-test false-flagged argument-hint or the fold marker")

    def test_real_plugin_tree_passes(self):
        fails = run_all(PLUGIN_ROOT)
        self.assertEqual(fails, [], msg=f"{len(fails)} issue(s) found in {PLUGIN_ROOT}:\n" + "\n".join(fails))


if __name__ == "__main__":
    unittest.main()
