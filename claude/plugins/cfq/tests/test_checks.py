"""Migrated from test-checks.sh.

Self-test for scripts/cfq_lint.py, scripts/cfq_security.py, scripts/cfq_lang.py and
scripts/cfq_maintenance.py, plus the commands/* short/long-form pairs.
"""

import json
import os
import re
import subprocess
import unittest

from cfq_testlib import CfqTestCase, PLUGIN_ROOT, PhaseDirsStatus, write_status


def _rule_count(output, rule):
    return len(re.findall(rf": {re.escape(rule)}:", output))


class TestLint(PhaseDirsStatus, CfqTestCase):
    def _write(self, path, content):
        path.write_text(content)

    def test_dirty_batch_fires_every_rule_once(self):
        qdir = self._repos_dir / "lintrepo" / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        dirty = qdir / "2026-01-01-dirty"
        (dirty / "done").mkdir(parents=True)
        target = self._repos_dir / "existing-target"
        target.touch()

        # 01-a: correct -- all headings, one existing absolute path, no issues
        self._write(dirty / "01-a.md", f"""# Phase A
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 02-b: sections violation -- missing the Verification heading
        self._write(dirty / "02-b.md", f"""# Phase B
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
""")

        # 03-c: abspath violation -- relative path (existence is not checked for a non-absolute path)
        self._write(dirty / "03-c.md", """# Phase C
## Size
M
## Context
x
## Affected Files
- `relative/path.sh` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 04-d: missing violation -- absolute path, marked "(ändern)", does not exist
        self._write(dirty / "04-d.md", f"""# Phase D
## Size
M
## Context
x
## Affected Files
- `{self._repos_dir / 'does-not-exist.sh'}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 05-e: stale-new violation -- marked "(new)" but the path already exists
        self._write(dirty / "05-e.md", f"""# Phase E
## Size
M
## Context
x
## Affected Files
- `{target}` (new)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 08-g: sections violation -- missing the Size heading
        self._write(dirty / "08-g.md", f"""# Phase G
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 09-h: sections violation -- the old German "Größe" heading no longer counts as Size
        self._write(dirty / "09-h.md", f"""# Phase H
## Größe
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 10-i: verification-cmd violation -- prose only, no fenced code block, no backticked command
        self._write(dirty / "10-i.md", f"""# Phase I
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
This step must be verified manually by a human tester.
""")

        # 11-j: verification-expect violation -- a command, but no stated expected result
        self._write(dirty / "11-j.md", f"""# Phase J
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
```bash
bash tests/foo.sh
```
""")

        # 12-k: changes-empty violation -- heading present, section body empty
        self._write(dirty / "12-k.md", f"""# Phase K
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 13-l: files-empty violation -- heading present, no `- `…`` entry
        self._write(dirty / "13-l.md", """# Phase L
## Size
M
## Context
x
## Affected Files
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # 14-m: title violation -- no `# ` heading anywhere in the file
        self._write(dirty / "14-m.md", f"""## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        # done/07-f: numbering gap (06 skipped), full of content violations too -- proves done/
        # phases are excluded from sections/abspath/missing/stale-new, only numbering must fire.
        self._write(dirty / "done" / "07-f.md", f"""## Context
x
## Affected Files
- `relative/also-bad.sh` (ändern)
- `{self._repos_dir / 'also-does-not-exist.sh'}` (ändern)
## Changes
x
""")

        # invalid .priority value -> priority violation (a missing file is the normal, unflagged case)
        (dirty / ".priority").write_text("medium")

        proc = self.run_cfq("lint", str(dirty))
        self.assertNotEqual(proc.returncode, 0, "dirty batch should exit non-zero")
        out = proc.stdout + proc.stderr

        self.assertEqual(_rule_count(out, "sections"), 3, f"rule sections fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "numbering"), 1, f"rule numbering fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "abspath"), 1, f"rule abspath fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "missing"), 1, f"rule missing fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "stale-new"), 1, f"rule stale-new fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "priority"), 1, f"rule priority fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "batch-context"), 1, f"rule batch-context fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "verification-cmd"), 1, f"rule verification-cmd fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "verification-expect"), 1, f"rule verification-expect fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "changes-empty"), 1, f"rule changes-empty fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "files-empty"), 1, f"rule files-empty fired wrong count. Output:\n{out}")
        self.assertEqual(_rule_count(out, "title"), 1, f"rule title fired wrong count. Output:\n{out}")

        self.assertIsNone(re.search(r"^01-a\.md:", out, re.MULTILINE), "correct file 01-a.md appears in findings")
        self.assertNotIn("07-f.md:", out, f"done/ file content should never be linted, got: {out}")
        self.assertIn("14-m.md: title: missing # heading", out, f"title finding wrong/missing: {out}")

    def test_clean_batch_with_dangling_depends(self):
        qdir = self._repos_dir / "lintrepo2" / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        target = self._repos_dir / "existing-target2"
        target.touch()

        clean = qdir / "2026-01-02-clean"
        clean.mkdir()
        (clean / ".priority").write_text("high")
        (clean / ".dependsOn").write_text("gibtsnicht")
        (clean / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        self._write(clean / "01-a.md", f"""# Phase A
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")

        proc = self.run_cfq("lint", str(clean))
        self.assertEqual(proc.returncode, 0, f"clean batch (dangling depends only) should exit 0, got {proc.returncode}")
        out = proc.stdout + proc.stderr
        self.assertIsNotNone(re.search(r"^OK 1 phases$", out, re.MULTILINE), f"clean batch summary line missing/wrong: {out}")
        self.assertIsNotNone(
            re.search(r"^warn: .*: depends: gibtsnicht does not exist$", out, re.MULTILINE),
            f"clean batch missing depends warning: {out}",
        )

    def _changes_steps_batch(self, repo, changes, with_changes_heading=True):
        qdir = self._repos_dir / repo / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        target = self._repos_dir / f"{repo}-target"
        target.touch()
        batch = qdir / "2026-01-02-steps"
        batch.mkdir()
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        changes_block = f"## Changes\n{changes}\n" if with_changes_heading else ""
        self._write(batch / "01-a.md", f"""# Phase A
## Summary
Does a thing in plain words.
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
{changes_block}## Verification
`bash tests/foo.sh` must exit 0
""")
        return batch

    def test_changes_numbered_steps_lint_clean(self):
        batch = self._changes_steps_batch("stepsrepo1", "1. Do the first thing.\n2. Do the second.")
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIsNotNone(re.search(r"^OK 1 phases$", out, re.MULTILINE), out)
        self.assertNotIn("changes-steps", out)

    def test_missing_summary_warns_but_exits_zero(self):
        batch = self._changes_steps_batch("sumrepo1", "1. Do it.")
        phase = batch / "01-a.md"
        phase.write_text(phase.read_text().replace("## Summary\nDoes a thing in plain words.\n", ""))
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIsNotNone(re.search(r"^OK 1 phases$", out, re.MULTILINE), out)
        self.assertEqual(out.count("warn: 01-a.md: summary-missing: no ## Summary section"), 1, out)

    def test_summary_present_has_no_summary_warning(self):
        batch = self._changes_steps_batch("sumrepo2", "1. Do it.")
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertNotIn("summary-missing", out)

    def test_changes_prose_only_warns_but_exits_zero(self):
        batch = self._changes_steps_batch("stepsrepo2", "x")
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIsNotNone(re.search(r"^OK 1 phases$", out, re.MULTILINE), out)
        self.assertEqual(
            out.count("warn: 01-a.md: changes-steps: Changes has no numbered top-level step"), 1, out
        )

    def test_changes_step_only_inside_fence_warns(self):
        batch = self._changes_steps_batch("stepsrepo3", "```\n1. Not a real step.\n```")
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("warn: 01-a.md: changes-steps: Changes has no numbered top-level step", out)

    def test_missing_changes_heading_has_no_changes_steps_warning(self):
        batch = self._changes_steps_batch("stepsrepo4", "", with_changes_heading=False)
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 1, out)
        self.assertIn("01-a.md: sections: missing Changes heading", out)
        self.assertNotIn("changes-steps", out)

    # ---- ## Model heading (batch 053 phase 09) ---------------------------------------------------

    def _model_batch(self, repo, model_block, impl_models=("sonnet", "haiku")):
        """A parked batch whose single phase carries `model_block` after `## Size`, in a repo whose
        settings.json sets implModels."""
        root = self.make_repo(repo)
        (root / ".claude" / "cfq").mkdir(parents=True, exist_ok=True)
        (root / ".claude" / "cfq" / "settings.json").write_text(
            json.dumps({"implModels": list(impl_models)})
        )
        target = self._repos_dir / f"{repo}-target"
        target.touch()
        batch = root / ".claude" / "cfq" / "impl" / "2026-01-05-model"
        batch.mkdir(parents=True)
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        phase = self._valid_phase(target).replace("## Size\nM\n", f"## Size\nM\n{model_block}")
        self._write(batch / "01-a.md", phase)
        self.run_cfq("park", str(root), batch.name, "normal", check=True)
        self.auto_status = False
        return batch

    def test_model_from_implmodels_is_clean(self):
        batch = self._model_batch("modelrepo1", "## Model\nHaiku\n")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)
        self.assertNotIn("model", out)

    def test_model_outside_implmodels_is_reported(self):
        batch = self._model_batch("modelrepo2", "## Model\nopus\n")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn("01-a.md: model: 'opus' is not in implModels (sonnet, haiku)", out)

    def test_empty_model_heading_is_reported(self):
        batch = self._model_batch("modelrepo3", "## Model\n")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn("01-a.md: model: ## Model heading has no value", out)

    def test_phase_without_model_heading_is_clean(self):
        batch = self._model_batch("modelrepo4", "")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)
        self.assertNotIn("model", out)

    def test_unavailable_settings_warn_without_blocking(self):
        """A batch outside any queue layout has no repo to read implModels from."""
        batch = self._repos_dir / "loose" / "2026-01-05-loose"
        batch.mkdir(parents=True)
        target = self._repos_dir / "loose-target"
        target.touch()
        phase = self._valid_phase(target).replace("## Size\nM\n", "## Size\nM\n## Model\nopus\n")
        self._write(batch / "01-a.md", phase)
        _, out = self._lint_out(batch)
        self.assertEqual(out.count("warn: model: implModels unavailable, ## Model not checked"), 1, out)
        self.assertNotIn("01-a.md: model:", out)

    # ---- status.json (batch 051 phase 05) -------------------------------------------------------

    def _status_batch(self, repo, phases=("01-a", "02-b")):
        """A batch parked through a real `bin/cfq park` -- git repo, plan files written first,
        status.json created by park itself."""
        root = self.make_repo(repo)
        target = self._repos_dir / f"{repo}-target"
        target.touch()
        batch = root / ".claude" / "cfq" / "impl" / "2026-01-04-status"
        batch.mkdir(parents=True)
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        for slug in phases:
            self._write(batch / f"{slug}.md", self._valid_phase(target))
        self.run_cfq("park", str(root), batch.name, "normal", check=True)
        self.auto_status = False  # park wrote status.json; a test breaks it on purpose
        return root, batch

    def _valid_phase(self, target):
        return f"""# Phase
## Size
M
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
1. x
## Verification
`bash tests/foo.sh` must exit 0
"""

    def _lint_out(self, batch):
        proc = self.run_cfq("lint", str(batch))
        return proc.returncode, proc.stdout + proc.stderr

    def test_lint_on_a_parked_batch_is_clean(self):
        _, batch = self._status_batch("statusrepo1")
        self.assertTrue((batch / "status.json").is_file(), "park should have written status.json")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)
        self.assertIn("OK 2 phases", out)

    def test_lint_reports_missing_status_file(self):
        _, batch = self._status_batch("statusrepo2")
        (batch / "status.json").unlink()
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{batch.name}: status: missing status.json", out)

    def test_lint_reports_unparsable_status_file(self):
        _, batch = self._status_batch("statusrepo3")
        (batch / "status.json").write_text("{not json")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{batch.name}: status: status.json is not valid JSON", out)

    def test_lint_reports_phase_file_added_after_park(self):
        _, batch = self._status_batch("statusrepo4", phases=("01-a",))
        self._write(batch / "02-b.md", self._valid_phase(self._repos_dir / "statusrepo4-target"))
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{batch.name}: status: 02-b has no status entry", out)
        self.assertNotIn("sections:", out, "the unregistered open file is still linted by location")

    def test_lint_reports_entry_without_file(self):
        _, batch = self._status_batch("statusrepo5")
        (batch / "02-b.md").unlink()
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{batch.name}: status: 02-b entry has no file", out)

    def test_lint_reports_mirror_mismatch(self):
        _, batch = self._status_batch("statusrepo6")
        (batch / "done").mkdir()
        (batch / "02-b.md").rename(batch / "done" / "02-b.md")
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{batch.name}: status: 02-b is open but lies in done/", out)

    def test_skipped_phase_is_not_linted_for_headings_but_still_numbered(self):
        _, batch = self._status_batch("statusrepo7", phases=("01-a", "02-b", "03-c"))
        (batch / "02-b.md").write_text("no headings at all\n")
        write_status(batch, **{"02_b": {"status": "skipped", "reason": "obsolete"}})
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)
        self.assertNotIn("02-b.md", out)
        self.assertNotIn("numbering", out, "a skipped phase must not read as a gap")
        self.assertIn("OK 3 phases", out)

    def test_new_marker_on_existing_path_fires_stale_new(self):
        qdir = self._repos_dir / "lintrepo3" / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        target = self._repos_dir / "existing-target3"
        target.touch()

        newmarker = qdir / "2026-01-03-newmarker"
        newmarker.mkdir()
        (newmarker / ".planning").touch()
        self._write(newmarker / "01-a.md", f"""# Phase A
## Size
M
## Context
x
## Affected Files
- `{target}` (new)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
""")
        proc = self.run_cfq("lint", str(newmarker))
        self.assertNotEqual(proc.returncode, 0, "English (new) marker on an existing path should fail lint")
        out = proc.stdout + proc.stderr
        self.assertIn(": stale-new:", out, f"English (new) marker did not fire stale-new: {out}")
        self.assertNotIn(": priority:", out, f"batch without .priority should not fire priority: {out}")

    # ---- pending creators (batch 054 phase 01) --------------------------------------------------

    def _creator_phase(self, path, new):
        marker = " (new)" if new else ""
        return f"""# Phase
## Size
M
## Context
x
## Affected Files
- `{path}`{marker}
## Changes
1. x
## Verification
`bash tests/foo.sh` must exit 0
"""

    def _creator_batch(self, qdir, name, phases, planning=False, depends=None, statuses=None, done=False):
        """`phases` maps a slug to (path, is_new). A batch for `done=True` lies under `done/`."""
        base = qdir / "done" if done else qdir
        batch = base / name
        batch.mkdir(parents=True)
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        if planning:
            (batch / ".planning").touch()
        if depends:
            (batch / ".dependsOn").write_text("\n".join(depends) + "\n")
        for slug, (path, is_new) in phases.items():
            self._write(batch / f"{slug}.md", self._creator_phase(path, is_new))
        write_status(batch, **(statuses or {}))
        return batch

    def _creator_qdir(self, label):
        qdir = self._repos_dir / label / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        return qdir, self._repos_dir / f"{label}-x.sh"

    def test_creator_in_same_batch_accepts_later_bare_path(self):
        qdir, x = self._creator_qdir("creator1")
        batch = self._creator_batch(
            qdir, "2026-02-01-same", {"01-a": (x, True), "02-b": (x, False)}, planning=True)
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)
        self.assertNotIn(str(x), out)

    def test_creator_in_dependency_batch_accepts_bare_path(self):
        qdir, x = self._creator_qdir("creator2")
        self._creator_batch(qdir, "2026-02-01-a", {"01-a": (x, True)})
        b = self._creator_batch(qdir, "2026-02-02-b", {"01-a": (x, False)}, depends=["2026-02-01-a"])
        code, out = self._lint_out(b)
        self.assertEqual(code, 0, out)
        self.assertNotIn(str(x), out)

    def test_creator_done_and_file_present_is_clean(self):
        qdir, x = self._creator_qdir("creator3")
        x.touch()
        batch = self._creator_batch(
            qdir, "2026-02-01-same", {"01-a": (x, True), "02-b": (x, False)},
            planning=True, statuses={"01-a": "done"})
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)

    def test_creator_done_but_file_absent_fails_naming_the_creator(self):
        qdir, x = self._creator_qdir("creator4")
        batch = self._creator_batch(
            qdir, "2026-02-01-same", {"01-a": (x, True), "02-b": (x, False)},
            statuses={"01-a": "done"})
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"02-b.md: missing: {x} does not exist (created by 01-a, which is done)", out)

    def test_creator_skipped_fails_naming_the_creator(self):
        qdir, x = self._creator_qdir("creator5")
        batch = self._creator_batch(
            qdir, "2026-02-01-same", {"01-a": (x, True), "02-b": (x, False)},
            statuses={"01-a": "skipped"})
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"02-b.md: missing: {x} does not exist (created by 01-a, which is skipped)", out)

    def test_creator_numbered_later_fails_as_running_later(self):
        qdir, x = self._creator_qdir("creator6")
        batch = self._creator_batch(
            qdir, "2026-02-01-same", {"01-a": (x, False), "02-b": (x, True)}, planning=True)
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"01-a.md: missing: {x} does not exist (created by 02-b, which runs later)", out)

    def test_creator_in_skipped_dependency_batch_fails(self):
        qdir, x = self._creator_qdir("creator7")
        a = self._creator_batch(qdir, "2026-02-01-a", {"01-a": (x, True)}, statuses={"01-a": "skipped"})
        b = self._creator_batch(qdir, "2026-02-02-b", {"01-a": (x, False)}, depends=[a.name])
        code, out = self._lint_out(b)
        self.assertEqual(code, 1, out)
        self.assertIn(f"01-a.md: missing: {x} does not exist (created by {a.name}/01-a, which is skipped)", out)

    def test_finished_dependency_batch_and_unclaimed_path_stay_plain_missing(self):
        qdir, x = self._creator_qdir("creator8")
        self._creator_batch(qdir, "2026-02-01-a", {"01-a": (x, True)}, done=True)
        b = self._creator_batch(
            qdir, "2026-02-02-b", {"01-a": (x, False)}, depends=["2026-02-01-a"])
        code, out = self._lint_out(b)
        self.assertEqual(code, 1, out)
        self.assertIn(f"01-a.md: missing: {x} does not exist\n", out)
        self.assertNotIn("created by", out)

    def test_second_marker_in_same_batch_is_duplicate_new(self):
        qdir, x = self._creator_qdir("creator9")
        batch = self._creator_batch(
            qdir, "2026-02-01-same", {"01-a": (x, True), "02-b": (x, True)}, planning=True)
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"02-b.md: duplicate-new: {x} is created by 01-a; list it without (new)", out)
        self.assertNotIn("01-a.md: duplicate-new", out)

    def test_second_marker_across_batches_is_duplicate_new(self):
        qdir, x = self._creator_qdir("creator10")
        a = self._creator_batch(qdir, "2026-02-01-a", {"01-a": (x, True)})
        b = self._creator_batch(qdir, "2026-02-02-b", {"01-a": (x, True)}, depends=[a.name])
        code, out = self._lint_out(b)
        self.assertEqual(code, 1, out)
        self.assertIn(f"01-a.md: duplicate-new: {x} is created by {a.name}/01-a; list it without (new)", out)

    def test_stale_new_on_resume_is_a_warning(self):
        qdir, x = self._creator_qdir("creator11")
        x.touch()
        batch = self._creator_batch(qdir, "2026-02-01-resume", {"01-a": (x, True)})
        code, out = self._lint_out(batch)
        self.assertEqual(code, 0, out)
        self.assertIn(f"warn: 01-a.md: stale-new: {x} already exists", out)
        self.assertNotIn("\n01-a.md: stale-new", "\n" + out)

    def test_stale_new_on_a_later_phase_is_a_finding(self):
        qdir, x = self._creator_qdir("creator12")
        x.touch()
        y = self._repos_dir / "creator12-y.sh"
        batch = self._creator_batch(
            qdir, "2026-02-01-later", {"01-a": (y, True), "02-b": (x, True)})
        code, out = self._lint_out(batch)
        self.assertEqual(code, 1, out)
        self.assertIn(f"02-b.md: stale-new: {x} already exists", out)
        self.assertNotIn(f"warn: 02-b.md: stale-new", out)

    def test_unreadable_status_does_not_crash_the_creator_scan(self):
        qdir, x = self._creator_qdir("creator13")
        x.touch()
        batch = self._creator_batch(qdir, "2026-02-01-nostatus", {"01-a": (x, True)})
        (batch / "status.json").unlink()
        self.auto_status = False
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 1, out)
        self.assertIn(f"{batch.name}: status: missing status.json", out)
        self.assertNotIn("Traceback", proc.stderr)

    def test_batch_context_checks(self):
        qdir = self._repos_dir / "lintrepo4" / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        target = self._repos_dir / "existing-target4"
        target.touch()

        phase_body = f"""# Phase A

## Size

S

## Context
x

## Affected Files
- `{target}` (ändern)

## Changes
x

## Verification

`bash tests/foo.sh` must exit 0
"""

        noctx = qdir / "2026-01-04-noctx"
        noctx.mkdir()
        (noctx / "01-a.md").write_text(phase_body)
        proc = self.run_cfq("lint", str(noctx))
        self.assertNotEqual(proc.returncode, 0, "missing .batch-context.md should fail lint")
        out = proc.stdout + proc.stderr
        self.assertIn(": batch-context: missing .batch-context.md", out, f"missing .batch-context.md not reported: {out}")

        nogoal = qdir / "2026-01-05-nogoal"
        nogoal.mkdir()
        (nogoal / "01-a.md").write_text(phase_body)
        (nogoal / ".batch-context.md").write_text("# Batch Context\n\n## Decisions\nsomething\n")
        proc = self.run_cfq("lint", str(nogoal))
        self.assertNotEqual(proc.returncode, 0, ".batch-context.md without ## Goal should fail lint")
        out = proc.stdout + proc.stderr
        self.assertIn(
            ": batch-context: .batch-context.md missing ## Goal heading", out,
            f"missing ## Goal heading not reported: {out}",
        )

        emptygoal = qdir / "2026-01-06-emptygoal"
        emptygoal.mkdir()
        (emptygoal / "01-a.md").write_text(phase_body)
        (emptygoal / ".batch-context.md").write_text("# Batch Context\n\n## Goal\n\n## Decisions\nx\n")
        proc = self.run_cfq("lint", str(emptygoal))
        self.assertNotEqual(proc.returncode, 0, "empty ## Goal section should fail lint")
        out = proc.stdout + proc.stderr
        self.assertIn(": batch-context: ## Goal section is empty", out, f"empty ## Goal section not reported: {out}")

        goodctx = qdir / "2026-01-07-goodctx"
        goodctx.mkdir()
        (goodctx / "01-a.md").write_text(phase_body)
        (goodctx / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        proc = self.run_cfq("lint", str(goodctx))
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"valid .batch-context.md should pass lint, got {proc.returncode}: {out}")
        self.assertIsNotNone(re.search(r"^OK 1 phases$", out, re.MULTILINE), f"goodctx summary line missing/wrong: {out}")

    def test_missing_title_heading(self):
        qdir = self._repos_dir / "lintrepo5" / ".claude" / "cfq"
        qdir.mkdir(parents=True)
        target = self._repos_dir / "existing-target5"
        target.touch()
        phase_body = f"""## Size
S
## Context
x
## Affected Files
- `{target}` (ändern)
## Changes
x
## Verification
`bash tests/foo.sh` must exit 0
"""

        batch = qdir / "2026-01-08-notitle"
        batch.mkdir()
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nDoes a thing.\n")
        (batch / "01-a.md").write_text(phase_body)

        proc = self.run_cfq("lint", str(batch))
        self.assertNotEqual(proc.returncode, 0, "phase file without a # heading should fail lint")
        out = proc.stdout + proc.stderr
        self.assertIn("01-a.md: title: missing # heading", out, f"missing title finding not reported: {out}")

        # a done phase file without a title is never inspected for sections at all -- no finding
        done = batch / "done"
        done.mkdir()
        (done / "02-b.md").write_text(phase_body)
        proc = self.run_cfq("lint", str(batch))
        out = proc.stdout + proc.stderr
        self.assertNotIn("02-b.md:", out, f"done phase file content should never be linted: {out}")


