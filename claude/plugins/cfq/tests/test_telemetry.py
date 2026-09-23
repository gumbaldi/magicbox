"""Migrated from test-telemetry.sh (bin/cfq telemetry — record/sync)."""

import json
import re
import sys
import unittest

from cfq_testlib import CfqTestCase, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_report  # noqa: E402


TRANSCRIPT_TURNS = """\
{"type":"assistant","timestamp":"2026-08-13T10:00:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"high","attributionSkill":"code-for-queue:implement-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-sonnet-5","usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":10,"cache_creation_input_tokens":5},"content":[{"type":"text","text":"GEHEIMER_PROMPT_TEXT shows up in assistant prose here"}]}}
{"type":"assistant","timestamp":"2026-08-13T10:01:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"high","attributionSkill":"code-for-queue:implement-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-sonnet-5","usage":{"input_tokens":200,"output_tokens":80,"cache_read_input_tokens":20,"cache_creation_input_tokens":0},"content":[{"type":"tool_use","name":"Bash","input":{"command":"echo GEHEIMER_PROMPT_TEXT"}}]}}
{"type":"assistant","timestamp":"2026-08-13T10:02:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"medium","attributionSkill":"code-for-queue:plan-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-opus-5","usage":{"input_tokens":150,"output_tokens":60,"cache_read_input_tokens":15,"cache_creation_input_tokens":0},"content":[{"type":"text","text":"planning turn"}]}}
{"type":"assistant","timestamp":"2026-08-13T10:03:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":true,"effort":"medium","attributionSkill":"code-for-queue:plan-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-opus-5","usage":{"input_tokens":50,"output_tokens":20,"cache_read_input_tokens":5,"cache_creation_input_tokens":0},"content":[{"type":"text","text":"subagent turn"}]}}
"""

EXTRA_TURN = """\
{"type":"assistant","timestamp":"2026-08-13T10:04:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"high","attributionSkill":"code-for-queue:implement-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-sonnet-5","usage":{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"content":[{"type":"text","text":"one more turn"}]}}
"""


def _sub_line(ts, agent, usage=None, model="claude-sonnet-5", effort="high"):
    """One entry as a sub-agent transcript file (subagents/agent-*.jsonl) would carry it -- same
    shape as a main-transcript entry, plus attributionAgent."""
    usage = usage or {
        "input_tokens": 30, "output_tokens": 15,
        "cache_read_input_tokens": 2, "cache_creation_input_tokens": 0,
    }
    obj = {
        "type": "assistant",
        "timestamp": ts,
        "isSidechain": True,
        "effort": effort,
        "attributionAgent": agent,
        "attributionSkill": "cfq:implement-for-queue",
        "attributionPlugin": "cfq",
        "message": {"model": model, "usage": usage},
    }
    return json.dumps(obj, separators=(",", ":"))


def _write_meta(subdir, agent_id, agent_type, description="", spawn_depth=1, parent=None):
    """The sibling agent-<id>.meta.json a real subagents/ directory carries -- field names and
    shape verified against real session directories (agentType, description, spawnDepth, and
    parentAgentId only at depth >= 2)."""
    meta = {"agentType": agent_type, "description": description, "spawnDepth": spawn_depth}
    if parent:
        meta["parentAgentId"] = parent
    (subdir / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))


