"""Migrated from test-dash.sh.

Self-test for scripts/cfq_dash.py: repo rollup, thisRepo scoping, the settings marker
mapping (default/global/repo/env source and masked-value display), and the `THIS REPO` render
block (open-batches-only, `--all`, and the expanded next batch).
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

from cfq_testlib import CfqTestCase, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_dash  # noqa: E402

# The seven capability rows the ACTIONS section names (Step C's six actions plus Step D's
# settings change) -- kept as one list so the drift guard below can check both directions: every
# keyword must show up in the rendered dashboard AND in references/dashboard.md's own prose.
ACTION_KEYWORDS = [
    "priority",
    "delete a batch",
    "archive a batch",
    "registry",
    "dependency",
    "todo",
    "setting",
    "rfq",
]

DASHBOARD_MD = Path(__file__).resolve().parents[1] / "references" / "dashboard.md"


class TestDash(CfqTestCase):
    def _plain_repo(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)

    def _phase_file(self, path, title, size="M"):
        path.write_text(
            f"# {title}\n\n## Size\n\n{size}\n\n## Context\n\nContext sentence one. Context sentence two.\n"
        )

    def _open_batch(self, repo, name, open_nums=("01",), done_nums=(), priority=None, depends_on=None, sizes=None):
        """Batch dir under impl/<name>: `open_nums` become open NN-*.md phases, `done_nums`
        become ticked ones under done/. `sizes` maps a phase num to its `## Size` value."""
        sizes = sizes or {}
        bdir = repo / ".claude" / "cfq" / "impl" / name
        bdir.mkdir(parents=True, exist_ok=True)
        for num in open_nums:
            self._phase_file(bdir / f"{num}-phase.md", f"Phase {num}", size=sizes.get(num, "M"))
        if done_nums:
            (bdir / "done").mkdir(exist_ok=True)
            for num in done_nums:
                self._phase_file(bdir / "done" / f"{num}-phase.md", f"Phase {num}", size=sizes.get(num, "M"))
        if priority:
            (bdir / ".priority").write_text(priority)
        if depends_on:
            (bdir / ".dependsOn").write_text(depends_on + "\n")
        return bdir

    def _archived_batch(self, repo, name, phases=1):
        bdir = repo / ".claude" / "cfq" / "impl" / "done" / name
        bdir.mkdir(parents=True, exist_ok=True)
        for i in range(1, phases + 1):
            (bdir / f"{i:02d}-phase.md").touch()
        return bdir

    def test_repo_rollup_and_render(self):
        tmp = self._repos_dir / "dashroot"

        # repo-a: registered, one open batch (high priority, 1 open + 1 done phase). A real git
        # repo so cfq_dash.py's git rev-parse resolves it as "this repo" when cwd is inside it.
        repo_a = tmp / "repo-a"
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "done").mkdir(parents=True)
        self._plain_repo(repo_a)
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "01-a.md").touch()
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / "done" / "00-x.md").touch()
        (repo_a / ".claude" / "cfq" / "impl" / "2026-01-01-demo" / ".priority").write_text("high")

        # repo-b: registered, no batches at all -- the rollup must read OK, never crash on empty
        # batches.
        repo_b = tmp / "repo-b"
        (repo_b / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo_b)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}

        # 1. Two registered repos, one with an open batch -> .repos has exactly two entries, each
        # appearing once, counters matching what was created on disk.
        out = self.json_out(self.run_cfq("dash", env=env))
        self.assertEqual(out["status"], "OK", f"status = {out['status']}")
        self.assertEqual(len(out["repos"]), 2, f"repos length = {len(out['repos'])}")
        a = [r for r in out["repos"] if r["path"] == str(repo_a)]
        self.assertEqual(len(a), 1, f"repo-a should appear exactly once, got {a}")
        self.assertEqual(
            {k: a[0][k] for k in ("open", "done", "status")}, {"open": 1, "done": 0, "status": "IN_PROGRESS"},
            f"repo-a rollup = {a[0]}",
        )
        b = [r for r in out["repos"] if r["path"] == str(repo_b)][0]
        self.assertEqual(
            {k: b[k] for k in ("open", "done", "status")}, {"open": 0, "done": 0, "status": "OK"},
            f"repo-b rollup = {b}",
        )

        # 1b. `render` is additive, not a substitute: same fixture, JSON default above is
        # untouched, and the terminal render mentions both repos. Deep render coverage (tables,
        # MULTIPLE_IN_PROGRESS, equivalence, no-HTML-entity) lives in test_render.py, not
        # duplicated here.
        rendered = self.run_cfq("dash", "render", str(tmp), env=env).stdout
        self.assertIn("repo-a", rendered, "render output missing repo-a")
        self.assertIn("repo-b", rendered, "render output missing repo-b")

        # 2. Run from inside a registered repo -> .thisRepo.batches lists that repo's batches only.
        out_inside = self.json_out(self.run_cfq("dash", cwd=str(repo_a), env=env))
        this = [b["name"] for b in out_inside["thisRepo"]["batches"]]
        self.assertEqual(this, ["2026-01-01-demo"], f"thisRepo.batches = {this}")

        # 3. Run from a directory that is not a registered repo -> .thisRepo is null, .repos
        # still populated, status still OK.
        outside = self._repos_dir / "outside"
        self._plain_repo(outside)
        out_outside = self.json_out(self.run_cfq("dash", cwd=str(outside), env=env))
        self.assertIsNone(out_outside["thisRepo"], "thisRepo should be null outside a registered repo")
        self.assertEqual(len(out_outside["repos"]), 2, "repos should stay populated")
        self.assertEqual(out_outside["status"], "OK", f"status should stay OK, got {out_outside['status']}")

        # 4. No repos at all -> status NO_REPO, empty .repos, no crash. A fresh HOME, not
        # self.home -- repo-a/repo-b got registered into self.home's registry above, and the scan
        # unions the registry with CFQ_SCAN_ROOTS, so reusing self.home would still find them.
        empty_root = self._repos_dir / "empty-root"
        empty_root.mkdir()
        empty_home = self._repos_dir / "empty-home"
        empty_home.mkdir()
        out_empty = self.json_out(
            self.run_cfq("dash", home=empty_home, env={"CFQ_SCAN_ROOTS": str(empty_root)}),
        )
        self.assertEqual(out_empty["status"], "NO_REPO", f"empty status = {out_empty['status']}")
        self.assertEqual(out_empty["repos"], [], f"empty repos = {out_empty['repos']}")

    def test_precheck_lines_column_position_pinned(self):
        # Phase 09: pins the exact `<icon> <label:<16>><detail>` bytes PRECHECKS prints today --
        # both literals below are hand-composed with Python's own `:<16` format spec, never built
        # via `cfq_lib.text`, so a real drift in cfq_dash.py's own formatting cannot pass by
        # construction.
        tmp = self._repos_dir / "preroot"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-08-01-a")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout
        lines = rendered.splitlines()

        dash_line_text = next(l for l in lines if re.match(r"^(✅|⚠️) Dash\b", l))
        self.assertEqual(dash_line_text, f"✅ {'Dash':<16}1 repos · 1 with open work")

        plugins_line_text = next(l for l in lines if re.match(r"^(✅|➖|⚠️) Plugins\b", l))
        self.assertEqual(
            plugins_line_text, f"➖ {'Plugins':<16}mattpocock-skills/ponytail not installed",
        )

    def test_settings_marker_mapping(self):
        # 5. Marker mapping, one case per --sources value (default/global/repo/env:process), plus
        # the env:process must-fall-back to the masked file value (not just the env value), plus
        # env:repo-legacy.
        mroot = self._repos_dir / "mroot"
        mfixture = mroot / "mfixture"
        (mfixture / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(mfixture)

        def run_dash(env=None):
            merged = {"CFQ_SCAN_ROOTS": str(mroot)}
            if env:
                merged.update(env)
            return self.json_out(self.run_cfq("dash", cwd=str(mfixture), env=merged))

        def key_row(key, out):
            return next(s for s in out["settings"] if s["key"] == key)

        d = key_row("maintenanceEvery", run_dash())
        self.assertEqual(d["marker"], "D", f"default marker = {d}")

        self.run_cfq("settings", "set", "maintenanceEvery", "20")
        g = key_row("maintenanceEvery", run_dash())
        self.assertEqual(g["marker"], "G", f"global marker = {g}")

        self.run_cfq("settings", "set", "--repo", str(mfixture), "maintenanceEvery", "5")
        r = key_row("maintenanceEvery", run_dash())
        self.assertEqual(r["marker"], "R", f"repo marker = {r}")

        envp = key_row("maintenanceEvery", run_dash(env={"CFQ_MAINTENANCE_EVERY": "99"}))
        self.assertEqual(envp["marker"], "E", f"env:process marker = {envp}")

        self.run_cfq("settings", "set", "--repo", str(mfixture), "docLevel", "standard")
        envd = key_row("docLevel", run_dash(env={"CFQ_DOC_LEVEL": "minimal"}))
        self.assertEqual(envd["value"], "minimal", f"docLevel effective value = {envd}")
        self.assertEqual(
            envd["maskedValue"], "standard",
            f"docLevel maskedValue must be the repo file value, not just the env value, got {envd}",
        )
        self.assertEqual(envd["maskedSource"], "repo", f"docLevel maskedSource = {envd}")

        (mfixture / ".claude" / "settings.json").write_text('{"env":{"CFQ_DOC_LEVEL":"minimal"}}')
        envl = key_row("docLevel", run_dash(env={"CFQ_DOC_LEVEL": "minimal"}))
        self.assertEqual(envl["marker"], "E", f"env:repo-legacy marker = {envl}")
        self.assertEqual(envl["source"], "env:repo-legacy", f"env:repo-legacy source = {envl}")

    def test_this_repo_open_only_and_next_expanded(self):
        # routine: one open batch among three archived ones -> exactly one table row, a "N
        # batches done" summary, and the open batch expanded (it's the only /ifq candidate).
        tmp = self._repos_dir / "focusroot"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-02-01-open")
        for n in ("2026-01-01-a", "2026-01-02-b", "2026-01-03-c"):
            self._archived_batch(repo, n)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertIn("| 2026-02-01-open |", rendered, f"open batch row missing:\n{rendered}")
        for n in ("2026-01-01-a", "2026-01-02-b", "2026-01-03-c"):
            self.assertNotIn(n, rendered, f"archived batch {n} should not appear:\n{rendered}")
        self.assertIn("3 batches done", rendered, f"summary line missing:\n{rendered}")
        self.assertIn(
            "2026-02-01-open (next in order)", rendered, f"expanded header missing:\n{rendered}"
        )

    def test_this_repo_nothing_open(self):
        # nothing open: table and expansion both disappear, only the summary remains.
        tmp = self._repos_dir / "nothingopen"
        repo = tmp / "repo"
        self._plain_repo(repo)
        for n in ("2026-01-01-a", "2026-01-02-b", "2026-01-03-c"):
            self._archived_batch(repo, n)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertIn("THIS REPO", rendered, f"section title missing:\n{rendered}")
        self.assertNotIn("| Batch | Priority", rendered, f"table header should be gone:\n{rendered}")
        self.assertIn("3 batches done", rendered, f"summary line missing:\n{rendered}")
        self.assertNotIn("in progress)", rendered, f"no batch should be expanded:\n{rendered}")
        self.assertNotIn("next in order)", rendered, f"no batch should be expanded:\n{rendered}")
        self.assertNotIn(f"cd {repo}", rendered, f"repo with nothing open must not offer /ifq:\n{rendered}")

    def test_this_repo_several_open_only_in_progress_expanded(self):
        # several open, one inProgress: all three rows show, but only the inProgress batch (which
        # outranks the flagged one) gets expanded.
        tmp = self._repos_dir / "severalopen"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-03-01-a", open_nums=("02",), done_nums=("01",))
        self._open_batch(repo, "2026-03-02-b")
        self._open_batch(repo, "2026-03-03-c", priority="high")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        for n in ("2026-03-01-a", "2026-03-02-b", "2026-03-03-c"):
            self.assertIn(f"| {n} |", rendered, f"row for {n} missing:\n{rendered}")
        self.assertIn("2026-03-01-a (in progress)", rendered, f"expanded header missing:\n{rendered}")
        self.assertNotIn("2026-03-02-b (", rendered, f"non-next batch must not expand:\n{rendered}")
        self.assertNotIn("2026-03-03-c (", rendered, f"flagged batch loses to inProgress:\n{rendered}")

    def test_this_repo_lists_unfinished_batch_without_all_flag(self):
        # a batch whose phases are all done but `finish` never ran (0 open, 2 done, not
        # archived) must appear in the non---all view as IN_PROGRESS -- it counts as
        # inProgress, not as an archived/finished batch.
        tmp = self._repos_dir / "unfinishedroot"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-05-01-unfinished", open_nums=(), done_nums=("01", "02"))

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertIn(
            "| 2026-05-01-unfinished |", rendered, f"unfinished batch row missing:\n{rendered}"
        )
        self.assertIn(
            "0/2 | IN_PROGRESS", rendered, f"unfinished batch status wrong:\n{rendered}"
        )

    def test_this_repo_all_flag_lists_archived_too(self):
        # --all: every batch shown, archived included, no summary line, expansion unchanged.
        tmp = self._repos_dir / "allflag"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-02-01-open")
        self._archived_batch(repo, "2026-01-01-a")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", "--all", str(repo), env=env).stdout

        self.assertIn("| 2026-02-01-open |", rendered, f"open batch row missing:\n{rendered}")
        self.assertIn("| 2026-01-01-a |", rendered, f"archived batch row missing:\n{rendered}")
        self.assertNotIn("batches done", rendered, f"summary must be omitted with --all:\n{rendered}")
        self.assertIn(
            "2026-02-01-open (next in order)", rendered, f"expansion missing with --all:\n{rendered}"
        )

    def test_this_repo_expansion_shows_done_and_open_phases(self):
        # expansion source: the expanded block is `brief --with-done` verbatim -- 01 ticked, 02/03
        # open with their sizes.
        tmp = self._repos_dir / "expansource"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(
            repo, "2026-04-01-mixed",
            open_nums=("02", "03"), done_nums=("01",),
            sizes={"02": "M", "03": "L"},
        )

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertRegex(rendered, r"✔ 01\b", f"phase 01 should be ticked:\n{rendered}")
        self.assertRegex(rendered, r"\b02\b.*\[M\]", f"phase 02 size missing:\n{rendered}")
        self.assertRegex(rendered, r"\b03\b.*\[L\]", f"phase 03 size missing:\n{rendered}")

    def test_this_repo_blocked_next_names_dependency(self):
        # blocked next: the only open (phase-bearing) batch is blocked -> row present, no
        # expansion, one line naming the dependency it waits on.
        tmp = self._repos_dir / "blockednext"
        repo = tmp / "repo"
        self._plain_repo(repo)
        # A phase-less directory is enough to make `2026-05-02-target` structurally blocked
        # (cfq_scan.py only checks the path exists) without itself becoming an open candidate.
        (repo / ".claude" / "cfq" / "impl" / "2026-05-01-dep").mkdir(parents=True)
        self._open_batch(repo, "2026-05-02-target", depends_on="2026-05-01-dep")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertIn("| 2026-05-02-target |", rendered, f"blocked batch row missing:\n{rendered}")
        self.assertNotIn("2026-05-02-target (", rendered, f"blocked batch must not expand:\n{rendered}")
        self.assertIn("2026-05-01-dep", rendered, f"blocking dependency not named:\n{rendered}")
        self.assertIn("blocked", rendered.lower(), f"blocking note missing:\n{rendered}")

    def test_dash_json_all_flag_accepted_and_ignored(self):
        # JSON mode always carried every batch; --all must be accepted and change nothing.
        tmp = self._repos_dir / "jsonall"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-02-01-open")
        self._archived_batch(repo, "2026-01-01-a")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        plain = self.json_out(self.run_cfq("dash", str(repo), env=env))
        with_all = self.json_out(self.run_cfq("dash", "--all", str(repo), env=env))
        self.assertEqual(plain, with_all, "`--all` must not change the JSON output")
        self.assertEqual(
            len(with_all["thisRepo"]["batches"]), 2, f"batches = {with_all['thisRepo']['batches']}"
        )

    def test_queues_reports_column(self):
        # Reports counts report.json presence across a repo's batches, open and archived both,
        # rendered next to Batches -- neighbouring counts (Plan/Todo/Batches) print a bare number
        # for zero, so Reports does too rather than a dash or blank.
        tmp = self._repos_dir / "reportsroot"
        repo = tmp / "repo"
        self._plain_repo(repo)
        b1 = self._open_batch(repo, "2026-07-01-a")
        (b1 / "report.json").write_text("{}")
        self._archived_batch(repo, "2026-07-02-b")
        b3 = self._archived_batch(repo, "2026-07-03-c")
        (b3 / "report.json").write_text("{}")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(tmp), env=env).stdout

        self.assertIn(
            "| repo | 0 | 0 | 1/2 | 2 |", rendered, f"reports column wrong:\n{rendered}"
        )

    def test_queues_reports_column_zero(self):
        tmp = self._repos_dir / "noreportsroot"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-07-04-d")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(tmp), env=env).stdout

        self.assertIn(
            "| repo | 0 | 0 | 1/0 | 0 |", rendered, f"zero reports should render as a bare 0:\n{rendered}"
        )

    def test_actions_lists_view_reports_pointing_at_rfq(self):
        tmp = self._repos_dir / "rfqactionsroot"
        repo = tmp / "repo"
        (repo / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertIn("view reports", rendered, f"view-reports action missing:\n{rendered}")
        self.assertIn("/rfq", rendered, f"/rfq pointer missing from ACTIONS:\n{rendered}")

    # --- Phase 03: NEXT last, ACTIONS visible, unambiguous plugins line ---

    def _plugin_home(self, home, mattpocock=False, ponytail=False, ponytail_default_mode=None):
        if mattpocock:
            (home / ".claude" / "plugins" / "cache" / "mattpocock-skills" / "mattpocock-skills" / "1.0.0").mkdir(
                parents=True
            )
        if ponytail:
            (home / ".claude" / "plugins" / "cache" / "ponytail" / "ponytail" / "4.8.4").mkdir(parents=True)
        if ponytail_default_mode is not None:
            cfg_dir = home / ".config" / "ponytail"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "config.json").write_text('{"defaultMode":"%s"}' % ponytail_default_mode)

    def _plugins_line(self, rendered):
        return next(
            line for line in rendered.splitlines()
            if re.match(r"^(✅|➖|⚠️) Plugins\b", line)
        )

    def test_next_section_order_last(self):
        tmp = self._repos_dir / "orderroot"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._open_batch(repo, "2026-06-01-a")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout
        lines = rendered.splitlines()

        next_idx = lines.index("NEXT")
        actions_idx = lines.index("ACTIONS")
        config_idx = next(i for i, l in enumerate(lines) if l.startswith("CONFIG"))
        self.assertGreater(actions_idx, config_idx, f"ACTIONS must follow CONFIG:\n{rendered}")
        self.assertGreater(next_idx, actions_idx, f"NEXT must be last, after ACTIONS:\n{rendered}")

    def test_next_current_repo_first(self):
        tmp = self._repos_dir / "orderfirst"
        repo_a = tmp / "repo-a"
        repo_b = tmp / "repo-b"
        self._plain_repo(repo_a)
        self._plain_repo(repo_b)
        self._open_batch(repo_a, "2026-06-01-a")
        self._open_batch(repo_b, "2026-06-01-b")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo_b), env=env).stdout

        idx_b = rendered.index(f"cd {repo_b}")
        idx_a = rendered.index(f"cd {repo_a}")
        self.assertLess(idx_b, idx_a, f"current repo (repo-b) must be listed first in NEXT:\n{rendered}")

    def test_next_section_absent_when_nothing_open(self):
        tmp = self._repos_dir / "nonext"
        repo = tmp / "repo"
        self._plain_repo(repo)
        self._archived_batch(repo, "2026-01-01-a")

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertNotIn("NEXT", rendered, f"no NEXT header expected when nothing is open:\n{rendered}")
        self.assertNotIn("/ifq", rendered, f"no handoff block expected when nothing is open:\n{rendered}")

    def test_actions_section_lists_every_capability(self):
        tmp = self._repos_dir / "actionsroot"
        repo = tmp / "repo"
        (repo / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout

        self.assertIn("ACTIONS", rendered, f"ACTIONS header missing:\n{rendered}")
        lowered = rendered.lower()
        for kw in ACTION_KEYWORDS:
            self.assertIn(kw, lowered, f"action keyword {kw!r} missing from the rendered dashboard:\n{rendered}")

    def test_actions_drift_guard_matches_dashboard_md(self):
        # Keeps the ACTIONS list and references/dashboard.md's prose from drifting apart in
        # either direction -- a new management action must be documented AND rendered.
        tmp = self._repos_dir / "driftroot"
        repo = tmp / "repo"
        (repo / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo)

        env = {"CFQ_SCAN_ROOTS": str(tmp)}
        rendered = self.run_cfq("dash", "render", str(repo), env=env).stdout.lower()
        doc = DASHBOARD_MD.read_text().lower()

        for kw in ACTION_KEYWORDS:
            self.assertIn(kw, rendered, f"action keyword {kw!r} rendered nowhere but documented in dashboard.md")
            self.assertIn(kw, doc, f"action keyword {kw!r} rendered but not documented in dashboard.md")

    def test_plugins_line_mode_off_drops_clause(self):
        tmp = self._repos_dir / "modeoffroot"
        home = self._repos_dir / "modeoffhome"
        repo = tmp / "repo"
        (repo / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo)
        self._plugin_home(home, mattpocock=True, ponytail=True, ponytail_default_mode="off")

        rendered = self.run_cfq(
            "dash", "render", str(tmp), home=home, env={"CFQ_SCAN_ROOTS": str(tmp)},
        ).stdout
        plugins_line = self._plugins_line(rendered)

        self.assertTrue(
            plugins_line.endswith("ponytail audit: on"),
            f"plugins line should end with 'ponytail audit: on':\n{plugins_line}",
        )
        self.assertNotIn("mode:", plugins_line, f"mode clause should vanish when ponytailMode is off:\n{plugins_line}")

    def test_plugins_line_mode_full_warns(self):
        tmp = self._repos_dir / "modefullroot"
        home = self._repos_dir / "modefullhome"
        repo = tmp / "repo"
        (repo / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo)
        self._plugin_home(home, ponytail=True)

        rendered = self.run_cfq(
            "dash", "render", str(tmp), home=home, env={"CFQ_SCAN_ROOTS": str(tmp)},
        ).stdout

        self.assertIn("⚠️ Plugins", rendered, f"mode full should force the warning icon:\n{rendered}")
        self.assertIn(
            "ponytail default mode: full · cfq expects off", rendered, f"expected wording missing:\n{rendered}"
        )

    def test_plugins_line_audit_off(self):
        tmp = self._repos_dir / "auditoffroot"
        home = self._repos_dir / "auditoffhome"
        repo = tmp / "repo"
        (repo / ".claude" / "cfq").mkdir(parents=True)
        self._plain_repo(repo)
        self._plugin_home(home, mattpocock=True, ponytail=True, ponytail_default_mode="off")

        rendered = self.run_cfq(
            "dash", "render", str(tmp), home=home,
            env={"CFQ_SCAN_ROOTS": str(tmp), "CFQ_USE_PONYTAIL": "false"},
        ).stdout

        self.assertIn("ponytail audit: off", rendered, f"expected wording missing:\n{rendered}")
        self.assertIn("➖ Plugins", rendered, f"audit off keeps the plain icon, as today:\n{rendered}")


class TestDashRenderPinnedPreShared(unittest.TestCase):
    """Phase 09: pins `cfq_dash.py`'s current rendered output -- the icon literals in
    `dash_line`/`plugins_line`, the `:<16` PRECHECKS padding, and the 27-width ACTIONS column --
    byte-identical, before those call sites move onto `cfq_lib/text.py`'s shared renderer. Every
    expected literal below is hand-composed (never built via `cfq_lib.text`), so a real drift in
    `cfq_dash.py`'s output cannot pass by construction."""

    def test_dash_line_icon_ok(self):
        icon, text = cfq_dash.dash_line("OK", [{"open": 1}, {"open": 0}], None)
        self.assertEqual(icon, "✅", f"dash_line OK icon = {icon!r}")
        self.assertEqual(text, "2 repos · 1 with open work")

    def test_dash_line_icon_multiple_in_progress(self):
        this_repo = {
            "name": "repo",
            "batches": [
                {"name": "a", "status": "IN_PROGRESS"},
                {"name": "b", "status": "IN_PROGRESS"},
            ],
        }
        icon, text = cfq_dash.dash_line("MULTIPLE_IN_PROGRESS", [], this_repo)
        self.assertEqual(icon, "⚠️", f"dash_line MULTIPLE_IN_PROGRESS icon = {icon!r}")
        self.assertEqual(
            text,
            "MULTIPLE_IN_PROGRESS in repo: a, b — invariant violation, resolve manually",
        )

    def test_plugins_line_icon_missing(self):
        icon, text = cfq_dash.plugins_line({
            "mattpocock": False, "ponytail": False, "ponytailMode": "off",
            "useMattpocockGrilling": True, "usePonytailAudit": True,
        })
        self.assertEqual(icon, "➖", f"plugins_line missing-plugins icon = {icon!r}")
        self.assertEqual(text, "mattpocock-skills/ponytail not installed")

    def test_plugins_line_icon_healthy(self):
        icon, text = cfq_dash.plugins_line({
            "mattpocock": True, "ponytail": True, "ponytailMode": "off",
            "useMattpocockGrilling": True, "usePonytailAudit": True,
        })
        self.assertEqual(icon, "✅", f"plugins_line healthy icon = {icon!r}")
        self.assertEqual(
            text, "mattpocock-skills and ponytail installed · classic grill on · ponytail audit: on",
        )

    def test_plugins_line_icon_mode_warn(self):
        icon, text = cfq_dash.plugins_line({
            "mattpocock": False, "ponytail": True, "ponytailMode": "full",
            "useMattpocockGrilling": True, "usePonytailAudit": True,
        })
        self.assertEqual(icon, "⚠️", f"plugins_line degraded-mode icon = {icon!r}")
        self.assertEqual(
            text,
            "mattpocock-skills not installed · ponytail audit: on · "
            "ponytail default mode: full · cfq expects off",
        )

    def test_render_body_byte_identical_empty_queue(self):
        out = cfq_dash.render_body([], None, [], False, "", "", "")
        self.assertEqual(out, "\nNo repos with a queue yet.")

    def test_render_body_byte_identical_with_queue_entries(self):
        # Also pins the :258 two-column ACTIONS block for both a short left value ("view
        # reports", 12 chars) and the longest one ("set / remove a dependency", 25 chars) -- the
        # case a literal 27-width column and a computed one would diverge on.
        repos = [{
            "name": "repo-a", "plan": 0, "todo": 0, "open": 1, "done": 0, "reports": 0,
            "status": "OK", "path": "/x/repo-a",
        }]
        this_repo = {
            "path": "/x/repo-a", "name": "repo-a",
            "batches": [{
                "name": "2026-01-01-demo", "priority": "", "open": 1, "done": 0,
                "archived": False, "status": "OK",
            }],
        }
        out = cfq_dash.render_body(repos, this_repo, [], False, "", "", "")
        expected = (
            "\nQUEUES\n"
            "| Repo | Plan | Todo | Batches | Reports | Status |\n"
            "|---|---|---|---|---|---|\n"
            "| repo-a | 0 | 0 | 1/0 | 0 | OK |\n"
            "\n"
            "THIS REPO · repo-a\n"
            "| Batch | Priority | Open/Done | Status |\n"
            "|---|---|---|---|\n"
            "| 2026-01-01-demo | - | 1/0 | OK |\n"
            "0 batches done · full list: bin/cfq dash render --all\n"
            "\n"
            "CONFIG · repo-a\n"
            "0 of 0 keys differ from default\n"
            "\n"
            "ACTIONS\n"
            "flag / unflag priority     mark a batch high priority\n"
            "delete a batch             removes the queue directory\n"
            "archive a batch            moves it to impl/done/\n"
            "clean the registry         drop repos that no longer exist\n"
            "set / remove a dependency  .dependsOn between batches\n"
            "work off todo/ entries     runs their check: commands\n"
            "change a setting           just say it in plain language\n"
            "full batch list            bin/cfq dash render --all\n"
            "view reports               /rfq\n"
            "settings, this repo        bin/cfq settings list --repo /x/repo-a --sources\n"
            "settings, global           bin/cfq settings list --sources\n"
            "\n"
            "NEXT\n"
            "\n"
            "cd /x/repo-a\n"
            "/model sonnet\n"
            "/ifq"
        )
        self.assertEqual(out, expected)

if __name__ == "__main__":
    unittest.main()
