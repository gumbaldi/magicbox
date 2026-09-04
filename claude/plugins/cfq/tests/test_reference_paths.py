"""Migrated from test-reference-paths.sh.

Guards the reference-file layout described in CLAUDE.md: one flat references/ directory, every
link ${CLAUDE_PLUGIN_ROOT}-qualified, no unexpanded token inside a reference file (the loader
never expands it there), every named script real. Four checks, grep-sweep style like
test-layout.sh check 8. Each check gets a synthetic minimal fixture
(test-no-duplicate-defaults.sh's style) rather than a full tree copy, so the self-test stays
cheap.
"""

import re
import unittest

from cfq_testlib import PLUGIN_ROOT, CfqTestCase

LINK_RE = re.compile(r"(\$\{CLAUDE_PLUGIN_ROOT\}|<plugin-root>)/references/([A-Za-z0-9_-]+\.md)")
BARE_LINK_RE = re.compile(
    r"(\$\{CLAUDE_PLUGIN_ROOT\}/|<plugin-root>/)?references/[A-Za-z0-9_-]+\.md"
)
TOKEN_RE = re.compile(r"CLAUDE_PLUGIN_ROOT")
SCRIPT_NAME_RE = re.compile(r"cfq-[a-z-]+\.sh")


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
    for sub in ("skills", "references"):
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


def run_all(root):
    fails = []
    fails += check_links_resolve(root)
    fails += check_no_bare_relative(root)
    fails += check_no_token_in_references(root)
    fails += check_no_scripts_named(root)
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

    def test_real_plugin_tree_passes(self):
        fails = run_all(PLUGIN_ROOT)
        self.assertEqual(fails, [], msg=f"{len(fails)} issue(s) found in {PLUGIN_ROOT}:\n" + "\n".join(fails))


if __name__ == "__main__":
    unittest.main()