class TelemetryTest(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir()
        self.run_clean("git", "init", "-q", cwd=self.repo)
        self.batch = self.repo / ".claude" / "cfq" / "2026-01-01-demo"
        self.batch.mkdir(parents=True)

        # Mirrors cfq_runtime.py's slug_for exactly -- a tempfile-generated path can contain "_",
        # which the old `.replace("/", "-")` left untouched while slug_for now maps it to "-".
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.repo))
        self.tdir = self.home / ".claude" / "projects" / slug
        self.tdir.mkdir(parents=True)
        self.transcript = self.tdir / "testsid.jsonl"
        self.transcript.write_text(TRANSCRIPT_TURNS)

        self.jsonl = self.repo / ".claude" / "cfq" / "telemetry.jsonl"

        # Seed report.json with a phase entry, as implement-for-queue would via
        # cfq_report.append_phase() (phase record/commit's own ledger-write step).
        cfq_report.append_phase(
            str(self.batch), '{"phase":"01-foo","status":"green","summary":"test"}',
            record_telemetry=False,
        )

    def _record(self, *args, session="testsid"):
        return self.run_cfq(
            "telemetry", "record", *args,
            cwd=self.repo, env={"CLAUDE_CODE_SESSION_ID": session}, check=True,
        )

    def _last_record(self):
        return json.loads(self.jsonl.read_text().splitlines()[-1])

    def test_record_and_sync(self):
        # 1. First record call
        proc = self._record(str(self.batch), "phase", "01-foo")
        # billable_in = input + cache_creation (500 + 5 = 505), excluding cache_read (50) --
        # cache_read is shown in its own clause instead of silently folding into "in".
        self.assertEqual(
            proc.stdout.strip(), "telemetry: 4 turns, 210 out / 505 in (50 cached)",
            msg=f"unexpected record output: {proc.stdout!r}",
        )

        rec1 = self._last_record()

        self.assertEqual(rec1["totals"]["output"], 210, msg="totals.output, want 210 (50+80+60+20)")
        self.assertEqual(rec1["totals"]["cache_read"], 50, msg="totals.cache_read, want 50 (10+20+15+5)")

        by_model = {k: v["turns"] for k, v in rec1["by_model"].items()}
        self.assertEqual(by_model, {"claude-opus-5": 2, "claude-sonnet-5": 2}, msg="by_model")
        by_effort = {k: v["turns"] for k, v in rec1["by_effort"].items()}
        self.assertEqual(by_effort, {"high": 2, "medium": 2}, msg="by_effort")
        by_skill = {k: v["turns"] for k, v in rec1["by_skill"].items()}
        self.assertEqual(
            by_skill,
            {"code-for-queue:implement-for-queue": 2, "code-for-queue:plan-for-queue": 2},
            msg="by_skill",
        )

        self.assertEqual(rec1["tools"], {"Bash": 1}, msg="tools")
        # No subagents/ directory exists in this fixture -- the fourth (isSidechain:true) line in
        # TRANSCRIPT_TURNS is an ordinary main-session turn now (it still counts toward totals
        # above), not a sub-agent turn: sub-agent turns come only from the subagents/ directory.
        # This is the backwards-compatibility guarantee for the 328 existing records, all of which
        # were written with no such directory.
        self.assertEqual(rec1["subagent"]["turns"], 0, msg="subagent.turns, want 0 (no subagents/ dir)")
        self.assertEqual(rec1["by_agent"], {}, msg="by_agent empty with no subagents/ dir")
        self.assertEqual(rec1["mode"], "classic", msg="mode classic with no worker-attributed turns")
        self.assertEqual(rec1["subagent_worker"]["turns"], 0, msg="subagent_worker.turns, want 0 (no subagents/ dir)")
        self.assertEqual(rec1["subagent_explore"]["turns"], 0, msg="subagent_explore.turns, want 0 (no subagents/ dir)")

        # No prompt/tool-argument text ever reaches the stored record.
        n = self.jsonl.read_text().count("GEHEIMER_PROMPT_TEXT")
        self.assertEqual(n, 0, msg=f"telemetry.jsonl leaked prompt text ({n} hits)")

        # Structural whitelist: every leaf field name must be one we deliberately added.
        # subagent_worker/subagent_explore are additive top-level fields introduced by an earlier
        # phase; "count" is `layers`'s own leaf field (turns/output/... already existed in
        # `subagent`'s shape) -- `layers` itself is always present, even with zero agents, so
        # `count` shows up in every record from here on, not only ones with a subagents/ dir.
        allowed = {
            "schema", "kind", "repo", "batch", "phase", "mode", "session_id", "branch",
            "cc_version", "from", "until", "wallclock_s", "turns", "input", "output",
            "cache_read", "cache_creation", "billable_in", "Bash",
            "subagent_worker", "subagent_explore", "count",
        }
        leaves = set(_leaf_keys(rec1))
        extra = leaves - allowed
        self.assertEqual(extra, set(), msg=f"unexpected leaf field(s) in telemetry record: {extra}")

        # report.json got the telemetry block attached to the last phase.
        report = json.loads((self.batch / "report.json").read_text())
        self.assertEqual(
            report["phases"][-1]["telemetry"], rec1,
            msg="report.json .phases[-1].telemetry does not match recorded telemetry",
        )

        # 2. Second record call of the same session only picks up the new line (window logic)
        with self.transcript.open("a") as f:
            f.write(EXTRA_TURN)
        self._record(str(self.batch), "phase", "01-foo")
        rec2 = self._last_record()
        self.assertEqual(rec2["totals"]["turns"], 1, msg="windowed record turns, want 1")

        # 3. kind=planning writes to .planning instead of .phases[-1].telemetry
        self._record(str(self.batch), "planning")
        rec3 = self._last_record()
        report = json.loads((self.batch / "report.json").read_text())
        self.assertEqual(
            report["planning"], rec3, msg="report.json .planning does not match recorded telemetry"
        )

        # 4. Fail-soft: no transcript found -> exit 0, no telemetry.jsonl written
        repo2 = self._repos_dir / "repo2"
        repo2.mkdir()
        self.run_clean("git", "init", "-q", cwd=repo2)
        batch2 = repo2 / ".claude" / "cfq" / "2026-01-02-empty"
        batch2.mkdir(parents=True)
        home_empty = self._repos_dir / "home-empty"
        home_empty.mkdir()
        proc = self.run_cfq(
            "telemetry", "record", str(batch2), "phase", "02-bar",
            home=home_empty, cwd=repo2, env={"CLAUDE_CODE_SESSION_ID": "nope"},
        )
        self.assertEqual(proc.returncode, 0, msg="record without transcript should exit 0")
        self.assertFalse(
            (repo2 / ".claude" / "cfq" / "telemetry.jsonl").exists(),
            msg="telemetry.jsonl written despite missing transcript",
        )

        # 5. Sync path, no network: local git target without a remote
        target = self._repos_dir / "target"
        target.mkdir()
        self.run_clean("git", "init", "-q", cwd=target)
        self.run_clean("git", "config", "user.email", "test@example.com", cwd=target)
        self.run_clean("git", "config", "user.name", "Test", cwd=target)
        self.run_cfq("settings", "set", "telemetrySyncRepo", str(target), check=True)

        proc = self.run_cfq("telemetry", "sync", str(self.repo))
        self.assertEqual(proc.returncode, 0, msg="sync exited non-zero despite a failed push (must stay non-fatal)")
        out = proc.stdout + proc.stderr
        self.assertIn("non-fatal", out, msg=f"sync output missing non-fatal note: {out}")
        name = f"{self.repo.name}.jsonl"
        lines_target = len((target / name).read_text().splitlines())
        lines_src = len(self.jsonl.read_text().splitlines())
        self.assertEqual(lines_target, lines_src, msg=f"sync copied {lines_target} lines, want {lines_src}")

        proc = self.run_cfq("telemetry", "sync", str(self.repo))
        out = proc.stdout + proc.stderr
        self.assertEqual(out.strip(), "telemetry sync: nothing new", msg=f"second sync = {out!r}")

    def test_whitelist_rejects_unknown_leaf_field(self):
        # The structural guard's rejection path, asserted directly rather than only ever
        # exercised via acceptance: a stray leaf field must show up as `extra`, not disappear.
        allowed = {"turns", "output"}
        bad_record = {"turns": 1, "output": 2, "prompt_text": "this must never land on disk"}
        leaves = set(_leaf_keys(bad_record))
        extra = leaves - allowed
        self.assertEqual(
            extra, {"prompt_text"}, msg="whitelist check failed to flag an unknown leaf field",
        )

    def _subagent_dir(self):
        d = self.tdir / "testsid" / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_subagent_worker_turns_populate_by_agent_and_orchestrator_mode(self):
        subdir = self._subagent_dir()
        (subdir / "agent-1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:30.000Z", "cfq:cfq-phase-worker") + "\n"
            + _sub_line("2026-08-13T10:01:30.000Z", "cfq:cfq-phase-worker") + "\n"
        )
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        self.assertEqual(rec["subagent"]["turns"], 2, msg="subagent.turns, want 2")
        self.assertIn("cfq:cfq-phase-worker", rec["by_agent"], msg="by_agent missing the worker")
        self.assertEqual(rec["mode"], "orchestrator")
        self.assertEqual(rec["totals"]["turns"], 4, msg="totals stays the orchestrator's own session")
        self.assertEqual(rec["subagent_worker"]["turns"], 2, msg="subagent_worker.turns, want 2")
        self.assertEqual(rec["subagent_explore"]["turns"], 0, msg="subagent_explore.turns, want 0")

    def test_subagent_explore_only_stays_classic_mode(self):
        subdir = self._subagent_dir()
        (subdir / "agent-1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:30.000Z", "Explore") + "\n"
        )
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        self.assertEqual(rec["subagent"]["turns"], 1, msg="subagent.turns, want 1")
        self.assertIn("Explore", rec["by_agent"])
        self.assertNotIn("cfq:cfq-phase-worker", rec["by_agent"])
        self.assertEqual(
            rec["mode"], "classic",
            msg="Explore-only sub-agent usage must not be read as orchestrator mode",
        )
        self.assertEqual(rec["totals"]["turns"], 4, msg="totals stays the orchestrator's own session")
        self.assertEqual(rec["subagent_worker"]["turns"], 0, msg="subagent_worker.turns, want 0")
        self.assertEqual(rec["subagent_explore"]["turns"], 1, msg="subagent_explore.turns, want 1")

    def test_subagent_worker_and_explore_split_do_not_bleed(self):
        # The regression from Context: a window with both a phase worker and an Explore agent
        # must partition cleanly -- neither field counts the other's turns, and `subagent` (the
        # unchanged collapsed sum) still equals their total.
        subdir = self._subagent_dir()
        (subdir / "agent-1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:15.000Z", "cfq:cfq-phase-worker") + "\n"
            + _sub_line("2026-08-13T10:00:30.000Z", "cfq:cfq-phase-worker") + "\n"
        )
        (subdir / "agent-2.jsonl").write_text(
            _sub_line("2026-08-13T10:00:45.000Z", "Explore") + "\n"
        )
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        self.assertEqual(rec["subagent"]["turns"], 3, msg="subagent.turns, want 3 (2 worker + 1 explore)")
        self.assertEqual(rec["subagent_worker"]["turns"], 2, msg="subagent_worker.turns, want 2")
        self.assertEqual(rec["subagent_explore"]["turns"], 1, msg="subagent_explore.turns, want 1")
        self.assertEqual(
            rec["subagent_worker"]["turns"] + rec["subagent_explore"]["turns"], rec["subagent"]["turns"],
            msg="subagent_worker + subagent_explore must sum back to subagent",
        )
        self.assertEqual(
            rec["subagent_worker"]["output"] + rec["subagent_explore"]["output"], rec["subagent"]["output"],
            msg="subagent_worker + subagent_explore output must sum back to subagent",
        )
        self.assertEqual(rec["mode"], "orchestrator", msg="a phase worker present still means orchestrator mode")

    def test_subagent_entries_outside_window_excluded(self):
        subdir = self._subagent_dir()
        agent_file = subdir / "agent-1.jsonl"
        agent_file.write_text(_sub_line("2026-08-13T10:00:30.000Z", "cfq:cfq-phase-worker") + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        rec1 = self._last_record()
        self.assertEqual(rec1["subagent"]["turns"], 1, msg="first window: 1 sub-agent turn")

        # Second call: bump the window forward. The old entry (before the new `since`) and a
        # deliberately-future entry (after the new `until`) must both be excluded; only the entry
        # that actually falls inside (since, until] counts.
        with self.transcript.open("a") as f:
            f.write(EXTRA_TURN)
        with agent_file.open("a") as f:
            f.write(_sub_line("2026-08-13T10:03:30.000Z", "cfq:cfq-phase-worker") + "\n")
            f.write(_sub_line("2026-08-13T10:05:00.000Z", "cfq:cfq-phase-worker") + "\n")

        self._record(str(self.batch), "phase", "01-foo")
        rec2 = self._last_record()
        self.assertEqual(
            rec2["subagent"]["turns"], 1,
            msg="only the entry inside the new (since, until] window counts",
        )
        self.assertEqual(rec2["totals"]["turns"], 1, msg="totals stays windowed the same as before")

    # -- agents/layers (schema 2) -------------------------------------------------------------

    def _scenario_orchestrator(self):
        """routine: an orchestrator-mode phase -- one worker (model sonnet, effort high) that
        spawned one Explore agent (haiku), plus one Explore agent spawned by the session."""
        subdir = self._subagent_dir()
        (subdir / "agent-w1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:15.000Z", "cfq:cfq-phase-worker", model="claude-sonnet-5", effort="high")
            + "\n"
        )
        _write_meta(subdir, "w1", "cfq:cfq-phase-worker", description="Implement phase 01", spawn_depth=1)
        (subdir / "agent-e1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:30.000Z", "Explore", model="claude-haiku-5", effort="high") + "\n"
        )
        _write_meta(subdir, "e1", "Explore", description="worker's own explore", spawn_depth=2, parent="w1")
        (subdir / "agent-e2.jsonl").write_text(
            _sub_line("2026-08-13T10:00:45.000Z", "Explore", model="claude-sonnet-5", effort="high") + "\n"
        )
        _write_meta(subdir, "e2", "Explore", description="session's own explore", spawn_depth=1)
        self._record(str(self.batch), "phase", "01-foo")
        return self._last_record()

    def _scenario_classic(self):
        """routine: a classic phase -- session plus one Explore agent, no worker
        (worker/worker_explore are zero)."""
        subdir = self._subagent_dir()
        (subdir / "agent-e1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:30.000Z", "Explore") + "\n"
        )
        _write_meta(subdir, "e1", "Explore", spawn_depth=1)
        self._record(str(self.batch), "phase", "01-foo")
        return self._last_record()

    def _scenario_missing_meta(self):
        """edge: a meta file missing for one agent (counts as main_explore, no crash)."""
        subdir = self._subagent_dir()
        (subdir / "agent-nometa.jsonl").write_text(
            _sub_line("2026-08-13T10:00:30.000Z", "Explore") + "\n"
        )
        self._record(str(self.batch), "phase", "01-foo")
        return self._last_record()

    def _scenario_stale_agent_excluded(self):
        """edge: an agent with no turns in the window is not listed."""
        subdir = self._subagent_dir()
        (subdir / "agent-stale.jsonl").write_text(
            _sub_line("2026-08-13T10:00:15.000Z", "Explore") + "\n"
        )
        _write_meta(subdir, "stale", "Explore", spawn_depth=1)
        self._record(str(self.batch), "phase", "01-foo")
        with self.transcript.open("a") as f:
            f.write(EXTRA_TURN)
        self._record(str(self.batch), "phase", "01-foo")
        return self._last_record()

    def _assert_layers_invariant(self, rec):
        """main + main_explore + worker + worker_explore == totals + subagent, field by field --
        the one invariant every fixture in this file must hold."""
        layers = rec["layers"]
        totals, subagent = rec["totals"], rec["subagent"]
        for field in ("turns", "input", "output", "cache_read", "cache_creation", "billable_in"):
            want = totals[field] + subagent[field]
            got = sum(layers[name][field] for name in ("main", "main_explore", "worker", "worker_explore"))
            self.assertEqual(got, want, msg=f"layers invariant broke on {field}: {got} != {want}")

    def test_layers_invariant_holds_for_every_fixture(self):
        # Each scenario needs its own clean repo/session -- re-running setUp() between
        # iterations gets a fresh CfqTestCase environment (temp home + temp repo), the same one
        # every other test method in this class starts from.
        scenarios = (
            ("orchestrator", self._scenario_orchestrator),
            ("classic", self._scenario_classic),
            ("missing_meta", self._scenario_missing_meta),
            ("stale_agent_excluded", self._scenario_stale_agent_excluded),
        )
        for name, build in scenarios:
            with self.subTest(scenario=name):
                self.setUp()
                self._assert_layers_invariant(build())

    def test_agents_and_layers_orchestrator_mode(self):
        rec = self._scenario_orchestrator()

        nodes_by_id = {n["id"]: n for n in rec["agents"]}
        self.assertEqual(set(nodes_by_id), {"w1", "e1", "e2"}, msg="agents list")
        self.assertEqual(nodes_by_id["w1"]["layer"], "worker")
        self.assertEqual(nodes_by_id["e1"]["layer"], "worker_explore", msg="e1's parent chain reaches the worker")
        self.assertEqual(nodes_by_id["e2"]["layer"], "main_explore", msg="e2 was spawned by the session, not the worker")
        self.assertEqual(nodes_by_id["e1"]["parent"], "w1")
        self.assertIsNone(nodes_by_id["w1"]["parent"])
        self.assertEqual(nodes_by_id["w1"]["depth"], 1)
        self.assertEqual(nodes_by_id["e1"]["depth"], 2)
        self.assertEqual(nodes_by_id["w1"]["models"], ["claude-sonnet-5"])
        self.assertEqual(nodes_by_id["w1"]["efforts"], ["high"])
        self.assertEqual(nodes_by_id["e1"]["models"], ["claude-haiku-5"])
        self.assertEqual(nodes_by_id["w1"]["description"], "Implement phase 01")

        layers = rec["layers"]
        self.assertEqual(layers["worker"]["count"], 1)
        self.assertEqual(layers["worker"]["turns"], 1)
        self.assertEqual(layers["worker"]["models"], ["claude-sonnet-5"])
        self.assertEqual(layers["worker_explore"]["count"], 1)
        self.assertEqual(layers["worker_explore"]["turns"], 1)
        self.assertEqual(layers["worker_explore"]["models"], ["claude-haiku-5"])
        self.assertEqual(layers["main_explore"]["count"], 1)
        self.assertEqual(layers["main_explore"]["turns"], 1)
        self.assertEqual(layers["main"]["count"], 1)
        self.assertEqual(layers["main"]["turns"], rec["totals"]["turns"])
        self.assertEqual(layers["main"], {**rec["totals"], "models": layers["main"]["models"], "efforts": layers["main"]["efforts"], "count": 1})

        self._assert_layers_invariant(rec)

    def test_agents_and_layers_classic_mode_no_worker(self):
        rec = self._scenario_classic()

        self.assertEqual(rec["layers"]["worker"], {
            "turns": 0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
            "billable_in": 0, "models": [], "efforts": [], "count": 0,
        })
        self.assertEqual(rec["layers"]["worker_explore"]["count"], 0)
        self.assertEqual(rec["layers"]["main_explore"]["count"], 1)
        self.assertEqual(rec["layers"]["main_explore"]["turns"], 1)

        self._assert_layers_invariant(rec)

    def test_agents_missing_meta_counts_as_main_explore(self):
        rec = self._scenario_missing_meta()

        node = next(n for n in rec["agents"] if n["id"] == "nometa")
        self.assertEqual(node["layer"], "main_explore")
        self.assertEqual(node["depth"], 1)
        self.assertIsNone(node["parent"])
        self.assertEqual(node["type"], "Explore", msg="type falls back to the turn's own attributionAgent")

        self._assert_layers_invariant(rec)

    def test_agent_with_no_turns_in_window_is_not_listed(self):
        rec = self._scenario_stale_agent_excluded()
        self.assertEqual(rec["agents"], [], msg="an agent with no turns in the new window is not listed")
        self._assert_layers_invariant(rec)

    def test_planning_record_mode_is_empty(self):
        self._record(str(self.batch), "planning")
        rec = self._last_record()
        self.assertEqual(rec["mode"], "", msg="mode is empty on planning records, like phase")
        self.assertEqual(rec["by_agent"], {})

    def test_planning_record_populates_subagent_explore(self):
        # pfq delegates to Explore agents; that usage must not stay invisible just because a
        # planning session has no orchestrator `mode` to attach it to.
        subdir = self._subagent_dir()
        (subdir / "agent-1.jsonl").write_text(
            _sub_line("2026-08-13T10:00:30.000Z", "Explore") + "\n"
        )
        self._record(str(self.batch), "planning")
        rec = self._last_record()
        self.assertEqual(rec["mode"], "", msg="mode stays empty on planning records")
        self.assertEqual(rec["subagent_explore"]["turns"], 1, msg="planning subagent_explore.turns, want 1")
        self.assertGreater(rec["subagent_explore"]["output"], 0, msg="planning subagent_explore.output, want > 0")

    def test_bootstrap_kind(self):
        proc = self.run_cfq(
            "telemetry", "record", str(self.batch), "bootstrap", "implement-for-queue", "3", "420",
            check=True,
        )
        self.assertEqual(
            proc.stdout.strip(), "telemetry: bootstrap implement-for-queue 3 calls / 420 ms",
            msg=f"unexpected bootstrap record output: {proc.stdout!r}",
        )

        rec6 = self._last_record()
        self.assertEqual(rec6["kind"], "bootstrap", msg="bootstrap kind")
        self.assertEqual(rec6["skill"], "implement-for-queue", msg="bootstrap skill")
        self.assertEqual(rec6["call_count"], 3, msg="bootstrap call_count")
        self.assertEqual(rec6["duration_ms"], 420, msg="bootstrap duration_ms")

        allowed_bootstrap = {
            "schema", "kind", "repo", "batch", "skill", "call_count", "duration_ms", "timestamp",
        }
        leaves6 = set(_leaf_keys(rec6))
        extra6 = leaves6 - allowed_bootstrap
        self.assertEqual(
            extra6, set(), msg=f"unexpected leaf field(s) in bootstrap telemetry record: {extra6}"
        )

        # Non-numeric callCount/durationMs is rejected, not silently coerced.
        proc = self.run_cfq(
            "telemetry", "record", str(self.batch), "bootstrap", "implement-for-queue",
            "notanumber", "420",
        )
        self.assertNotEqual(proc.returncode, 0, msg="bootstrap accepted a non-numeric callCount")