class TestPhaseTemplate(PhaseDirsStatus, CfqTestCase):
    """`references/phase-template.md` stays in the form `bin/cfq lint` and `bin/cfq brief` read."""
    TITLE = "<Imperative one-sentence title, no phase number>"
    EXISTING = "`<absolute path of an existing file>`"
    NEW = "`<absolute path of a new file>` (new)"

    def _template(self):
        text = (PLUGIN_ROOT / "references" / "phase-template.md").read_text()
        for placeholder in (self.TITLE, self.EXISTING, self.NEW):
            self.assertIn(placeholder, text, f"placeholder missing from phase-template.md: {placeholder}")
        return text

    def _batch(self, text, name="007-2026-02-01-template"):
        existing = self._repos_dir / "existing-target"
        existing.touch()
        text = text.replace(self.EXISTING, f"`{existing}`")
        text = text.replace(self.NEW, f"`{self._repos_dir / 'not-yet-there'}` (new)")
        batch = self._repos_dir / name
        batch.mkdir()
        (batch / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nExample.\n")
        (batch / "01-example.md").write_text(text)
        return batch

    def test_template_copy_lints_clean(self):
        batch = self._batch(self._template())
        proc = self.run_cfq("lint", str(batch))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("01-example.md", proc.stdout + proc.stderr)

    def test_template_title_and_size_are_read_by_brief(self):
        template = self._template()
        size = re.search(r"^## Size\n\n(\S+)\n", template, re.MULTILINE).group(1)
        out = self.run_cfq("brief", str(self._batch(template)), "--overview", check=True).stdout
        title = self.TITLE[2:] if self.TITLE.startswith("# ") else self.TITLE
        self.assertRegex(out, rf"01\s+{re.escape(title)}\s+{re.escape(size)}\s", out)

    def test_template_copy_without_a_required_heading_fails_lint(self):
        template = self._template()
        for heading in ("Size", "Context", "Affected Files", "Changes", "Verification"):
            with self.subTest(heading=heading):
                self.assertIn(f"\n## {heading}\n", template)
                batch = self._batch(
                    template.replace(f"\n## {heading}\n", "\n## Other\n"),
                    name=f"007-2026-02-01-no-{heading.lower().replace(' ', '-')}",
                )
                proc = self.run_cfq("lint", str(batch))
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertIn(f"missing {heading} heading", proc.stdout + proc.stderr)


class TestSecurity(CfqTestCase):
    def _plain_repo(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        return d

    def test_forge_detection(self):
        secrepo = self._plain_repo("secrepo")

        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:acme/widget.git"], cwd=secrepo, check=True,
        )
        proc = self.run_cfq("security", str(secrepo), env={"CFQ_SECURITY_DETECT_ONLY": "1"})
        self.assertEqual(proc.stdout.strip(), "github github.com acme/widget", f"git@ form -> {proc.stdout}")

        subprocess.run(
            ["git", "remote", "set-url", "origin", "https://github.com/acme/widget.git"], cwd=secrepo, check=True,
        )
        proc = self.run_cfq("security", str(secrepo), env={"CFQ_SECURITY_DETECT_ONLY": "1"})
        self.assertEqual(proc.stdout.strip(), "github github.com acme/widget", f"https form -> {proc.stdout}")

        subprocess.run(
            ["git", "remote", "set-url", "origin", "ssh://git@forge.example:10022/team/widget.git"],
            cwd=secrepo, check=True,
        )
        proc = self.run_cfq("security", str(secrepo), env={"CFQ_SECURITY_DETECT_ONLY": "1"})
        self.assertEqual(proc.stdout.strip(), "unknown forge.example team/widget", f"ssh form (no login) -> {proc.stdout}")
        proc = self.run_cfq(
            "security", str(secrepo),
            env={"CFQ_SECURITY_DETECT_ONLY": "1", "CFQ_TEA_LOGIN_HOSTS": "forge.example"},
        )
        self.assertEqual(proc.stdout.strip(), "gitea forge.example team/widget", f"ssh form (with login) -> {proc.stdout}")

        subprocess.run(
            ["git", "remote", "set-url", "origin", "http://forge.example/team/widget.git"], cwd=secrepo, check=True,
        )
        proc = self.run_cfq("security", str(secrepo), env={"CFQ_SECURITY_DETECT_ONLY": "1"})
        self.assertEqual(proc.stdout.strip(), "unknown forge.example team/widget", f"http form -> {proc.stdout}")

        subprocess.run(
            ["git", "remote", "set-url", "origin", "https://ghe.example/team/widget.git"], cwd=secrepo, check=True,
        )
        proc = self.run_cfq(
            "security", str(secrepo),
            env={"CFQ_SECURITY_DETECT_ONLY": "1", "CFQ_GH_LOGIN_HOSTS": "ghe.example"},
        )
        self.assertEqual(proc.stdout.strip(), "github ghe.example team/widget", f"gh login -> {proc.stdout}")
        proc = self.run_cfq(
            "security", str(secrepo),
            env={"CFQ_SECURITY_DETECT_ONLY": "1", "CFQ_GH_LOGIN_HOSTS": "ghe.example",
                 "CFQ_TEA_LOGIN_HOSTS": "ghe.example"},
        )
        self.assertEqual(proc.stdout.strip(), "github ghe.example team/widget", f"gh beats tea -> {proc.stdout}")

        subprocess.run(
            ["git", "remote", "set-url", "origin", "git@gitlab.example:group/sub/widget.git"],
            cwd=secrepo, check=True,
        )
        proc = self.run_cfq(
            "security", str(secrepo),
            env={"CFQ_SECURITY_DETECT_ONLY": "1", "CFQ_GLAB_LOGIN_HOSTS": "gitlab.example"},
        )
        self.assertEqual(
            proc.stdout.strip(), "gitlab gitlab.example group/sub/widget", f"glab login -> {proc.stdout}",
        )
        proc = self.run_cfq(
            "security", str(secrepo),
            env={"CFQ_SECURITY_DETECT_ONLY": "1", "CFQ_GLAB_LOGIN_HOSTS": "gitlab.example",
                 "CFQ_TEA_LOGIN_HOSTS": "gitlab.example"},
        )
        self.assertEqual(
            proc.stdout.strip(), "gitlab gitlab.example group/sub/widget", f"glab beats tea -> {proc.stdout}",
        )

        subprocess.run(["git", "remote", "remove", "origin"], cwd=secrepo, check=True)
        proc = self.run_cfq("security", str(secrepo), env={"CFQ_SECURITY_DETECT_ONLY": "1"})
        self.assertEqual(proc.stdout.strip(), "none - -", f"no remote -> {proc.stdout}")

    def test_full_run_no_sources(self):
        secrepo = self._plain_repo("secrepo")
        proc = self.run_cfq("security", str(secrepo))
        self.assertEqual(proc.returncode, 0, f"security exit code = {proc.returncode}, want 0")
        out = self.json_out(proc)
        self.assertFalse(out["available"], f"no-source security output = {out}")
        self.assertEqual(len(out["sources"]), 0, f"no-source security output = {out}")
        self.assertTrue(len(out["hint"]) > 0, f"no-source security output = {out}")

    def test_manifest_only_no_lockfile(self):
        mfrepo = self._plain_repo("mfrepo")
        (mfrepo / "package.json").write_text('{"name":"x","version":"1.0.0"}')
        proc = self.run_cfq("security", str(mfrepo))
        self.assertEqual(proc.returncode, 0, f"manifest-only security exit code = {proc.returncode}, want 0")
        out = self.json_out(proc)
        self.assertIsInstance(out, dict, f"manifest-only security output is not valid JSON: {proc.stdout}")

    def test_security_findings_cap(self):
        # securityFindingsCap actually reaches cfq_security.py's behavior: a synthetic npm-audit
        # fixture producing more findings than a lowered cap gets truncated to it.
        capfixture = self._repos_dir / "capfixture"
        (capfixture / "bin").mkdir(parents=True)
        (capfixture / "package.json").write_text('{"name":"x","version":"1.0.0"}')
        npm_stub = capfixture / "bin" / "npm"
        npm_stub.write_text("""#!/usr/bin/env bash
if [ "$1" = "audit" ]; then
  jq -n '{vulnerabilities: {a:{severity:"high",fixAvailable:false}, b:{severity:"high",fixAvailable:false},
    c:{severity:"low",fixAvailable:false}, d:{severity:"low",fixAvailable:false}}}'
  exit 0
fi
exit 0
""")
        npm_stub.chmod(0o755)

        self.run_cfq("settings", "set", "securityFindingsCap", "2")
        proc = self.run_cfq(
            "security", str(capfixture),
            env={"PATH": f"{capfixture / 'bin'}:{os.environ.get('PATH', '')}"},
        )
        self.assertEqual(proc.returncode, 0, f"capped security exit code = {proc.returncode}, want 0")
        out = self.json_out(proc)
        self.assertEqual(len(out["findings"]), 2, f"securityFindingsCap=2 not applied, findings = {out['findings']}")

    def _stub_repo(self, name, remote, gh_script=None, glab_script=None):
        d = self._plain_repo(name)
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=d, check=True)
        (d / "bin").mkdir()
        for tool, script in (("gh", gh_script), ("glab", glab_script)):
            if script is not None:
                stub = d / "bin" / tool
                stub.write_text(script)
                stub.chmod(0o755)
        return d

    def _run_stubbed(self, d, **extra_env):
        env = {"PATH": f"{d / 'bin'}:{os.environ.get('PATH', '')}"}
        env.update(extra_env)
        proc = self.run_cfq("security", str(d), env=env)
        self.assertEqual(proc.returncode, 0, f"security exit code = {proc.returncode}, want 0")
        return self.json_out(proc)

    def test_github_enterprise_host(self):
        gh_script = """#!/usr/bin/env bash
echo "$@" >> "$(dirname "$0")/gh.log"
case "$*" in
  *dependabot/alerts*)
    echo '[{"dependency":{"package":{"name":"lodash"}},"security_advisory":{"severity":"high"},"security_vulnerability":{"first_patched_version":{"identifier":"4.17.21"}}}]';;
  *code-scanning/alerts*) echo '[]';;
  *" user") echo '{}';;
esac
exit 0
"""
        d = self._stub_repo("ghe", "https://ghe.example/team/widget.git", gh_script=gh_script)
        out = self._run_stubbed(d, CFQ_GH_LOGIN_HOSTS="ghe.example")
        self.assertEqual(out["forge"], "github", f"GHE output = {out}")
        self.assertIn("dependabot", out["sources"], f"GHE output = {out}")
        self.assertEqual(out["fixable"].get("high"), 1, f"GHE output = {out}")
        calls = [ln for ln in (d / "bin" / "gh.log").read_text().splitlines() if ln.startswith("api")]
        self.assertTrue(len(calls) >= 3, f"gh calls = {calls}")
        for call in calls:
            self.assertIn("--hostname ghe.example", call, f"gh call without the host: {call}")

    def test_gitlab_host(self):
        glab_script = """#!/usr/bin/env bash
case "$*" in
  *projects/group%2Fsub%2Fwidget/vulnerabilities*)
    echo '[{"title":"A","severity":"critical"},{"title":"B","severity":"info"}]';;
  *" user") echo '{}';;
esac
exit 0
"""
        d = self._stub_repo("gl", "git@gitlab.example:group/sub/widget.git", glab_script=glab_script)
        out = self._run_stubbed(d, CFQ_GLAB_LOGIN_HOSTS="gitlab.example")
        self.assertEqual(out["forge"], "gitlab", f"GitLab output = {out}")
        self.assertIn("gitlab", out["sources"], f"GitLab output = {out}")
        self.assertEqual(out["counts"], {"critical": 1, "info": 1}, f"GitLab output = {out}")
        self.assertEqual(out["fixable"], {}, f"GitLab output = {out}")

    def test_gitlab_without_vulnerability_api(self):
        glab_script = """#!/usr/bin/env bash
case "$*" in
  *vulnerabilities*) exit 1;;
esac
exit 0
"""
        d = self._stub_repo("gl2", "git@gitlab.example:group/sub/widget.git", glab_script=glab_script)
        out = self._run_stubbed(d, CFQ_GLAB_LOGIN_HOSTS="gitlab.example")
        self.assertFalse(out["available"], f"GitLab without API output = {out}")
        self.assertEqual(out["forge"], "gitlab", f"GitLab without API output = {out}")
        self.assertIn("GitLab Ultimate", out["hint"], f"GitLab without API output = {out}")
        self.assertIn("local audit is the only source", out["hint"], f"GitLab without API output = {out}")

    def test_unknown_host_hint_names_all_logins(self):
        d = self._stub_repo("unk", "https://nowhere.example/team/widget.git")
        out = self._run_stubbed(d, CFQ_GH_LOGIN_HOSTS="x.invalid", CFQ_GLAB_LOGIN_HOSTS="x.invalid",
                                CFQ_TEA_LOGIN_HOSTS="x.invalid")
        self.assertFalse(out["available"], f"unknown host output = {out}")
        self.assertEqual(out["forge"], "unknown", f"unknown host output = {out}")
        for needle in (
            "gh auth login --hostname nowhere.example",
            "glab auth login --hostname nowhere.example",
            "tea login add --url nowhere.example",
        ):
            self.assertIn(needle, out["hint"], f"unknown host hint = {out['hint']}")


