"""Tests for scripts/cfq_portal.py -- the `portal sync`/`portal rebuild` data layer behind
`<repo>/.claude/cfq/reports/index.html`. The viewer shell itself is phases 11-15; this only checks
the `.js` data files `portal sync` writes into `<repo>/.claude/cfq/reports/data/` against the
payload contract in `.batch-context.md` (Portal data files).
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import unittest

from cfq_testlib import PLUGIN_ROOT, CfqTestCase, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_portal  # noqa: E402
from cfq_lib import flags as cfq_flags  # noqa: E402

DATA_FILE_RE = re.compile(
    r"^window\.CFQ_DATA = window\.CFQ_DATA \|\| \{\};\n"
    r"window\.CFQ_DATA\[(?P<key>.*?)\] = (?P<payload>.*);\n\Z",
    re.S,
)

DONE_BATCH = "007-2026-09-01-demo-batch"
OPEN_BATCH = "008-2026-09-02-open-batch"
BARE_BATCH = "2026-09-03-bare"
REVIEW_BATCH = "009-2026-09-04-review-batch"
PLANNING_BATCH = "010-2026-09-05-planning-batch"
DONE_BRANCH = f"cfq/{DONE_BATCH}"
MERGE_CARD = f"2026-09-30-merge-cfq-{DONE_BATCH}.md"

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"


def T(turns, inp, out, cache_read, cache_creation):
    return {
        "turns": turns, "input": inp, "output": out, "cache_read": cache_read,
        "cache_creation": cache_creation, "billable_in": inp + cache_creation,
    }


def T5(turns, inp, out, cache_read, cache_creation):
    t = T(turns, inp, out, cache_read, cache_creation)
    del t["billable_in"]
    return t


def layer(tokens, model=None, count=1):
    d = dict(tokens)
    d["by_model"] = {model: dict(tokens)} if model else {}
    d["count"] = count
    return d


ZERO = T(0, 0, 0, 0, 0)


def schema3(layers, *, since, until, wallclock, agents=(), tools=None, by_skill=None,
            recommended=(), settled=True, mode="orchestrator", kind="phase"):
    return {
        "schema": 3, "kind": kind, "mode": mode, "from": since, "until": until,
        "wallclock_s": wallclock, "since": since, "settled": settled, "rev": 2 if settled else 1,
        "layers": {
            "main": layers.get("main", layer(ZERO, count=0)),
            "main_explore": layers.get("main_explore", layer(ZERO, count=0)),
            "worker": layers.get("worker", layer(ZERO, count=0)),
            "worker_explore": layers.get("worker_explore", layer(ZERO, count=0)),
        },
        "agents": list(agents),
        "tools": tools or {},
        "by_skill": by_skill or {"-": T(1, 1, 1, 1, 1)},
        "skills_recommended": list(recommended),
    }


PLANNING_TEL = schema3(
    {"main": layer(T(10, 20, 1000, 5000, 300), OPUS)},
    since="2026-08-31T09:00:00Z", until="2026-08-31T10:00:00Z", wallclock=3600, kind="planning", mode="",
)
RED_TEL = schema3(
    {"main": layer(T(4, 8, 400, 1000, 100), SONNET)},
    since="2026-09-01T11:00:00Z", until="2026-09-01T11:10:00Z", wallclock=600,
)
GREEN_AGENT = {
    "id": "agent-w1", "type": "cfq:cfq-phase-worker", "description": "Implement phase 02", "depth": 1,
    "parent": None, "layer": "worker", "totals": T(5, 10, 500, 3000, 60),
    "by_model": {SONNET: T(5, 10, 500, 3000, 60)},
}
GREEN_TEL = schema3(
    {
        "main": layer(T(3, 6, 300, 2000, 50), OPUS),
        "worker": layer(T(5, 10, 500, 3000, 60), SONNET),
    },
    since="2026-09-01T12:00:00Z", until="2026-09-01T12:02:00Z", wallclock=120,
    agents=[GREEN_AGENT], tools={"Agent": 1, "Bash": 3},
    by_skill={"-": T(2, 1, 1, 1, 1), "tdd": T(6, 1, 1, 1, 1)}, recommended=["tdd"],
)
# a finished-batch phase recorded before per-model data existed: totals only, no layers
SETUP_TEL = {
    "schema": 2, "kind": "phase", "mode": "classic", "from": "2026-09-01T10:00:00Z",
    "until": "2026-09-01T10:30:00Z", "wallclock_s": 1800, "totals": T(2, 4, 100, 500, 20),
    "tools": {"Read": 2}, "by_skill": {"-": T(2, 4, 100, 500, 20)},
}
SCHEMA1_TELEMETRY = {
    "totals": {"turns": 3, "output": 300, "billable_in": 150, "cache_read": 0},
    "wallclock_s": 30,
    "by_model": {"sonnet": 1},
    "by_effort": {"medium": 1},
    "by_skill": {"-": 1},
    "subagent_worker": {"turns": 1, "output": 100, "billable_in": 50},
}

DIFFSTAT = {
    "files": 2, "insertions": 30, "deletions": 4,
    "paths": [{"path": "claude/x.py", "added": 20, "deleted": 4}, {"path": "logo.png", "added": None, "deleted": None}],
}
FINISH = {
    "at": "2026-09-02T09:00:00+00:00", "lang": {"issues": 0, "findings": []}, "maintenance": "ok",
    "security": {"planning": {"counts": {"low": 1}}, "now": {"counts": {"low": 1}}, "new": {"counts": {}}},
    "changelog": "ok", "errors": [],
}
SECURITY = [
    {"available": True, "counts": {"low": 1}, "findings": [], "at": "2026-08-31T10:00:00+00:00"},
    {"available": True, "counts": {"low": 2}, "findings": [], "at": "2026-09-02T08:00:00+00:00"},
]


def ledger_phase(slug, status, telemetry=None, **extra):
    p = {
        "phase": slug, "status": status, "implemented": f"built {slug}", "verification": "tests -> OK",
        "deviations": [], "errors": [], "triggers": [], "filesTouched": [], "parkedPlanEntries": [],
        "commit": "abc123",
    }
    if telemetry is not None:
        p["telemetry"] = telemetry
    p.update(extra)
    return p


class PortalTest(CfqTestCase):
    # ---- fixture builders --------------------------------------------------------------------

    def _cfq(self, repo):
        return repo / ".claude" / "cfq"

    def _data_dir(self, repo):
        return self._cfq(repo) / "reports" / "data"

    def _write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def _build_world(self, repo):
        """A done batch (planning record; phase 02 red then green; notes, fromPlan, finish,
        security, changelog block, merge card), an open batch (one done, two open phases, no
        telemetry), a batch without report.json, a `.review` batch, a `.planning` batch, and
        open and closed todo cards and plan entries."""
        cfq = self._cfq(repo)
        done = cfq / "impl" / "done" / DONE_BATCH
        self._write(done / ".batch-context.md", (
            "# Batch Context\n\n"
            "## Goal\nBuild the **portal** safely <script>alert('goal')</script>.\n"
            "Second line of the same paragraph.\n\nA second paragraph, not part of the row.\n\n"
            "## Decisions\n- Decision one\n- Decision two\n\n"
            "## Invariants\nNever break the build.\n"
        ))
        self._write(done / "done" / "01-setup.md", (
            "# Setup phase\n\n## Size\n\nS\n\n## Context\n\nSetup context.\n\n"
            "## Affected Files\n\n- `claude/setup.py`\n"
        ))
        self._write(done / "done" / "02-build.md", (
            "# Build the <script>alert('title')</script> thing\n\n## Size\n\nL\n\n## Context\n\n"
            "Some context with <script>alert(1)</script> in it.\n\n"
            "## Affected Files\n\n- `claude/x.py` -- the change\n- `claude/y.py`\n\n## Verification\n\n```bash\ntrue\n```\n"
        ))
        report = {
            "repo": str(repo), "batch": DONE_BATCH, "started": "2026-09-01T09:30:00+00:00",
            "planning": PLANNING_TEL,
            "phases": [
                ledger_phase("01-setup", "green", SETUP_TEL, reopened="2026-09-01T10:40:00+00:00",
                             parkedPlanEntries=["plan/2026-09-16-from-phase.md"]),
                ledger_phase("02-build", "red", RED_TEL, errors=["boom"]),
                ledger_phase(
                    "02-build", "green", GREEN_TEL, deviations=["Touched y.py too"],
                    observations=["The renderer is slow"], diffstat=DIFFSTAT,
                    filesTouched=["/repo/claude/x.py"], triggers=["omitted"],
                ),
            ],
            "security": SECURITY,
            "notes": [
                {"kind": "todo", "file": "2026-09-20-fix-thing.md", "title": "Fix the thing",
                 "at": "2026-09-01T12:01:00+00:00", "phase": "02-build", "framework": False},
                {"kind": "plan", "file": "2026-09-19-idea.md", "title": "An idea",
                 "at": "2026-09-01T12:01:30+00:00", "phase": None, "framework": False},
                {"kind": "todo", "file": "2026-09-01-old-card.md", "title": "Old card",
                 "at": "2026-09-01T12:01:40+00:00", "phase": "02-build", "framework": False},
                {"kind": "plan", "file": "2026-09-18-gone.md", "title": "Gone",
                 "at": "2026-09-01T12:02:00+00:00", "phase": "02-build", "framework": True},
            ],
            "fromPlan": ["2026-09-17-parked.md"],
            "finish": FINISH,
        }
        self._write(done / "report.json", json.dumps(report))

        opened = cfq / "impl" / OPEN_BATCH
        self._write(opened / ".batch-context.md", "# Batch Context\n\n## Goal\nOpen goal.\n")
        self._write(opened / "done" / "01-a.md", "# A\n\n## Size\n\nS\n")
        self._write(opened / "02-b.md", "# B\n\n## Size\n\nM\n")
        self._write(opened / "03-c.md", "# C\n\n## Size\n\nM\n")
        self._write(opened / "report.json", json.dumps({
            "repo": str(repo), "batch": OPEN_BATCH, "started": "2026-09-02T09:00:00+00:00",
            "phases": [ledger_phase("01-a", "green")],
        }))

        self._write(cfq / "impl" / BARE_BATCH / "01-x.md", "# X\n\n## Size\n\nS\n")
        self._write(cfq / "impl" / REVIEW_BATCH / "01-r.md", "# R\n\n## Size\n\nS\n")
        self._write(cfq / "impl" / REVIEW_BATCH / ".review", "{}\n")
        self._write(cfq / "impl" / PLANNING_BATCH / "01-p.md", "# P\n\n## Size\n\nS\n")
        self._write(cfq / "impl" / PLANNING_BATCH / ".planning", "2026-09-05T00:00:00+00:00\n")

        self._write(cfq / "todo" / "2026-09-20-fix-thing.md", "# Fix the thing\n\nSome todo body.\n\ncheck: true\n")
        self._write(cfq / "todo" / "2026-09-21-xss.md", "# Beware <script>alert(3)</script>\n\nBody <script>alert(4)</script>\n")
        self._write(cfq / "todo" / "done" / "2026-09-01-old-card.md", (
            "# Old card\n\nBody.\n\n## Closed\n\n2026-09-02 -- superseded\n"
        ))
        self._write(cfq / "todo" / "done" / MERGE_CARD, f"# Merge {DONE_BRANCH}\n\ncheck: true\n")
        self._write(cfq / "plan" / "2026-09-19-idea.md", "# An idea\n\nDetails about the idea.\n")
        self._write(cfq / "plan" / "2026-09-16-from-phase.md", "# From a phase\n\nParked by phase 01.\n")
        self._write(cfq / "plan" / "done" / "2026-09-17-parked.md", "# Parked idea\n\nParked into the batch.\n")

        self._write(cfq / "changelog.yml", (
            "- batchNumber: 8\n"
            f"  batch: {OPEN_BATCH}\n"
            "  status: in-progress\n"
            "- batchNumber: 7\n"
            f"  batch: {DONE_BATCH}\n"
            f"  branch: {DONE_BRANCH}\n"
            "  base: main\n"
            "  started: 2026-09-01T09:30:00+00:00\n"
            "  status: done\n"
        ))

    def _build_batch(self, repo, batch_name, with_report=True, schema1=False):
        """A small open batch (one open, one done phase) for tests that do not need the world."""
        impl = self._cfq(repo) / "impl" / batch_name
        self._write(impl / ".batch-context.md", "# Batch Context\n\n## Goal\nBuild the portal.\n")
        self._write(impl / "01-first.md", "# First phase\n\n## Size\n\nM\n")
        self._write(impl / "done" / "00-setup.md", "# Setup phase\n\n## Size\n\nS\n")
        if with_report:
            tel = SCHEMA1_TELEMETRY if schema1 else GREEN_TEL
            self._write(impl / "report.json", json.dumps({
                "repo": str(repo), "batch": batch_name, "started": "2026-09-23T10:00:00+02:00",
                "phases": [ledger_phase("00-setup", "green", tel)],
            }))
        return impl

    def _init_queue(self, repo):
        """A bare `.claude/cfq/` with no batches -- `cfq_scan.scan_repo()` treats a repo with no
        such directory at all as unregistered (`status: "NO_REPO"`, sync short-circuits before
        even reaching the install step), so every install-only test needs at least this much."""
        (repo / ".claude" / "cfq").mkdir(parents=True, exist_ok=True)

    def _payload(self, path):
        m = DATA_FILE_RE.match(path.read_text())
        self.assertIsNotNone(m, f"unexpected data-file shape in {path}: {path.read_text()[:200]!r}")
        return json.loads(m.group("key")), json.loads(m.group("payload"))

    def _load(self, repo, key):
        _key, payload = self._payload(self._data_dir(repo) / f"{key}.js")
        return payload

    def _sync(self, repo, *extra, env=None):
        proc = self.run_cfq("portal", "sync", str(repo), *extra, env=env)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return self.json_out(proc)

    def _world(self, name="world"):
        repo = self.make_repo(name)
        self._build_world(repo)
        self._sync(repo)
        return repo

    def _row(self, repo, batch):
        return next(b for b in self._load(repo, "queue")["batches"] if b["name"] == batch)

    def _entry(self, repo, entry_id):
        return next(e for e in self._load(repo, "queue")["entries"] if e["id"] == entry_id)

    # ---- the loader contract: a data file's path is its key plus .js -----------------------------

    def test_every_data_file_path_is_its_key_plus_js(self):
        repo = self._world()
        data = self._data_dir(repo)
        files = sorted(data.rglob("*.js"))
        self.assertGreater(len(files), 8)
        for f in files:
            key, _payload = self._payload(f)
            self.assertEqual(key + ".js", str(f.relative_to(data)), f"{f} registers the wrong key")

    def test_file_set_and_second_sync_writes_nothing(self):
        repo = self.make_repo()
        self._build_world(repo)
        first = self._sync(repo)
        expected_data = {
            "site.js", "queue.js",
            *(f"batch/{b}.js" for b in (DONE_BATCH, OPEN_BATCH, BARE_BATCH, REVIEW_BATCH, PLANNING_BATCH)),
            *(f"entry/{e}.js" for e in (
                "todo-2026-09-20-fix-thing", "todo-2026-09-21-xss", "todo-2026-09-01-old-card",
                "plan-2026-09-19-idea", "plan-2026-09-16-from-phase", "plan-2026-09-17-parked",
                f"todo-{MERGE_CARD[:-3]}",
            )),
        }
        self.assertEqual(
            set(first["written"]),
            expected_data | {"index.html"} | {
                f"assets/{f.name}" for f in (PLUGIN_ROOT / "portal").iterdir() if f.name != "index.html"
            },
        )
        self.assertEqual({str(f.relative_to(self._data_dir(repo))) for f in self._data_dir(repo).rglob("*.js")}, expected_data)

        second = self._sync(repo)
        self.assertEqual(second["written"], [], "an unchanged fixture must rewrite nothing")
        self.assertEqual(second["unchanged"], len(expected_data))
        self.assertEqual(second["removed"], [])

    def test_stale_plan_and_impl_files_are_removed(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        stale = self._data_dir(repo) / "batch"
        self._write(stale / "2026-09-23-demo.plan.js", 'window.CFQ_DATA["batch/2026-09-23-demo/plan"] = {};\n')
        self._write(stale / "2026-09-23-demo.impl.js", 'window.CFQ_DATA["batch/2026-09-23-demo/impl"] = {};\n')

        result = self._sync(repo)
        self.assertIn("batch/2026-09-23-demo.plan.js", result["removed"])
        self.assertIn("batch/2026-09-23-demo.impl.js", result["removed"])
        self.assertEqual(sorted(p.name for p in stale.glob("*.js")), ["2026-09-23-demo.js"])

    def test_deleted_batch_data_file_is_removed(self):
        repo = self.make_repo()
        impl = self._build_batch(repo, "2026-09-23-demo")
        self._sync(repo)

        shutil.rmtree(impl)
        result = self._sync(repo)
        self.assertIn("batch/2026-09-23-demo.js", result["removed"])

    def test_closed_entry_keeps_its_data_file_as_archive(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        entry = self._write(self._cfq(repo) / "plan" / "2026-09-19-idea.md", "# An idea\n\nDetails.\n")
        self._sync(repo)
        self.assertEqual(self._load(repo, "entry/plan-2026-09-19-idea")["state"], "open")

        done = self._cfq(repo) / "plan" / "done"
        done.mkdir()
        shutil.move(str(entry), str(done / entry.name))  # what `note close` does
        result = self._sync(repo)
        self.assertEqual(result["removed"], [])
        self.assertEqual(self._load(repo, "entry/plan-2026-09-19-idea")["state"], "done")

    # ---- site.js ---------------------------------------------------------------------------------

    def test_commit_url_from_remote(self):
        want = "https://host/owner/repo/commit/"
        for remote in (
            "git@host:owner/repo.git", "https://host/owner/repo.git", "https://host/owner/repo",
            "ssh://git@host/owner/repo.git", "https://user@host/owner/repo/",
        ):
            self.assertEqual(cfq_portal.commit_url_from_remote(remote), want, remote)
        for remote in ("", "   ", "not a remote", "/local/path/repo.git", "https://host/onlyone"):
            self.assertEqual(cfq_portal.commit_url_from_remote(remote), "", remote)

    def test_site_payload(self):
        repo = self.make_repo("my-repo")
        self._init_queue(repo)
        self._sync(repo)
        site = self._load(repo, "site")
        self.assertEqual(site["mode"], "repo")
        self.assertEqual(site["repo"], "my-repo")
        self.assertEqual(site["commitUrl"], "")
        self.assertEqual(site["pluginVersion"], json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())["version"])

        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@example.com:acme/widgets.git"], check=True)
        self._sync(repo)
        self.assertEqual(self._load(repo, "site")["commitUrl"], "https://example.com/acme/widgets/commit/")

    # ---- queue.js: batch rows ---------------------------------------------------------------------

    def test_queue_row_of_the_done_batch(self):
        repo = self._world()
        row = self._row(repo, DONE_BATCH)
        self.assertEqual(row["number"], 7)
        self.assertEqual(row["title"], "demo batch")
        self.assertEqual(row["date"], "2026-09-01")
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["phases"], {"done": 2, "total": 2})
        self.assertEqual(row["priority"], "")
        self.assertEqual(row["dependsOn"], [])
        self.assertEqual(
            row["goalHtml"],
            "Build the <strong>portal</strong> safely &lt;script&gt;alert(&apos;goal&apos;)&lt;/script&gt;. "
            "Second line of the same paragraph.",
        )
        self.assertEqual(row["started"], "2026-09-01T09:30:00+00:00")
        self.assertEqual(row["finished"], "2026-09-01T12:02:00Z")
        # planning + the red attempt + the green attempt + phase 01, nothing dropped
        self.assertEqual(row["cost"]["total"], T5(24, 48, 2300, 11500, 530))
        self.assertEqual(row["cost"]["byModel"], {
            OPUS: T5(13, 26, 1300, 7000, 350),
            SONNET: T5(9, 18, 900, 4000, 160),
        })
        self.assertEqual(row["deviations"], 1)
        self.assertEqual(row["flags"], {"warn": 2, "info": 3})
        self.assertEqual((row["branch"], row["base"]), (DONE_BRANCH, "main"))
        self.assertTrue(row["settled"])

    def test_unsettled_record_makes_the_row_unsettled(self):
        repo = self._world()
        report = self._cfq(repo) / "impl" / "done" / DONE_BATCH / "report.json"
        data = json.loads(report.read_text())
        data["phases"][2]["telemetry"]["settled"] = False
        report.write_text(json.dumps(data))
        self._sync(repo)
        self.assertFalse(self._row(repo, DONE_BATCH)["settled"])

    def test_merged_follows_the_merge_card(self):
        repo = self._world()
        self.assertIs(self._row(repo, DONE_BATCH)["merged"], True)

        todo = self._cfq(repo) / "todo"
        shutil.move(str(todo / "done" / MERGE_CARD), str(todo / MERGE_CARD))
        self._sync(repo)
        self.assertIs(self._row(repo, DONE_BATCH)["merged"], False)

        (todo / MERGE_CARD).unlink()
        self._sync(repo)
        self.assertIsNone(self._row(repo, DONE_BATCH)["merged"])
        self.assertIsNone(self._row(repo, OPEN_BATCH)["merged"])

    def test_row_without_telemetry_has_no_cost(self):
        repo = self._world()
        for name in (OPEN_BATCH, BARE_BATCH):
            self.assertIsNone(self._row(repo, name)["cost"], name)
        self.assertEqual(self._row(repo, OPEN_BATCH)["phases"], {"done": 1, "total": 3})
        self.assertEqual(self._row(repo, OPEN_BATCH)["status"], "in_progress")
        self.assertEqual(self._row(repo, BARE_BATCH)["status"], "planned")
        self.assertIsNone(self._row(repo, BARE_BATCH)["number"])
        self.assertEqual(self._row(repo, BARE_BATCH)["title"], "bare")

    def test_review_marker_and_planning_marker_statuses(self):
        repo = self._world()
        self.assertEqual(self._row(repo, REVIEW_BATCH)["status"], "awaiting_review")
        self.assertEqual(self._row(repo, PLANNING_BATCH)["status"], "planning")

    def test_blocked_batch_stays_blocked_with_a_review_marker(self):
        repo = self.make_repo()
        self._build_world(repo)
        impl = self._cfq(repo) / "impl"
        (impl / REVIEW_BATCH / ".dependsOn").write_text(f"{OPEN_BATCH}\n")
        self._sync(repo)
        self.assertEqual(self._row(repo, REVIEW_BATCH)["status"], "blocked")

    def test_queue_row_carries_unknown_deps(self):
        # An unnamed/deleted dependency doesn't block a batch on its own (cfq_scan.py's own
        # resolve_deps -- only a still-open dependency dir does that), but the viewer still needs
        # to name it, so `unknownDeps` travels through unmodified alongside `dependsOn`.
        repo = self.make_repo()
        impl = self._build_batch(repo, "2026-09-23-demo")
        (impl / ".dependsOn").write_text("gibtsnicht\n")
        self._sync(repo)
        row = self._row(repo, "2026-09-23-demo")
        self.assertEqual(row["dependsOn"], ["gibtsnicht"])
        self.assertEqual(row["unknownDeps"], ["gibtsnicht"])

    def test_title_lines_are_not_part_of_the_rendered_html(self):
        repo = self._world()
        batch = self._load(repo, f"batch/{DONE_BATCH}")
        for phase in batch["phases"]:
            self.assertNotIn("<h1", phase["planHtml"], phase["slug"])
            self.assertNotIn(phase["title"], phase["planHtml"].replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'"))
        entry = self._load(repo, "entry/plan-2026-09-19-idea")
        self.assertNotIn("<h1", entry["bodyHtml"])
        self.assertNotIn("An idea", entry["bodyHtml"])
        self.assertIn("Details about the idea.", entry["bodyHtml"])

    # ---- queue.js: totals and entries -------------------------------------------------------------

    def test_queue_totals(self):
        repo = self._world()
        totals = self._load(repo, "queue")["totals"]
        self.assertEqual(totals["batches"], {"inProgress": 1, "planned": 3, "done": 1})
        self.assertEqual(totals["todos"], 2, "open todo cards only")
        self.assertEqual(totals["planEntries"], 2, "open plan entries only")
        self.assertEqual(totals["deviations"], 1)
        self.assertEqual(totals["flags"], {"warn": 3, "info": 3}, "the open batch adds one no-telemetry warn")
        self.assertEqual(totals["cost"], T5(24, 48, 2300, 11500, 530))
        queue = self._load(repo, "queue")
        self.assertEqual(queue["sizes"], [
            {"batch": DONE_BATCH, "phase": "01-setup", "size": "S", "turns": 2, "output": 100},
            {"batch": DONE_BATCH, "phase": "02-build", "size": "L", "turns": 12, "output": 1200},
        ])
        self.assertEqual(queue["baselines"], cfq_flags.baselines(queue["sizes"]))
        self.assertEqual(queue["baselines"]["L"], {"n": 1, "turnsMedian": 12, "outputMedian": 1200})
        self.assertEqual(sum(r["flags"]["warn"] for r in queue["batches"]), totals["flags"]["warn"])
        self.assertEqual(sum(r["flags"]["info"] for r in queue["batches"]), totals["flags"]["info"])
        self.assertEqual(queue["repo"], str(repo.resolve()))

    def test_entry_rows(self):
        repo = self._world()
        rows = {e["id"]: e for e in self._load(repo, "queue")["entries"]}
        self.assertEqual(len(rows), 7)
        self.assertNotIn("bodyHtml", rows["plan-2026-09-19-idea"], "queue.js entries stay summaries")

        fix = rows["todo-2026-09-20-fix-thing"]
        self.assertEqual((fix["kind"], fix["state"], fix["date"], fix["title"]), ("todo", "open", "2026-09-20", "Fix the thing"))
        self.assertIs(fix["check"], True)
        self.assertEqual(fix["closed"], "")
        self.assertEqual(fix["origin"], {"batch": DONE_BATCH, "phase": "02-build"})
        self.assertIsNone(fix["parkedInto"])

        old = rows["todo-2026-09-01-old-card"]
        self.assertEqual(old["state"], "done")
        self.assertEqual(old["closed"], "2026-09-02 -- superseded")

        self.assertIs(rows["plan-2026-09-19-idea"]["check"], False)
        self.assertEqual(rows["plan-2026-09-19-idea"]["origin"], {"batch": DONE_BATCH, "phase": None})
        self.assertEqual(rows["plan-2026-09-16-from-phase"]["origin"], {"batch": DONE_BATCH, "phase": "01-setup"})
        parked = rows["plan-2026-09-17-parked"]
        self.assertEqual((parked["state"], parked["parkedInto"]), ("done", DONE_BATCH))
        self.assertIsNone(parked["origin"])

        xss = rows["todo-2026-09-21-xss"]
        self.assertIsNone(xss["origin"])
        self.assertIsNone(xss["parkedInto"])

    def test_entry_payload_is_the_row_plus_body(self):
        repo = self._world()
        entry = self._load(repo, "entry/todo-2026-09-01-old-card")
        row = self._entry(repo, "todo-2026-09-01-old-card")
        self.assertEqual({k: v for k, v in entry.items() if k != "bodyHtml"}, row)
        self.assertIn("superseded", entry["bodyHtml"])

    # ---- batch/<name>.js ----------------------------------------------------------------------------

    def test_batch_payload_of_the_done_batch(self):
        repo = self._world()
        b = self._load(repo, f"batch/{DONE_BATCH}")
        self.assertEqual(set(b), {
            "name", "status", "priority", "dependsOn", "branch", "base", "merged", "started", "finished",
            "outcome", "context", "planning", "phases", "cost", "notes", "fromPlan", "closing",
            "security", "flags",
        })
        self.assertEqual((b["name"], b["status"], b["outcome"]), (DONE_BATCH, "done", "MIXED"))
        self.assertEqual((b["branch"], b["base"], b["merged"]), (DONE_BRANCH, "main", True))
        self.assertEqual((b["started"], b["finished"]), ("2026-09-01T09:30:00+00:00", "2026-09-01T12:02:00Z"))
        self.assertEqual(
            [(f["phase"], f["level"], f["code"]) for f in b["flags"]],
            [
                ("01-setup", "warn", "reopened"),
                ("01-setup", "info", "parked-entries"),
                ("02-build", "warn", "red-attempt"),
                ("02-build", "info", "observations"),
                ("02-build", "info", "triggers"),
            ],
        )

        self.assertEqual(set(b["context"]), {"goal", "decisions", "invariants"})
        self.assertIn("<strong>portal</strong>", b["context"]["goal"])
        self.assertIn("<ul>", b["context"]["decisions"])
        self.assertIn("Never break the build.", b["context"]["invariants"])

        planning = b["planning"]
        self.assertEqual((planning["from"], planning["until"], planning["wallclock_s"]),
                         ("2026-08-31T09:00:00Z", "2026-08-31T10:00:00Z", 3600))
        self.assertTrue(planning["settled"])
        self.assertEqual(planning["cost"]["total"], T5(10, 20, 1000, 5000, 300))
        self.assertEqual(planning["cost"]["byModel"], {OPUS: T5(10, 20, 1000, 5000, 300)})

        self.assertEqual([p["slug"] for p in b["phases"]], ["01-setup", "02-build"])
        setup, build = b["phases"]
        self.assertEqual((setup["num"], setup["title"], setup["size"], setup["state"]), (1, "Setup phase", "S", "done"))
        self.assertEqual(setup["affectedFiles"], ["claude/setup.py"])
        self.assertEqual((build["num"], build["size"]), (2, "L"))
        self.assertEqual(build["affectedFiles"], ["claude/x.py", "claude/y.py"])
        self.assertIn("Some context with", build["planHtml"])
        self.assertEqual([f["code"] for f in setup["flags"]], ["reopened", "parked-entries"])
        self.assertEqual([f["code"] for f in build["flags"]], ["red-attempt", "observations", "triggers"])
        self.assertEqual(build["flags"][0]["text"], "1 red attempt")
        self.assertEqual([len(p["attempts"]) for p in b["phases"]], [1, 2])

        red, green = build["attempts"]
        self.assertEqual((red["status"], green["status"]), ("red", "green"))
        self.assertEqual(red["errors"], ["boom"])
        self.assertEqual(green["summary"], "built 02-build")
        self.assertEqual(green["verification"], "tests -> OK")
        self.assertEqual(green["deviations"], ["Touched y.py too"])
        self.assertEqual(green["observations"], ["The renderer is slow"])
        self.assertEqual(green["triggers"], ["omitted"])
        self.assertEqual(green["commit"], "abc123")
        self.assertEqual(green["question"], "")
        self.assertEqual(green["reopened"], "")
        self.assertEqual(setup["attempts"][0]["reopened"], "2026-09-01T10:40:00+00:00")
        self.assertEqual(green["diffstat"], DIFFSTAT)
        self.assertIsNone(red["diffstat"])
        self.assertEqual(green["filesTouched"], ["/repo/claude/x.py"])
        self.assertEqual(green["parkedPlanEntries"], [])
        self.assertEqual(setup["attempts"][0]["parkedPlanEntries"], ["plan/2026-09-16-from-phase.md"])
        self.assertEqual(green["time"], {"from": "2026-09-01T12:00:00Z", "until": "2026-09-01T12:02:00Z", "wallclock_s": 120})
        self.assertTrue(green["settled"])
        self.assertEqual(green["mode"], "orchestrator")
        self.assertEqual(green["tools"], {"Agent": 1, "Bash": 3})
        self.assertEqual(green["skills"], {"recommended": ["tdd"], "used": ["tdd"]})

        cost = green["cost"]
        self.assertEqual(cost["total"], T5(8, 16, 800, 5000, 110))
        self.assertEqual(cost["byModel"], {OPUS: T5(3, 6, 300, 2000, 50), SONNET: T5(5, 10, 500, 3000, 60)})
        self.assertEqual(cost["layers"]["worker"], {
            "total": T5(5, 10, 500, 3000, 60), "byModel": {SONNET: T5(5, 10, 500, 3000, 60)}, "count": 1,
        })
        self.assertEqual(cost["layers"]["main_explore"], {"total": T5(0, 0, 0, 0, 0), "byModel": {}, "count": 0})
        self.assertEqual(set(cost["layers"]), {"main", "main_explore", "worker", "worker_explore"})
        self.assertEqual(cost["agents"], [{
            "id": "agent-w1", "type": "cfq:cfq-phase-worker", "description": "Implement phase 02",
            "layer": "worker", "parent": None, "total": T5(5, 10, 500, 3000, 60),
            "byModel": {SONNET: T5(5, 10, 500, 3000, 60)},
        }])
        # the schema-2 attempt without layers still yields its totals as the main layer, no models
        self.assertEqual(setup["attempts"][0]["cost"]["layers"]["main"]["total"], T5(2, 4, 100, 500, 20))
        self.assertEqual(setup["attempts"][0]["cost"]["byModel"], {})
        self.assertEqual(setup["attempts"][0]["skills"], {"recommended": [], "used": []})

        self.assertEqual(b["cost"]["total"], T5(24, 48, 2300, 11500, 530))
        self.assertEqual(b["cost"]["layers"]["worker"]["total"], T5(5, 10, 500, 3000, 60))
        self.assertEqual(b["cost"]["layers"]["worker"]["count"], 1)
        self.assertEqual([a["id"] for a in b["cost"]["agents"]], ["agent-w1"])

        self.assertEqual(
            [(n["kind"], n["id"], n["state"], n["phase"], n["framework"]) for n in b["notes"]],
            [
                ("todo", "todo-2026-09-20-fix-thing", "open", "02-build", False),
                ("plan", "plan-2026-09-19-idea", "open", None, False),
                ("todo", "todo-2026-09-01-old-card", "done", "02-build", False),
                ("plan", "plan-2026-09-18-gone", "missing", "02-build", True),
            ],
        )
        self.assertEqual(b["notes"][0]["title"], "Fix the thing")
        self.assertEqual(b["notes"][0]["at"], "2026-09-01T12:01:00+00:00")
        self.assertEqual(b["fromPlan"], [{"id": "plan-2026-09-17-parked", "title": "Parked idea"}])
        self.assertEqual(b["closing"], FINISH)
        self.assertEqual(b["security"], SECURITY[-1])

    def test_open_batch_without_telemetry_falls_back(self):
        repo = self._world()
        b = self._load(repo, f"batch/{OPEN_BATCH}")
        self.assertEqual(b["status"], "in_progress")
        self.assertIsNone(b["cost"])
        self.assertIsNone(b["planning"])
        self.assertIsNone(b["closing"])
        self.assertIsNone(b["security"])
        self.assertEqual(b["notes"], [])
        self.assertEqual(b["fromPlan"], [])
        self.assertEqual([(p["slug"], p["state"]) for p in b["phases"]], [("01-a", "done"), ("02-b", "open"), ("03-c", "open")])
        attempt = b["phases"][0]["attempts"][0]
        self.assertIsNone(attempt["cost"])
        self.assertEqual(attempt["time"], {"from": "", "until": "", "wallclock_s": 0})
        self.assertEqual(attempt["tools"], {})
        self.assertEqual(b["phases"][1]["attempts"], [])

    def test_batch_without_report_json_still_gets_a_payload(self):
        repo = self._world()
        b = self._load(repo, f"batch/{BARE_BATCH}")
        self.assertEqual((b["status"], b["started"], b["finished"]), ("planned", "", ""))
        self.assertEqual([p["slug"] for p in b["phases"]], ["01-x"])
        self.assertIsNone(b["cost"])

    def test_invalid_report_json_falls_back_to_the_plan_files(self):
        repo = self.make_repo()
        impl = self._build_batch(repo, "2026-09-23-demo")
        (impl / "report.json").write_text("{ this is not json")
        self._sync(repo)
        b = self._load(repo, "batch/2026-09-23-demo")
        self.assertEqual([p["slug"] for p in b["phases"]], ["00-setup", "01-first"])
        self.assertEqual(b["phases"][0]["attempts"], [])
        self.assertIsNone(b["cost"])
        self.assertEqual(b["started"], "")

    def test_schema1_report_yields_layer_sums(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo", schema1=True)
        self._sync(repo)

        cost = self._load(repo, "batch/2026-09-23-demo")["cost"]
        self.assertEqual(cost["layers"]["main"]["total"]["turns"], SCHEMA1_TELEMETRY["totals"]["turns"])
        self.assertEqual(cost["layers"]["worker"]["total"]["turns"], SCHEMA1_TELEMETRY["subagent_worker"]["turns"])
        self.assertEqual(cost["layers"]["worker_explore"]["total"]["turns"], 0)
        self.assertEqual(cost["byModel"], {}, "a record without per-model data has an empty byModel")
        # `totals` and `subagent_worker` are disjoint pools in schema 1 -- the whole-batch total is
        # their sum, not `totals` alone.
        self.assertEqual(
            cost["total"]["turns"],
            SCHEMA1_TELEMETRY["totals"]["turns"] + SCHEMA1_TELEMETRY["subagent_worker"]["turns"],
        )

    def test_script_text_is_escaped_in_html_fields_and_plain_elsewhere(self):
        repo = self._world()
        row = self._row(repo, DONE_BATCH)
        self.assertNotIn("<script", row["goalHtml"])
        self.assertIn("&lt;script&gt;", row["goalHtml"])

        batch = self._load(repo, f"batch/{DONE_BATCH}")
        build = batch["phases"][1]
        self.assertNotIn("<script", build["planHtml"])
        self.assertIn("&lt;script&gt;alert(1)", build["planHtml"])
        self.assertEqual(build["title"], "Build the <script>alert('title')</script> thing")
        self.assertNotIn("<script", batch["context"]["goal"])
        self.assertIn("&lt;script&gt;", batch["context"]["goal"])

        entry = self._load(repo, "entry/todo-2026-09-21-xss")
        self.assertNotIn("<script", entry["bodyHtml"])
        self.assertIn("&lt;script&gt;alert(4)", entry["bodyHtml"])
        self.assertEqual(entry["title"], "Beware <script>alert(3)</script>")
        self.assertEqual(self._entry(repo, "todo-2026-09-21-xss")["title"], "Beware <script>alert(3)</script>")

    # ---- routine: a changed report.json rewrites that batch's file and queue.js only -------------

    def test_changed_report_json_rewrites_only_that_batch_and_the_queue(self):
        repo = self._world()
        report = self._cfq(repo) / "impl" / "done" / DONE_BATCH / "report.json"
        data = json.loads(report.read_text())
        data["phases"][2]["telemetry"]["layers"]["worker"]["output"] = 9999
        report.write_text(json.dumps(data))

        result = self._sync(repo)
        self.assertEqual(set(result["written"]), {"queue.js", f"batch/{DONE_BATCH}.js"})
        self.assertEqual(result["removed"], [])

    # ---- --batch filter: unselected batches keep their existing files, gain no new ones --------

    def test_batch_filter_builds_a_batch_without_data_file_in_full(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-alpha")
        self._build_batch(repo, "2026-09-23-beta")

        result = self._sync(repo, "--batch", "2026-09-23-alpha")
        self.assertIn("batch/2026-09-23-alpha.js", result["written"])
        # no data file yet: built in full although outside the filter
        self.assertIn("batch/2026-09-23-beta.js", result["written"])
        self.assertIn("queue.js", result["written"])

    def test_batch_filter_leaves_an_existing_unselected_file_alone(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-alpha")
        self._build_batch(repo, "2026-09-23-beta")
        self._sync(repo)
        beta = self._data_dir(repo) / "batch/2026-09-23-beta.js"
        before = beta.read_text()

        result = self._sync(repo, "--batch", "2026-09-23-alpha")
        self.assertEqual(result["written"], [])
        self.assertEqual(beta.read_text(), before)

    def test_batch_filter_recomputes_only_flags_of_an_unselected_batch(self):
        repo = self.make_repo()
        for name in ("2026-09-23-alpha", "2026-09-23-beta"):
            self._build_batch(repo, name)
        self._sync(repo)
        beta = self._data_dir(repo) / "batch/2026-09-23-beta.js"
        key, payload = self._payload(beta)
        # tamper with something the recompute must not touch, and drop a stored flag
        payload["outcome"] = "TAMPERED"
        payload["phases"][0]["title"] = "TAMPERED"
        payload["phases"][0]["flags"] = []
        beta.write_text(cfq_portal.render_data_file(key, payload))

        result = self._sync(repo, "--batch", "2026-09-23-alpha")
        self.assertEqual(result["written"], [])  # the stored flags already equal the recomputed ones
        self.assertEqual(self._load(repo, "batch/2026-09-23-beta")["outcome"], "TAMPERED")

        # a stale flag list is rewritten, everything else in the file stays as read
        payload["phases"][0]["flags"] = [{"level": "info", "code": "stale", "text": "x", "phase": "00-setup"}]
        beta.write_text(cfq_portal.render_data_file(key, payload))
        result = self._sync(repo, "--batch", "2026-09-23-alpha")
        self.assertEqual(result["written"], ["batch/2026-09-23-beta.js"])
        rewritten = self._load(repo, "batch/2026-09-23-beta")
        self.assertEqual(rewritten["outcome"], "TAMPERED")
        self.assertEqual(rewritten["phases"][0]["title"], "TAMPERED")
        self.assertEqual(rewritten["phases"][0]["flags"], [])

    def test_rebuild_is_sync_over_everything(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-alpha")
        self._build_batch(repo, "2026-09-23-beta")

        proc = self.run_cfq("portal", "rebuild", str(repo))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        result = self.json_out(proc)
        self.assertIn("batch/2026-09-23-alpha.js", result["written"])
        self.assertIn("batch/2026-09-23-beta.js", result["written"])

    # ---- rebuild --migrate: retiring the old per-batch HTML report (batch 040 phase 05) --------

    def test_migrate_removes_legacy_batch_html_but_keeps_the_shell(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        reports_dir = self._data_dir(repo).parent
        reports_dir.mkdir(parents=True, exist_ok=True)
        legacy_dated = reports_dir / "2026-09-23-demo.html"
        legacy_numbered = reports_dir / "038-2026-09-23-other.html"
        legacy_dated.write_text("<html>old per-batch report</html>")
        legacy_numbered.write_text("<html>old per-batch report</html>")
        (reports_dir / "index.html").write_text("<html>old collected index</html>")

        result = self.json_out(self.run_cfq("portal", "rebuild", str(repo), "--migrate"))
        self.assertEqual(result["status"], "OK")
        self.assertIn(str(legacy_dated), result["removed"])
        self.assertIn(str(legacy_numbered), result["removed"])
        self.assertFalse(legacy_dated.exists())
        self.assertFalse(legacy_numbered.exists())
        # The shell's own `index.html` survives migration -- it was already overwritten with the
        # real viewer shell by this same rebuild's ordinary sync step, not deleted by --migrate.
        self.assertEqual(
            (reports_dir / "index.html").read_text(), (PLUGIN_ROOT / "portal" / "index.html").read_text(),
        )

    def test_migrate_never_touches_assets_or_data(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        result = self.json_out(self.run_cfq("portal", "rebuild", str(repo), "--migrate"))
        self.assertEqual(result["status"], "OK")
        self.assertTrue((self._data_dir(repo) / "batch" / "2026-09-23-demo.js").is_file())
        reports_dir = self._data_dir(repo).parent
        self.assertTrue((reports_dir / "assets" / "core.js").is_file())

    def test_rebuild_without_migrate_leaves_legacy_html_untouched(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        self._sync(repo)  # installs the shell and stamps the version
        reports_dir = self._data_dir(repo).parent
        legacy = reports_dir / "2026-09-23-demo.html"
        legacy.write_text("<html>old</html>")

        result = self.json_out(self.run_cfq("portal", "rebuild", str(repo)))
        self.assertEqual(result["removed"], [])
        self.assertTrue(legacy.is_file(), "an unchanged version stamp must not touch legacy html")

    def test_shell_install_on_a_version_change_removes_legacy_html(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")
        self._sync(repo)
        reports_dir = self._data_dir(repo).parent
        legacy_dated = reports_dir / "2026-09-23-demo.html"
        legacy_numbered = reports_dir / "038-2026-09-23-other.html"
        for f in (legacy_dated, legacy_numbered):
            f.write_text("<html>old per-batch report</html>")
        (reports_dir / ".portal-version").write_text("0.0.0-stale")

        result = self._sync(repo)
        self.assertEqual(set(result["removed"]), {str(legacy_dated), str(legacy_numbered)})
        self.assertFalse(legacy_dated.exists())
        self.assertFalse(legacy_numbered.exists())
        self.assertTrue((reports_dir / "index.html").is_file(), "the shell itself survives")
        self.assertTrue((self._data_dir(repo) / "queue.js").is_file())

    def test_migrate_removes_reportdir_mirror_legacy_html(self):
        repo = self.make_repo("alpha")
        self._build_batch(repo, "2026-09-23-a")
        report_dir = self._repos_dir / "shared-reports"
        mirror_dir = report_dir / "alpha"
        mirror_dir.mkdir(parents=True)
        legacy = mirror_dir / "2026-09-23-a.html"
        legacy.write_text("<html>old</html>")

        result = self.json_out(self.run_cfq(
            "portal", "rebuild", str(repo), "--migrate", env={"CFQ_REPORT_DIR": str(report_dir)},
        ))
        self.assertEqual(result["status"], "OK")
        self.assertIn(str(legacy), result["removed"])
        self.assertFalse(legacy.exists())

    # ---- install: the fixed viewer shell -------------------------------------------------------

    def _plugin_version(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        return data["version"]

    def test_install_copies_shell_files_matching_portal_source(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        sources = sorted(f.name for f in (PLUGIN_ROOT / "portal").iterdir() if f.is_file())
        self.assertIn("core.js", sources)
        self.assertIn("app.js", sources)
        self.assertNotIn("viewer.js", sources)
        for src_name in sources:
            rel = "index.html" if src_name == "index.html" else f"assets/{src_name}"
            self.assertEqual(
                (reports_dir / rel).read_text(),
                (PLUGIN_ROOT / "portal" / src_name).read_text(),
                f"{rel} was not copied verbatim from portal/{src_name}",
            )
        self.assertEqual((reports_dir / ".portal-version").read_text().strip(), self._plugin_version())

    def test_install_copies_nothing_when_version_stamp_already_matches(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        # A local edit to the installed shell must survive an unchanged-version resync -- the
        # phase's own contract ("an unchanged version copies nothing") means zero file operations,
        # not a content-diff rewrite back to the plugin's own source.
        (reports_dir / "assets" / "style.css").write_text("/* locally edited */")

        result = self._sync(repo)
        self.assertNotIn("index.html", result["written"])
        self.assertNotIn("assets/core.js", result["written"])
        self.assertNotIn("assets/style.css", result["written"])
        self.assertEqual((reports_dir / "assets" / "style.css").read_text(), "/* locally edited */")

    def test_install_recopies_shell_when_version_stamp_differs(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        (reports_dir / ".portal-version").write_text("0.0.0-stale")
        (reports_dir / "assets" / "style.css").write_text("/* stale */")

        result = self._sync(repo)
        self.assertIn("assets/style.css", result["written"])
        self.assertEqual(
            (reports_dir / "assets" / "style.css").read_text(),
            (PLUGIN_ROOT / "portal" / "style.css").read_text(),
        )
        self.assertEqual((reports_dir / ".portal-version").read_text().strip(), self._plugin_version())

    def test_install_removes_stale_asset_files_on_a_version_change(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        stale = reports_dir / "assets" / "viewer.js"
        stale.write_text("// the retired single-file viewer")
        (reports_dir / ".portal-version").write_text("0.0.0-stale")

        result = self._sync(repo)
        self.assertFalse(stale.exists(), "a file portal/ no longer has is removed from assets/")
        self.assertIn(str(stale), result["removed"])
        for f in (PLUGIN_ROOT / "portal").iterdir():
            if f.name != "index.html":
                self.assertTrue((reports_dir / "assets" / f.name).is_file(), f.name)

    def test_install_leaves_assets_alone_when_version_stamp_matches(self):
        repo = self.make_repo()
        self._init_queue(repo)
        self._sync(repo)

        reports_dir = self._data_dir(repo).parent
        stray = reports_dir / "assets" / "viewer.js"
        stray.write_text("// untouched")
        self._sync(repo)
        self.assertTrue(stray.is_file(), "an unchanged stamp copies and removes nothing")

    def test_sync_without_reportdir_carries_no_mirror(self):
        repo = self.make_repo()
        self._init_queue(repo)
        result = self._sync(repo)
        self.assertIsNone(result["mirror"])

    # ---- reportDir mirror (batch 040 phase 03) --------------------------------------------------

    def test_reportdir_mirror(self):
        repo_a = self.make_repo("alpha")
        repo_b = self.make_repo("beta")
        self._build_batch(repo_a, "2026-09-23-a")
        self._build_batch(repo_b, "2026-09-23-b")

        report_dir = self._repos_dir / "shared-reports"
        report_dir.mkdir()
        env = {"CFQ_REPORT_DIR": str(report_dir)}

        result_a = self._sync(repo_a, env=env)
        result_b = self._sync(repo_b, env=env)

        # routine: both mirrored, repos.js has two rows -----------------------------------------
        self.assertEqual(result_a["mirror"]["status"], "OK")
        self.assertEqual(result_b["mirror"]["status"], "OK")

        for rel in ("index.html", "assets/core.js", "assets/overview.js", "assets/app.js", "assets/style.css"):
            self.assertTrue((report_dir / rel).is_file(), f"global shell {rel} not installed")
        self.assertTrue((report_dir / ".portal-version").is_file())

        site_key, site_payload = self._payload(report_dir / "data" / "site.js")
        self.assertEqual(site_key, "site")
        self.assertEqual(site_payload, {"mode": "global"})

        repos_key, repos_payload = self._payload(report_dir / "data" / "repos.js")
        self.assertEqual(repos_key, "repos")
        self.assertEqual(len(repos_payload), 2)
        by_source = {r["source"]: r for r in repos_payload}
        self.assertIn(str(repo_a.resolve()), by_source)
        self.assertIn(str(repo_b.resolve()), by_source)
        row_a = by_source[str(repo_a.resolve())]
        self.assertEqual(row_a["name"], "alpha")
        self.assertEqual(row_a["mirror"], "alpha")
        self.assertIn("batches", row_a["counts"])

        for repo, mirror_name, batch_name in (
            (repo_a, "alpha", "2026-09-23-a"), (repo_b, "beta", "2026-09-23-b"),
        ):
            mirror_data = report_dir / mirror_name / "data"
            for rel in ("site.js", "queue.js", f"batch/{batch_name}.js"):
                self.assertTrue((mirror_data / rel).is_file(), f"{mirror_name}: missing mirrored {rel}")
            _k, mirrored_queue = self._payload(mirror_data / "queue.js")
            _k2, repo_queue = self._payload(self._data_dir(repo) / "queue.js")
            self.assertEqual(mirrored_queue, repo_queue, f"{mirror_name}: mirrored queue.js diverges from repo-local")

        # a no-op re-sync of the same repo mirrors nothing new
        second = self._sync(repo_a, env=env)
        self.assertEqual(second["mirror"]["status"], "OK")
        self.assertEqual(second["mirror"]["written"], [])

    def test_reportdir_mirror_same_basename_gets_stable_distinct_directory(self):
        repo_1 = self.make_repo("dup")
        repo_2 = self.make_repo(str(pathlib.Path("nested") / "dup"))
        self._build_batch(repo_1, "2026-09-23-a")
        self._build_batch(repo_2, "2026-09-23-b")

        report_dir = self._repos_dir / "shared-reports"
        report_dir.mkdir()
        env = {"CFQ_REPORT_DIR": str(report_dir)}

        result_1 = self._sync(repo_1, env=env)
        result_2 = self._sync(repo_2, env=env)
        mirror_1 = result_1["mirror"]["written"]
        mirror_2 = result_2["mirror"]["written"]
        self.assertTrue(any(p.startswith("dup/data/") for p in mirror_1), mirror_1)
        second_mirror_dirs = {p.split("/", 1)[0] for p in mirror_2 if "/data/" in p}
        self.assertEqual(len(second_mirror_dirs), 1)
        second_mirror_dir = next(iter(second_mirror_dirs))
        self.assertNotEqual(second_mirror_dir, "dup")
        self.assertTrue(second_mirror_dir.startswith("dup-"), second_mirror_dir)

        repos_key, repos_payload = self._payload(report_dir / "data" / "repos.js")
        mirrors = {r["mirror"] for r in repos_payload}
        self.assertEqual(mirrors, {"dup", second_mirror_dir})

        # stable across a re-sync: the same repo keeps the same mirror name it was first assigned,
        # and an unchanged resync mirrors nothing new
        result_2_again = self._sync(repo_2, env=env)
        self.assertEqual(result_2_again["mirror"]["written"], [])
        _key, repos_payload_again = self._payload(report_dir / "data" / "repos.js")
        by_source = {r["source"]: r["mirror"] for r in repos_payload_again}
        self.assertEqual(by_source[str(repo_2.resolve())], second_mirror_dir)

    def test_reportdir_unwritable_falls_back_with_mirror_error(self):
        repo = self.make_repo()
        self._build_batch(repo, "2026-09-23-demo")

        robase = self._repos_dir / "readonly-parent"
        robase.mkdir()
        bad_report_dir = robase / "reports"
        robase.chmod(0o555)
        try:
            result = self._sync(repo, env={"CFQ_REPORT_DIR": str(bad_report_dir)})
        finally:
            robase.chmod(0o755)

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["mirror"]["status"], "ERROR")
        self.assertTrue(result["mirror"]["detail"])
        # the repo-local sync itself is unaffected by the mirror failure
        self.assertTrue((self._data_dir(repo) / "queue.js").is_file())
        self.assertTrue((self._data_dir(repo) / "batch/2026-09-23-demo.js").is_file())


if __name__ == "__main__":
    unittest.main()
