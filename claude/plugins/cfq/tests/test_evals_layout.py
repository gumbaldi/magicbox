"""Guards the shape of the on-demand eval cases under evals/.

The cases themselves are run by hand with `claude plugin eval` (they spend model usage, so never
in CI); this file only checks the static layout they depend on: every case has a grader, every
grader names a known type, a case.yaml carries the schema line and its directory name, and the
README's harness facts are filled in. No YAML library -- frontmatter and case.yaml are read
line-wise.
"""

import re
import unittest

from cfq_testlib import PLUGIN_ROOT, CfqTestCase

GRADER_TYPES = ("regex", "tool_used", "tool_order", "file_exists", "llm", "baseline")
TYPE_RE = re.compile(r"^type:\s*([A-Za-z_]+)\s*$")
NAME_RE = re.compile(r"^name:\s*(\S+)\s*$")
SCAFFOLD_RE = re.compile(r"^\s*scaffold_script:\s*(\S+)\s*$")


def _case_dirs(root):
    evals = root / "evals"
    if not evals.is_dir():
        return []
    found = set()
    for name in ("prompt.md", "case.yaml"):
        for f in evals.rglob(name):
            if "results" in f.relative_to(evals).parts:
                continue
            found.add(f.parent)
    return sorted(found)


def _frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:i]
    return None


# 1. Every case directory has at least one graders/*.md.
def check_cases_have_graders(root):
    fails = []
    for d in _case_dirs(root):
        if not list((d / "graders").glob("*.md")):
            fails.append(f"FAIL: {d} has no graders/*.md")
    return fails


# 2. Every grader starts with a frontmatter block whose `type:` is a known grader type.
def check_grader_types(root):
    fails = []
    for d in _case_dirs(root):
        for g in sorted((d / "graders").glob("*.md")):
            fm = _frontmatter(g.read_text())
            if fm is None:
                fails.append(f"FAIL: {g} has no --- frontmatter block")
                continue
            types = [m.group(1) for m in map(TYPE_RE.match, fm) if m]
            if not types:
                fails.append(f"FAIL: {g} frontmatter has no type:")
            elif types[0] not in GRADER_TYPES:
                fails.append(f"FAIL: {g} unknown grader type: {types[0]}")
    return fails


# 3. A case.yaml has schema_version "1.1", name == directory name, an existing scaffold_script.
def check_case_yaml(root):
    fails = []
    for d in _case_dirs(root):
        f = d / "case.yaml"
        if not f.is_file():
            continue
        lines = f.read_text().splitlines()
        if 'schema_version: "1.1"' not in [ln.strip() for ln in lines]:
            fails.append(f'FAIL: {f} lacks the line schema_version: "1.1"')
        names = [m.group(1).strip("\"'") for m in map(NAME_RE.match, lines) if m]
        if names != [d.name]:
            fails.append(f"FAIL: {f} name {names} does not equal directory name {d.name!r}")
        for m in map(SCAFFOLD_RE.match, lines):
            if m and not (d / m.group(1).strip("\"'")).is_file():
                fails.append(f"FAIL: {f} scaffold_script names a missing file: {m.group(1)}")
    return fails


# 4. evals/README.md has a filled-in `## Harness facts` section.
def check_readme_facts(root):
    readme = root / "evals" / "README.md"
    if not readme.is_file():
        return [f"FAIL: {readme} is missing"]
    lines = readme.read_text().splitlines()
    try:
        start = lines.index("## Harness facts")
    except ValueError:
        return [f"FAIL: {readme} has no '## Harness facts' heading"]
    section = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        section.append(line)
    if any("TBD" in line for line in section):
        return [f"FAIL: {readme} Harness facts still contains TBD"]
    return []


def run_all(root):
    fails = []
    fails += check_cases_have_graders(root)
    fails += check_grader_types(root)
    fails += check_case_yaml(root)
    fails += check_readme_facts(root)
    return fails


def _write_case(root, name="demo", grader="---\ntype: tool_used\ntool: Skill\n---\n", scaffold=None):
    d = root / "evals" / name
    (d / "graders").mkdir(parents=True)
    (d / "prompt.md").write_text("---\nmax_turns: 5\n---\n\nhello\n")
    yaml = f'schema_version: "1.1"\nname: {name}\n'
    if scaffold:
        yaml += f"context:\n  scaffold_script: {scaffold}\n"
    (d / "case.yaml").write_text(yaml)
    if grader is not None:
        (d / "graders" / "g.md").write_text(grader)
    return d


class EvalsLayoutTest(CfqTestCase):
    def _root(self, name):
        root = self._repos_dir / name
        root.mkdir(parents=True)
        (root / "evals").mkdir()
        (root / "evals" / "README.md").write_text("## Harness facts\n\n1. yes\n")
        return root

    def test_routine_case_passes(self):
        root = self._root("routine")
        _write_case(root, scaffold="fixture.sh")
        (root / "evals" / "demo" / "fixture.sh").write_text("#!/usr/bin/env bash\n")
        self.assertEqual(run_all(root), [])

    def test_grader_without_type_is_reported(self):
        root = self._root("notype")
        _write_case(root, grader="---\ntool: Skill\n---\n")
        out = check_grader_types(root)
        self.assertTrue(any("no type:" in line for line in out), msg=str(out))

    def test_missing_scaffold_script_is_reported(self):
        root = self._root("noscaffold")
        _write_case(root, scaffold="fixture.sh")
        out = check_case_yaml(root)
        self.assertTrue(any("fixture.sh" in line for line in out), msg=str(out))

    def test_case_without_grader_and_tbd_are_reported(self):
        root = self._root("nograder")
        _write_case(root, grader=None)
        (root / "evals" / "README.md").write_text("## Harness facts\n\n1. TBD\n")
        self.assertTrue(check_cases_have_graders(root))
        self.assertTrue(check_readme_facts(root))

    def test_real_plugin_tree_passes(self):
        fails = run_all(PLUGIN_ROOT)
        self.assertEqual(fails, [], msg=f"{len(fails)} issue(s):\n" + "\n".join(fails))


if __name__ == "__main__":
    unittest.main()