class TestLang(CfqTestCase):
    def _plain_repo(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_doc_tree_drift(self):
        langrepo = self._plain_repo("langrepo")
        (langrepo / "docs" / "en").mkdir(parents=True)
        (langrepo / "docs" / "en" / "a.md").write_text("# a\n")

        proc = self.run_cfq("lang", str(langrepo), env={"CFQ_DOC_LANGUAGES": "de"})
        out = self.json_out(proc)
        self.assertEqual(out["missing"], ["docs/de/a.md"], f"missing translation not reported: {out}")

        (langrepo / "docs" / "de").mkdir()
        (langrepo / "docs" / "de" / "a.md").write_text("# a\n")
        proc = self.run_cfq("lang", str(langrepo), env={"CFQ_DOC_LANGUAGES": "de"})
        out = self.json_out(proc)
        self.assertEqual(out["missing"], [], f"missing should be empty once translated: {out}")

        (langrepo / "docs" / "de" / "nur-hier.md").write_text("# nur hier\n")
        proc = self.run_cfq("lang", str(langrepo), env={"CFQ_DOC_LANGUAGES": "de"})
        out = self.json_out(proc)
        self.assertEqual(out["stray"], ["docs/de/nur-hier.md"], f"stray file not reported: {out}")

        (langrepo / "docs" / "intro.md").write_text("# intro\n")
        proc = self.run_cfq("lang", str(langrepo), env={"CFQ_DOC_LANGUAGES": "de"})
        out = self.json_out(proc)
        self.assertEqual(out["unfiled"], ["docs/intro.md"], f"unfiled file not reported: {out}")

    def test_minimal_doc_level(self):
        minimalrepo = self._plain_repo("minimalrepo")
        proc = self.run_cfq("lang", str(minimalrepo), env={"CFQ_DOC_LEVEL": "minimal"})
        self.assertEqual(proc.returncode, 0, f"minimal/no-docs should exit 0, got {proc.returncode}")
        out = self.json_out(proc)
        self.assertEqual(out["missing"], [], f"minimal/no-docs output wrong: {out}")
        self.assertEqual(out["stray"], [], f"minimal/no-docs output wrong: {out}")
        self.assertEqual(out["unfiled"], [], f"minimal/no-docs output wrong: {out}")
        self.assertTrue(len(out["note"]) > 0, f"minimal/no-docs output wrong: {out}")

    def test_changed_ref_non_git_dir(self):
        minimalrepo = self._plain_repo("minimalrepo")
        proc = self.run_cfq("lang", str(minimalrepo), "--changed", "HEAD")
        self.assertEqual(proc.returncode, 0, f"--changed in a non-git dir should exit 0, got {proc.returncode}")
        out = self.json_out(proc)
        self.assertEqual(out["scope"], "repo", f"--changed in a non-git dir should fall back to scope repo: {out}")

    def test_prose_mode(self):
        proserepo = self._plain_repo("proserepo")
        subprocess.run(["git", "init", "-q"], cwd=proserepo, check=True)
        (proserepo / "f.txt").write_text("line one\nline two\n")
        subprocess.run(["git", "add", "f.txt"], cwd=proserepo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "-m", "base commit"],
            cwd=proserepo, check=True,
        )
        base_ref = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=proserepo, check=True, capture_output=True, text=True,
        ).stdout.strip()

        lines = (proserepo / "f.txt").read_text().splitlines()[1:]
        lines.append("added line")
        (proserepo / "f.txt").write_text("\n".join(lines) + "\n")
        subprocess.run(["git", "add", "f.txt"], cwd=proserepo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "-m",
             "small change with added line"],
            cwd=proserepo, check=True,
        )

        proc = self.run_cfq("lang", "prose", str(proserepo), base_ref)
        out = self.json_out(proc)
        self.assertFalse(out["truncated"], f"small commit should not be truncated: {out}")
        self.assertIn("added line", out["sample"], f"added line missing from sample: {out}")
        self.assertNotIn("line one", out["sample"], f"removed line leaked into sample: {out}")
        self.assertIn(
            "small change with added line", out["sample"], f"commit message missing from sample: {out}",
        )

        small_ref = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=proserepo, check=True, capture_output=True, text=True,
        ).stdout.strip()
        padding = "\n".join(
            f"padding line number {i} to blow the cap with some extra filler text" for i in range(1, 401)
        )
        with (proserepo / "f.txt").open("a") as fh:
            fh.write(padding + "\n")
        subprocess.run(["git", "add", "f.txt"], cwd=proserepo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "-m", "big change"],
            cwd=proserepo, check=True,
        )

        proc = self.run_cfq("lang", "prose", str(proserepo), small_ref)
        out = self.json_out(proc)
        self.assertTrue(out["truncated"], f"big commit should be truncated: {out}")
        self.assertLessEqual(len(out["sample"].encode()), 8192, "sample exceeds byte cap")

        nogitdir = self._plain_repo("nogitdir")
        proc = self.run_cfq("lang", "prose", str(nogitdir), "HEAD")
        self.assertEqual(proc.returncode, 0, f"prose on non-git dir should exit 0, got {proc.returncode}")
        out = self.json_out(proc)
        self.assertEqual(out["sample"], "", f"non-git prose output wrong: {out}")
        self.assertTrue(len(out["note"]) > 0, f"non-git prose output wrong: {out}")

        proc = self.run_cfq("lang", str(proserepo))
        out = self.json_out(proc)
        self.assertEqual(
            sorted(out.keys()),
            sorted(["codeLanguage", "docLanguages", "docLevel", "missing", "note", "scope", "stray", "unfiled"]),
            f"unchanged invocation key set changed: {out}",
        )

    def test_prose_reads_the_repository_i18n_patterns(self):
        proserepo = self._plain_repo("prose-tier")
        subprocess.run(["git", "init", "-q"], cwd=proserepo, check=True)
        (proserepo / "base.txt").write_text("base\n")
        subprocess.run(["git", "add", "."], cwd=proserepo, check=True)
        commit = ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-q", "-m"]
        subprocess.run([*commit, "base"], cwd=proserepo, check=True)
        base_ref = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=proserepo, check=True, capture_output=True, text=True,
        ).stdout.strip()
        (proserepo / "notes").mkdir()
        (proserepo / "notes" / "only.txt").write_text("MARKER-ONLY-IN-NOTES\n")
        subprocess.run(["git", "add", "."], cwd=proserepo, check=True)
        subprocess.run([*commit, "add notes"], cwd=proserepo, check=True)

        before = self.json_out(self.run_cfq("lang", "prose", str(proserepo), base_ref))
        self.assertIn("MARKER-ONLY-IN-NOTES", before["sample"], f"fixture file missing from sample: {before}")

        self.run_cfq("settings", "set", "--repo", str(proserepo), "i18nExcludePatterns", "*/notes/*", check=True)
        after = self.json_out(self.run_cfq("lang", "prose", str(proserepo), base_ref))
        self.assertNotIn(
            "MARKER-ONLY-IN-NOTES", after["sample"], f"repo-level i18nExcludePatterns ignored: {after}",
        )

    def test_tree_reads_the_repository_doc_level(self):
        # Global docLevel is standard, the repository says minimal: the note proves the
        # repository value was read.
        treerepo = self._plain_repo("tree-tier")
        self.run_cfq("settings", "set", "docLevel", "standard", check=True)
        self.run_cfq("settings", "set", "--repo", str(treerepo), "docLevel", "minimal", check=True)
        out = self.json_out(self.run_cfq("lang", str(treerepo)))
        self.assertEqual(out["docLevel"], "minimal", f"repo-level docLevel ignored: {out}")
        self.assertEqual(
            out["note"], "docLevel=minimal, no docs tree expected", f"minimal note missing: {out}",
        )


