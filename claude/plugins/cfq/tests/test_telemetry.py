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


def _resp_line(ts, mid, output, content=None, model="claude-sonnet-5", agent=None,
               inp=100, cache_read=10, cache_creation=5):
    """One transcript line of a response -- Claude Code writes one such line per content block,
    each repeating the response's message.id and usage. `mid=None` omits the id entirely."""
    message = {
        "model": model,
        "usage": {
            "input_tokens": inp, "output_tokens": output,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_creation,
        },
        "content": content if content is not None else [{"type": "text", "text": "x"}],
    }
    if mid is not None:
        message["id"] = mid
    obj = {"type": "assistant", "timestamp": ts, "effort": "high", "message": message}
    if agent:
        obj["attributionAgent"] = agent
    return json.dumps(obj, separators=(",", ":"))


def _write_meta(subdir, agent_id, agent_type, description="", spawn_depth=1, parent=None,
                tool_use_id=None):
    """The sibling agent-<id>.meta.json a real subagents/ directory carries -- field names and
    shape verified against real session directories (agentType, description, spawnDepth, and
    parentAgentId only at depth >= 2)."""
    meta = {"agentType": agent_type, "description": description, "spawnDepth": spawn_depth}
    if parent:
        meta["parentAgentId"] = parent
    if tool_use_id:
        meta["toolUseId"] = tool_use_id
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

    def test_record_attaches_only_to_matching_last_phase(self):
        # routine: report.json's last entry already matches the phase being recorded -- the guard
        # is a no-op on the normal path, telemetry still attaches exactly as before.
        cfq_report.append_phase(
            str(self.batch), '{"phase":"02-bar","status":"green","summary":"test"}',
            record_telemetry=False,
        )
        proc = self._record(str(self.batch), "phase", "02-bar")
        self.assertEqual(proc.stderr, "", msg="a matching last phase must not warn on stderr")
        rec = self._last_record()
        report = json.loads((self.batch / "report.json").read_text())
        self.assertEqual(
            report["phases"][-1].get("telemetry"), rec,
            msg="last entry's own phase matches -- must still gain telemetry",
        )

        # the repro from batch 032: a phase plan's own verification step names
        # `telemetry record <dir> phase <slug>` and runs it *before* that phase's own
        # `phase commit` appends its entry -- report.json's last entry is still the *previous*
        # phase ("02-bar", carrying the telemetry just attached above) at that point.
        before = json.loads((self.batch / "report.json").read_text())
        lines_before = len(self.jsonl.read_text().splitlines())
        proc = self._record(str(self.batch), "phase", "03-baz")
        after = json.loads((self.batch / "report.json").read_text())
        self.assertEqual(
            after, before,
            msg="report.json must stay byte-for-byte unchanged when the last phase does not match",
        )
        lines_after = len(self.jsonl.read_text().splitlines())
        self.assertEqual(
            lines_after, lines_before + 1,
            msg="the raw record must still land on telemetry.jsonl even when report.json is left alone",
        )
        self.assertIn("02-bar", proc.stderr, msg="stderr must name report.json's actual last phase")
        self.assertIn("03-baz", proc.stderr, msg="stderr must name the phase that was requested")
        self.assertEqual(proc.returncode, 0, msg="a mismatched last phase must still exit 0")

    def test_record_planning_ignores_phase_guard(self):
        # edge: kind=="planning" still writes data["planning"] unconditionally, regardless of
        # whether report.json's last phase entry matches anything -- the guard is phase-only.
        cfq_report.append_phase(
            str(self.batch), '{"phase":"02-bar","status":"green","summary":"test"}',
            record_telemetry=False,
        )
        self._record(str(self.batch), "planning")
        rec = self._last_record()
        report = json.loads((self.batch / "report.json").read_text())
        self.assertEqual(
            report["planning"], rec, msg="planning must attach even with an unrelated last phase"
        )
        self.assertNotIn(
            "telemetry", report["phases"][-1],
            msg="planning must never attach telemetry to a phase entry",
        )

    def test_record_empty_phases_list_is_a_noop(self):
        # edge: report.json exists (e.g. written by a planning-time call) but `phases` is still
        # empty -- nothing is written to report.json, and the guard must not crash on an empty
        # list's `[-1]` lookup.
        report_path = self.batch / "report.json"
        report_path.write_text(json.dumps({"repo": str(self.repo), "batch": self.batch.name, "phases": []}))
        proc = self._record(str(self.batch), "phase", "01-foo")
        self.assertEqual(proc.returncode, 0, msg="an empty phases list must not crash the guard")
        report = json.loads(report_path.read_text())
        self.assertEqual(report.get("phases"), [], msg="report.json must stay untouched")

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

    def test_subagent_attributed_once_by_first_response(self):
        # No meta, no link: the agent belongs to the record whose main window holds its first
        # response, with all of its responses -- later records do not count it again.
        subdir = self._subagent_dir()
        agent_file = subdir / "agent-1.jsonl"
        agent_file.write_text(_sub_line("2026-08-13T10:00:30.000Z", "cfq:cfq-phase-worker") + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        rec1 = self._last_record()
        self.assertEqual(rec1["subagent"]["turns"], 1, msg="first window: 1 sub-agent turn")

        with self.transcript.open("a") as f:
            f.write(EXTRA_TURN)
        with agent_file.open("a") as f:
            f.write(_sub_line("2026-08-13T10:03:30.000Z", "cfq:cfq-phase-worker") + "\n")
            f.write(_sub_line("2026-08-13T10:05:00.000Z", "cfq:cfq-phase-worker") + "\n")

        self._record(str(self.batch), "phase", "01-foo")
        rec2 = self._last_record()
        self.assertEqual(rec2["subagent"]["turns"], 0, msg="the agent's first response is outside the new window")
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
        self.assertEqual(layers["main"], {**rec["totals"], "models": layers["main"]["models"], "efforts": layers["main"]["efforts"], "count": 1, "by_model": rec["by_model"]})

        self._assert_layers_invariant(rec)

    def test_agents_and_layers_classic_mode_no_worker(self):
        rec = self._scenario_classic()

        self.assertEqual(rec["layers"]["worker"], {
            "turns": 0, "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
            "billable_in": 0, "models": [], "efforts": [], "count": 0, "by_model": {},
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

    # -- attribution by spawning tool call -----------------------------------------------------

    def _agent_call_line(self, ts, mid, tool_id):
        obj = json.loads(_resp_line(
            ts, mid, 10,
            [{"type": "tool_use", "id": tool_id, "name": "Agent", "input": {}}],
        ))
        obj["sessionId"] = "testsid"
        return json.dumps(obj, separators=(",", ":"))

    def _write_agent(self, subdir, aid, atype, stamps, **meta):
        (subdir / f"agent-{aid}.jsonl").write_text(
            "\n".join(_sub_line(t, atype) for t in stamps) + "\n"
        )
        if meta is not None:
            _write_meta(subdir, aid, atype, **meta)

    def test_worker_turns_after_main_window_are_attributed_by_tool_use_id(self):
        # The regression: the main transcript stopped at the Agent call, every worker response
        # is later than its last line.
        self.transcript.write_text(self._agent_call_line("2026-08-13T10:00:00.000Z", "msg_m1", "toolu_A") + "\n")
        subdir = self._subagent_dir()
        self._write_agent(
            subdir, "a1", "cfq:cfq-phase-worker",
            ["2026-08-13T10:05:00.000Z", "2026-08-13T10:06:00.000Z", "2026-08-13T10:07:00.000Z"],
            tool_use_id="toolu_A",
        )
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        self.assertEqual(rec["layers"]["worker"]["turns"], 3)
        self.assertEqual(rec["layers"]["worker"]["output"], 45)
        self.assertEqual(rec["mode"], "orchestrator")
        self.assertEqual(rec["subagent_worker"]["turns"], 3)
        self._assert_layers_invariant(rec)

    def test_second_record_in_one_session_does_not_recount_first_agent(self):
        self.transcript.write_text(self._agent_call_line("2026-08-13T10:00:00.000Z", "msg_m1", "toolu_A") + "\n")
        subdir = self._subagent_dir()
        self._write_agent(
            subdir, "a1", "cfq:cfq-phase-worker",
            ["2026-08-13T10:05:00.000Z", "2026-08-13T10:15:00.000Z"], tool_use_id="toolu_A",
        )
        self._record(str(self.batch), "phase", "01-foo")
        rec1 = self._last_record()
        self.assertEqual(rec1["layers"]["worker"]["turns"], 2)

        with self.transcript.open("a") as f:
            f.write(self._agent_call_line("2026-08-13T10:10:00.000Z", "msg_m2", "toolu_B") + "\n")
        self._write_agent(
            subdir, "a2", "cfq:cfq-phase-worker", ["2026-08-13T10:12:00.000Z"], tool_use_id="toolu_B",
        )
        self._record(str(self.batch), "phase", "02-foo")
        rec2 = self._last_record()
        self.assertEqual([n["id"] for n in rec2["agents"]], ["a2"])
        self.assertEqual(rec2["layers"]["worker"]["turns"], 1)
        self._assert_layers_invariant(rec2)

    def test_depth_two_agent_follows_its_root(self):
        self.transcript.write_text(self._agent_call_line("2026-08-13T10:00:00.000Z", "msg_m1", "toolu_A") + "\n")
        subdir = self._subagent_dir()
        self._write_agent(
            subdir, "a1", "cfq:cfq-phase-worker", ["2026-08-13T10:05:00.000Z"], tool_use_id="toolu_A",
        )
        # Its first response lies far outside the main window, and it has no usable toolUseId of
        # its own (the id of a call inside a1's transcript).
        self._write_agent(
            subdir, "a3", "Explore", ["2026-08-13T11:00:00.000Z"],
            spawn_depth=2, parent="a1", tool_use_id="toolu_in_a1",
        )
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        nodes = {n["id"]: n for n in rec["agents"]}
        self.assertEqual(set(nodes), {"a1", "a3"})
        self.assertEqual(nodes["a3"]["layer"], "worker_explore")
        self.assertEqual(rec["layers"]["worker_explore"]["turns"], 1)
        self._assert_layers_invariant(rec)

    def test_agents_without_link_fall_back_to_first_response_in_window(self):
        subdir = self._subagent_dir()
        # meta without toolUseId, and no meta file at all
        self._write_agent(subdir, "m1", "Explore", ["2026-08-13T10:00:30.000Z", "2026-08-13T12:00:00.000Z"])
        (subdir / "agent-nometa.jsonl").write_text(_sub_line("2026-08-13T10:01:30.000Z", "Explore") + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        nodes = {n["id"]: n for n in rec["agents"]}
        self.assertEqual(set(nodes), {"m1", "nometa"})
        self.assertEqual(nodes["m1"]["totals"]["turns"], 2, msg="all responses of an attributed agent count")
        self._assert_layers_invariant(rec)

        # second window: the agents' first responses lie before `since`, a new one inside
        with self.transcript.open("a") as f:
            f.write(EXTRA_TURN)
        self._write_agent(subdir, "m2", "Explore", ["2026-08-13T10:04:30.000Z"])
        self._record(str(self.batch), "phase", "02-foo")
        self.assertEqual([n["id"] for n in self._last_record()["agents"]], ["m2"])

    def test_unknown_tool_use_id_falls_back_to_first_response(self):
        subdir = self._subagent_dir()
        self._write_agent(subdir, "x1", "Explore", ["2026-08-13T10:00:30.000Z"], tool_use_id="toolu_missing")
        self._record(str(self.batch), "phase", "01-foo")
        self.assertEqual([n["id"] for n in self._last_record()["agents"]], ["x1"])

        with self.transcript.open("a") as f:
            f.write(EXTRA_TURN)
        self._write_agent(subdir, "x2", "Explore", ["2026-08-13T10:04:30.000Z"], tool_use_id="toolu_missing")
        self._record(str(self.batch), "phase", "02-foo")
        rec = self._last_record()
        self.assertEqual([n["id"] for n in rec["agents"]], ["x2"])
        self._assert_layers_invariant(rec)

    def test_build_record_upper_bounds_main_turns_and_agent_attribution(self):
        import cfq_telemetry
        subdir = self._subagent_dir()
        self._write_agent(subdir, "u1", "Explore", ["2026-08-13T10:00:30.000Z"])
        self._write_agent(subdir, "u2", "Explore", ["2026-08-13T10:03:30.000Z"])
        orig = cfq_telemetry.subagent_dir
        cfq_telemetry.subagent_dir = lambda: str(subdir)
        try:
            rec = cfq_telemetry.build_record(
                str(self.transcript), "", "phase", "01-foo", "b", "r", [], upper="2026-08-13T10:02:00.000Z",
            )
        finally:
            cfq_telemetry.subagent_dir = orig
        self.assertEqual(rec["totals"]["turns"], 3)
        self.assertEqual(rec["until"], "2026-08-13T10:02:00.000Z")
        self.assertEqual([n["id"] for n in rec["agents"]], ["u1"])

    # -- one count per API response, split by model (schema 3) --------------------------------

    def test_schema_is_3(self):
        self._record(str(self.batch), "phase", "01-foo")
        self.assertEqual(self._last_record()["schema"], 3)

    def test_lines_of_one_response_count_once(self):
        # routine: three lines of one message.id (output 8, 8, 224), same input/cache on each.
        self.transcript.write_text("\n".join([
            _resp_line("2026-08-13T10:00:00.000Z", "msg_a", 8),
            _resp_line("2026-08-13T10:00:01.000Z", "msg_a", 8),
            _resp_line("2026-08-13T10:00:02.000Z", "msg_a", 224),
        ]) + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        t = rec["totals"]
        self.assertEqual(t["turns"], 1)
        self.assertEqual(t["output"], 224)
        self.assertEqual(t["input"], 100)
        self.assertEqual(t["cache_read"], 10)
        self.assertEqual(t["cache_creation"], 5)
        self.assertEqual(rec["from"], "2026-08-13T10:00:00.000Z", msg="from stays the uncollapsed first line")
        self.assertEqual(rec["until"], "2026-08-13T10:00:02.000Z", msg="until stays the uncollapsed last line")
        self.assertEqual(rec["wallclock_s"], 2)
        self.assertEqual(rec["by_model"]["claude-sonnet-5"]["turns"], 1)

    def test_line_without_message_id_is_its_own_response(self):
        self.transcript.write_text("\n".join([
            _resp_line("2026-08-13T10:00:00.000Z", None, 10),
            _resp_line("2026-08-13T10:00:01.000Z", None, 20),
        ]) + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        t = self._last_record()["totals"]
        self.assertEqual(t["turns"], 2)
        self.assertEqual(t["output"], 30)

    def test_tools_counted_across_lines_each_tool_use_id_once(self):
        def tool(tid, name):
            block = {"type": "tool_use", "name": name, "input": {}}
            if tid:
                block["id"] = tid
            return [block]
        self.transcript.write_text("\n".join([
            _resp_line("2026-08-13T10:00:00.000Z", "msg_a", 8, tool("tu_1", "Bash")),
            _resp_line("2026-08-13T10:00:01.000Z", "msg_a", 9, tool("tu_2", "Read")),
            # the same tool_use.id repeated on a second line of the same response
            _resp_line("2026-08-13T10:00:02.000Z", "msg_a", 9, tool("tu_2", "Read")),
            # blocks without an id count once per occurrence
            _resp_line("2026-08-13T10:00:03.000Z", "msg_b", 5, tool(None, "Edit")),
            _resp_line("2026-08-13T10:00:04.000Z", "msg_c", 5, tool(None, "Edit")),
        ]) + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        self.assertEqual(rec["tools"], {"Bash": 1, "Read": 1, "Edit": 2})
        self.assertEqual(rec["totals"]["turns"], 3)

    def test_agent_node_by_model_sums_to_node_totals(self):
        subdir = self._subagent_dir()
        (subdir / "agent-m1.jsonl").write_text("\n".join([
            _resp_line("2026-08-13T10:00:10.000Z", "msg_1", 7, model="claude-sonnet-5", agent="Explore"),
            _resp_line("2026-08-13T10:00:11.000Z", "msg_1", 9, model="claude-sonnet-5", agent="Explore"),
            _resp_line("2026-08-13T10:00:20.000Z", "msg_2", 4, model="claude-haiku-5", agent="Explore"),
        ]) + "\n")
        _write_meta(subdir, "m1", "Explore", spawn_depth=1)
        self._record(str(self.batch), "phase", "01-foo")
        rec = self._last_record()
        node = next(n for n in rec["agents"] if n["id"] == "m1")
        self.assertEqual(set(node["by_model"]), {"claude-sonnet-5", "claude-haiku-5"})
        self.assertEqual(node["totals"]["turns"], 2)
        self.assertEqual(node["by_model"]["claude-sonnet-5"]["output"], 9)
        for field in ("turns", "input", "output", "cache_read", "cache_creation", "billable_in"):
            self.assertEqual(
                sum(v[field] for v in node["by_model"].values()), node["totals"][field], msg=field,
            )
        self.assertEqual(rec["subagent"]["turns"], 2, msg="subagent sum is collapsed too")

    def test_layers_carry_by_model(self):
        rec = self._scenario_orchestrator()
        layers = rec["layers"]
        for name in ("main", "main_explore", "worker", "worker_explore"):
            self.assertIn("by_model", layers[name], msg=name)
        self.assertEqual(layers["main"]["by_model"], rec["by_model"])
        self.assertEqual(set(layers["worker"]["by_model"]), {"claude-sonnet-5"})
        self.assertEqual(set(layers["worker_explore"]["by_model"]), {"claude-haiku-5"})
        self.assertEqual(layers["main_explore"]["by_model"]["claude-sonnet-5"]["turns"], 1)

    def test_layer_without_agents_has_empty_by_model(self):
        rec = self._scenario_classic()
        self.assertEqual(rec["layers"]["worker"]["by_model"], {})
        self.assertEqual(rec["layers"]["worker_explore"]["by_model"], {})

    def test_line_without_usage_still_counts_as_zero_token_turn(self):
        self.transcript.write_text(json.dumps({
            "type": "assistant", "timestamp": "2026-08-13T10:00:00.000Z",
            "message": {"id": "msg_x", "model": "claude-sonnet-5", "content": []},
        }) + "\n")
        self._record(str(self.batch), "phase", "01-foo")
        t = self._last_record()["totals"]
        self.assertEqual(t["turns"], 1)
        self.assertEqual(t["output"], 0)

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
        # turns/output/billable_in are now whole-session sums (schema 1: `totals` + the derived
        # `subagent_explore` layer; neither record carries `subagent_worker`/`subagent`, so the
        # worker/worker_explore layers stay zero) -- rec_a contributes 3+1=4 turns/300+50=350
        # output, rec_b 5+2=7 turns/500+80=580 output, for 11 turns / 930 output combined.
        proc = self.run_cfq("telemetry", "show", str(self.repo), check=True)
        out = json.loads(proc.stdout)
        self.assertEqual(out["turns"], 11, msg=f"turns = {out}")
        self.assertEqual(out["output"], 930, msg=f"output = {out}")
        self.assertEqual(out["billable_in"], 650, msg=f"billable_in = {out}")
        self.assertEqual(out["cache_read"], 30, msg=f"cache_read = {out}")
        self.assertEqual(out["models"], "claude-opus-5,claude-sonnet-5", msg=f"models = {out}")
        self.assertEqual(out["efforts"], "high,medium", msg=f"efforts = {out}")
        self.assertEqual(out["subagent_explore"], {"turns": 3, "output": 130}, msg=f"subagent_explore = {out}")
        self.assertEqual(
            out["layers"],
            {
                "main": {"turns": 8, "output": 800, "billable_in": 650},
                "main_explore": {"turns": 3, "output": 130, "billable_in": 0},
                "worker": {"turns": 0, "output": 0, "billable_in": 0},
                "worker_explore": {"turns": 0, "output": 0, "billable_in": 0},
            },
            msg=f"layers = {out}",
        )

    def test_show_session_filters_to_current_session_only(self):
        # The `(verbatim)` check: same session-id extraction cmd_record already uses, now reused
        # by `show --session` -- this is the one case that distinguishes it from a whole-file read.
        proc = self.run_cfq(
            "telemetry", "show", str(self.repo), "--session",
            env={"CLAUDE_CODE_SESSION_ID": "sess-a"}, check=True,
        )
        out = json.loads(proc.stdout)
        self.assertEqual(out["turns"], 4, msg=f"turns = {out}")
        self.assertEqual(out["output"], 350, msg=f"output = {out}")
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
                "layers": {
                    "main": {"turns": 0, "output": 0, "billable_in": 0},
                    "main_explore": {"turns": 0, "output": 0, "billable_in": 0},
                    "worker": {"turns": 0, "output": 0, "billable_in": 0},
                    "worker_explore": {"turns": 0, "output": 0, "billable_in": 0},
                },
            },
            msg=f"missing telemetry.jsonl should aggregate to all zeros, got {out}",
        )

    def test_show_layers_schema2_used_directly_not_rederived(self):
        # A schema-2 record's own `layers` key is authoritative -- read as-is, never re-derived
        # from `totals`/`subagent*`, even where those older sibling fields disagree (a record
        # never actually carries both meaningfully, but this proves the precedence). Also exercises
        # a populated `worker`/`worker_explore` split, which the schema-1 fixtures above never do.
        rec = {
            "schema": 2, "kind": "phase", "session_id": "sess-c",
            "totals": {"turns": 999, "output": 99999, "billable_in": 99999},
            "layers": {
                "main": {"turns": 3, "output": 300, "billable_in": 100},
                "main_explore": {"turns": 1, "output": 50, "billable_in": 0},
                "worker": {"turns": 6, "output": 700, "billable_in": 200},
                "worker_explore": {"turns": 2, "output": 150, "billable_in": 0},
            },
            "by_model": {"claude-haiku-5": {}}, "by_effort": {"low": {}},
        }
        self.jsonl.write_text(json.dumps(rec) + "\n")
        proc = self.run_cfq("telemetry", "show", str(self.repo), check=True)
        out = json.loads(proc.stdout)
        self.assertEqual(out["turns"], 12, msg=f"turns = {out}")
        self.assertEqual(out["output"], 1200, msg=f"output = {out}")
        self.assertEqual(out["billable_in"], 300, msg=f"billable_in = {out}")
        self.assertEqual(out["subagent_explore"], {"turns": 1, "output": 50}, msg=f"subagent_explore = {out}")
        self.assertEqual(
            out["layers"],
            {
                "main": {"turns": 3, "output": 300, "billable_in": 100},
                "main_explore": {"turns": 1, "output": 50, "billable_in": 0},
                "worker": {"turns": 6, "output": 700, "billable_in": 200},
                "worker_explore": {"turns": 2, "output": 150, "billable_in": 0},
            },
            msg=f"layers = {out}",
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