class TelemetryShowTest(CfqTestCase):
    """`telemetry show <repo-root> [--session]` -- the read verb pfq's Cost line needs instead of
    estimating its own token usage."""

    def setUp(self):
        super().setUp()
        self.repo = self._repos_dir / "repo"
        self.repo.mkdir()
        self.run_clean("git", "init", "-q", cwd=self.repo)
        self.jsonl_dir = self.repo / ".claude" / "cfq"
        self.jsonl_dir.mkdir(parents=True)
        self.jsonl = self.jsonl_dir / "telemetry.jsonl"

        rec_a = {
            "schema": 1, "kind": "phase", "session_id": "sess-a",
            "totals": {"turns": 3, "output": 300, "billable_in": 250, "cache_read": 10},
            "by_model": {"claude-sonnet-5": {}}, "by_effort": {"high": {}},
            "subagent_explore": {"turns": 1, "output": 50},
        }
        rec_b = {
            "schema": 1, "kind": "phase", "session_id": "sess-b",
            "totals": {"turns": 5, "output": 500, "billable_in": 400, "cache_read": 20},
            "by_model": {"claude-opus-5": {}}, "by_effort": {"medium": {}},
            "subagent_explore": {"turns": 2, "output": 80},
        }
        self.jsonl.write_text(json.dumps(rec_a) + "\n" + json.dumps(rec_b) + "\n")

    def test_show_whole_file_aggregates_every_session(self):
        proc = self.run_cfq("telemetry", "show", str(self.repo), check=True)
        out = json.loads(proc.stdout)
        self.assertEqual(out["turns"], 8, msg=f"turns = {out}")
        self.assertEqual(out["output"], 800, msg=f"output = {out}")
        self.assertEqual(out["billable_in"], 650, msg=f"billable_in = {out}")
        self.assertEqual(out["cache_read"], 30, msg=f"cache_read = {out}")
        self.assertEqual(out["models"], "claude-opus-5,claude-sonnet-5", msg=f"models = {out}")
        self.assertEqual(out["efforts"], "high,medium", msg=f"efforts = {out}")
        self.assertEqual(out["subagent_explore"], {"turns": 3, "output": 130}, msg=f"subagent_explore = {out}")

    def test_show_session_filters_to_current_session_only(self):
        # The `(verbatim)` check: same session-id extraction cmd_record already uses, now reused
        # by `show --session` -- this is the one case that distinguishes it from a whole-file read.
        proc = self.run_cfq(
            "telemetry", "show", str(self.repo), "--session",
            env={"CLAUDE_CODE_SESSION_ID": "sess-a"}, check=True,
        )
        out = json.loads(proc.stdout)
        self.assertEqual(out["turns"], 3, msg=f"turns = {out}")
        self.assertEqual(out["output"], 300, msg=f"output = {out}")
        self.assertEqual(out["billable_in"], 250, msg=f"billable_in = {out}")
        self.assertEqual(out["cache_read"], 10, msg=f"cache_read = {out}")
        self.assertEqual(out["models"], "claude-sonnet-5", msg=f"models = {out}")
        self.assertEqual(out["efforts"], "high", msg=f"efforts = {out}")
        self.assertEqual(out["subagent_explore"], {"turns": 1, "output": 50}, msg=f"subagent_explore = {out}")

    def test_show_missing_jsonl_returns_zeros_not_an_error(self):
        empty_repo = self._repos_dir / "repo-empty"
        empty_repo.mkdir()
        proc = self.run_cfq("telemetry", "show", str(empty_repo), check=True)
        out = json.loads(proc.stdout)
        self.assertEqual(
            out, {
                "turns": 0, "output": 0, "billable_in": 0, "cache_read": 0,
                "models": "", "efforts": "", "subagent_explore": {"turns": 0, "output": 0},
            },
            msg=f"missing telemetry.jsonl should aggregate to all zeros, got {out}",
        )


def _leaf_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from _leaf_keys(v)
            else:
                yield k
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaf_keys(v)


if __name__ == "__main__":
    unittest.main()