class TestMaintenance(CfqTestCase):
    def test_due_stamp_lifecycle(self):
        maintrepo = self._repos_dir / "maintrepo"
        maintrepo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=maintrepo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=maintrepo, check=True,
        )

        proc = self.run_cfq("maintenance", "due", str(maintrepo))
        self.assertEqual(proc.stdout.strip(), "DUE 0", f"no marker -> '{proc.stdout.strip()}', want 'DUE 0'")

        self.run_cfq("maintenance", "stamp", str(maintrepo))
        proc = self.run_cfq("maintenance", "due", str(maintrepo))
        self.assertEqual(
            proc.stdout.strip(), "NOT_DUE 0", f"stamp then due -> '{proc.stdout.strip()}', want 'NOT_DUE 0'",
        )

        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "--allow-empty", "-q", "-m", "c1"],
            cwd=maintrepo, check=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "--allow-empty", "-q", "-m", "c2"],
            cwd=maintrepo, check=True,
        )
        proc = self.run_cfq("maintenance", "due", str(maintrepo), env={"CFQ_MAINTENANCE_EVERY": "2"})
        self.assertEqual(proc.stdout.strip(), "DUE 2", f"2 commits, every=2 -> '{proc.stdout.strip()}', want 'DUE 2'")

        proc = self.run_cfq("maintenance", "due", str(maintrepo), env={"CFQ_MAINTENANCE_EVERY": "50"})
        self.assertEqual(
            proc.stdout.strip(), "NOT_DUE 2", f"2 commits, every=50 -> '{proc.stdout.strip()}', want 'NOT_DUE 2'",
        )

        marker = maintrepo / ".claude" / "cfq" / ".maintenance"
        marker.write_text("2020-01-01 0000000\n")
        proc = self.run_cfq("maintenance", "due", str(maintrepo))
        self.assertTrue(
            proc.stdout.strip().startswith("DUE"), f"garbage sha -> '{proc.stdout.strip()}', want DUE*",
        )

        marker.write_text("2020-01-01\n")
        proc = self.run_cfq("maintenance", "due", str(maintrepo))
        self.assertTrue(
            proc.stdout.strip().startswith("DUE"), f"empty sha -> '{proc.stdout.strip()}', want DUE*",
        )

        self.run_cfq("maintenance", "stamp", str(maintrepo))
        before = marker.read_text()
        proc = self.run_cfq("maintenance", "due", str(maintrepo), env={"CFQ_MAINTENANCE_EVERY": "0"})
        self.assertEqual(proc.stdout.strip(), "OFF", f"maintenanceEvery=0 -> '{proc.stdout.strip()}', want 'OFF'")
        after = marker.read_text()
        self.assertEqual(before, after, "OFF must not touch the marker")

    def test_due_reads_the_repository_tier(self):
        # The repository value differs from the global one (default 50) and the automatic lookup
        # is off: the answer can only come from the repository passed on the command line.
        maintrepo = self._repos_dir / "maintrepo-tier"
        maintrepo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=maintrepo, check=True)
        self.run_cfq("settings", "set", "--repo", str(maintrepo), "maintenanceEvery", "0", check=True)
        proc = self.run_cfq("maintenance", "due", str(maintrepo))
        self.assertEqual(
            proc.stdout.strip(), "OFF", f"repo-level maintenanceEvery=0 ignored -> '{proc.stdout.strip()}'",
        )


class TestCommandFiles(CfqTestCase):
    def _files(self):
        return sorted((PLUGIN_ROOT / "commands").iterdir())

    def test_only_markdown(self):
        for f in self._files():
            with self.subTest(file=f.name):
                self.assertEqual(f.suffix, ".md", f"commands/{f.name} is not Markdown")

    def test_expected_set(self):
        self.assertEqual({f.stem for f in self._files()}, {"cfq", "pfq", "ifq"})

    def test_no_command_shares_a_skill_name(self):
        skills = {d.name for d in (PLUGIN_ROOT / "skills").iterdir() if d.is_dir()}
        for f in self._files():
            with self.subTest(file=f.name):
                self.assertNotIn(f.stem, skills, f"commands/{f.name} shares a skill's name")

    def test_frontmatter_description(self):
        for f in self._files():
            with self.subTest(file=f.name):
                text = f.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"), f"{f.name} has no frontmatter")
                front = text.split("---\n", 2)[1]
                desc = [l for l in front.splitlines() if l.startswith("description:")]
                self.assertTrue(desc and desc[0][len("description:"):].strip(),
                                f"{f.name} has no non-empty description")

    def test_bodies_route_to_their_skill(self):
        commands_dir = PLUGIN_ROOT / "commands"
        pfq = (commands_dir / "pfq.md").read_text(encoding="utf-8")
        ifq = (commands_dir / "ifq.md").read_text(encoding="utf-8")
        self.assertIn("plan-for-queue skill", pfq)
        self.assertIn("implement-for-queue skill", ifq)
        self.assertIn("resume", ifq)
        self.assertIn("start", ifq)
        for name, text in (("pfq.md", pfq), ("ifq.md", ifq)):
            with self.subTest(file=name):
                self.assertEqual(text.rstrip("\n").splitlines()[-1], "$ARGUMENTS")


if __name__ == "__main__":
    unittest.main()
