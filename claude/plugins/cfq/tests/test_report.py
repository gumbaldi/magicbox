"""Migrated from test-report.sh.

Self-test for scripts/cfq_report.py: append/set-commit/summary/last-failure/security/skills plus
the derivation helpers the portal shares.
"""

import contextlib
import io
import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone

from cfq_testlib import CfqTestCase, SCRIPTS_DIR, write_status

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_report  # noqa: E402


class TestReport(CfqTestCase):
    def _batch(self, name):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _report_json(self, batch):
        return json.loads((batch / "report.json").read_text())

    def _summary(self, batch):
        return json.loads(self.run_cfq("report", "summary", str(batch), check=True).stdout)

    def _assert_layers_add_up(self, out):
        for key in ("turns", "output", "billable_in"):
            self.assertEqual(sum(layer[key] for layer in out["layers"].values()), out["totals"][key], key)

    def _append_raises(self, dir_, phase_json):
        """Calls append_phase() expecting its errors.die() validation to fire (SystemExit),
        capturing what it printed to stderr the same way a subprocess call's `proc.stderr` used
        to."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
            cfq_report.append_phase(dir_, phase_json, record_telemetry=False)
        self.assertNotEqual(ctx.exception.code, 0)
        return buf.getvalue()

    def test_set_commit_diffstat_stored_only_when_given(self):
        batch = self._batch("2026-01-02-diffstat")
        for slug in ("01-a", "02-b"):
            cfq_report.append_phase(
                str(batch),
                json.dumps({"phase": slug, "status": "green", "summary": "ok", "commit": ""}),
                record_telemetry=False,
            )
        stat = {"files": 1, "insertions": 2, "deletions": 0,
                "paths": [{"path": "a.txt", "added": 2, "deleted": 0}]}

        cfq_report.set_commit(str(batch), "01-a", "abc1234", diffstat=stat)
        cfq_report.set_commit(str(batch), "02-b", "def5678")

        phases = self._report_json(batch)["phases"]
        self.assertEqual(phases[0]["commit"], "abc1234")
        self.assertEqual(phases[0]["diffstat"], stat)
        self.assertEqual(phases[1]["commit"], "def5678")
        self.assertNotIn("diffstat", phases[1])

        self.run_cfq("report", "set-commit", str(batch), "02-b", "9999999")
        self.assertNotIn("diffstat", self._report_json(batch)["phases"][1])

    def test_observations_stored_and_validated(self):
        batch = self._batch("2026-01-03-observations")
        cfq_report.append_phase(
            str(batch),
            json.dumps({"phase": "01-a", "status": "green", "summary": "ok",
                        "observations": ["a", "b"]}),
            record_telemetry=False,
        )
        cfq_report.append_phase(
            str(batch),
            json.dumps({"phase": "02-b", "status": "green", "summary": "ok"}),
            record_telemetry=False,
        )
        phases = self._report_json(batch)["phases"]
        self.assertEqual(phases[0]["observations"], ["a", "b"])
        self.assertNotIn("observations", phases[1])

        before = (batch / "report.json").read_text()
        for bad in ('"text"', '["ok", 3]'):
            stderr = self._append_raises(
                str(batch), '{"phase":"03-c","status":"green","observations":%s}' % bad)
            self.assertIn("observations", stderr)
        self.assertEqual(before, (batch / "report.json").read_text())

    def test_append_and_set_commit(self):
        batch = self._batch("2026-01-01-demo")

        # record_telemetry=False mirrors the old fixture's empty HOME (append's automatic
        # telemetry call finding no transcript, fail-soft, no-op) -- this batch stays a "report
        # without telemetry" fixture on purpose.
        cfq_report.append_phase(
            str(batch),
            '{"phase":"01-a","status":"green","finished":"2026-01-01T10:00:00+01:00","summary":"ok",'
            '"deviations":["Plan sagte X, gebaut Y"],"errors":[],"verification":"tests -> PASS","commit":"abc1234"}',
            record_telemetry=False,
        )
        cfq_report.append_phase(
            str(batch),
            '{"phase":"02-b","status":"red","finished":"2026-01-01T11:00:00+01:00","summary":"fehlgeschlagen",'
            '"deviations":[],"errors":["Verifikation rot: 1 Test <failed>"],"verification":"tests -> FAIL","commit":""}',
            record_telemetry=False,
        )

        self.run_cfq("report", "set-commit", str(batch), "01-a", "def5678")
        c = self._report_json(batch)["phases"][0]["commit"]
        self.assertEqual(c, "def5678", f"set-commit did not update commit = {c}")

        # Unknown phase: set-commit must fail loudly instead of silently returning the file
        # unchanged. Passing the bare number where the report carries the full slug used to exit
        # 0 and leave the commit field null forever -- the whole reason this check exists.
        before = (batch / "report.json").read_text()
        proc = self.run_cfq("report", "set-commit", str(batch), "01", "9999999")
        self.assertNotEqual(proc.returncode, 0, "set-commit with an unknown phase should exit non-zero")
        self.assertTrue(len(proc.stderr) > 0, "set-commit gave no stderr message for an unknown phase")
        after = (batch / "report.json").read_text()
        self.assertEqual(before, after, "set-commit modified report.json despite an unknown phase")

        # A batch whose report.json has an empty phases array hits the same path, not a jq crash.
        emptyph = self._batch("2026-01-04-emptyphases")
        (emptyph / "report.json").write_text(
            '{"repo":"","batch":"2026-01-04-emptyphases","started":"2026-01-04T10:00:00+01:00","phases":[]}\n'
        )
        proc = self.run_cfq("report", "set-commit", str(emptyph), "01-a", "aaa1111")
        self.assertNotEqual(proc.returncode, 0, "set-commit on an empty phases array should exit non-zero")

        # The routine case still works after the change -- same phase, a second overwrite.
        self.run_cfq("report", "set-commit", str(batch), "01-a", "ccc3333")
        c = self._report_json(batch)["phases"][0]["commit"]
        self.assertEqual(c, "ccc3333", f"set-commit no longer updates a known phase = {c}")

        # append validates the phase field before anything is persisted: NN-slug only.
        badph = self._batch("2026-01-05-badphase")

        # bare number -- the batch-009 shape that started this
        stderr = self._append_raises(str(badph), '{"phase":"01","status":"green","summary":"x"}')
        self.assertTrue(len(stderr) > 0, "append gave no stderr message for a bare phase number")
        self.assertFalse((badph / "report.json").exists(), "append created report.json despite rejecting the phase value")

        # missing phase field entirely
        self._append_raises(str(badph), '{"status":"green","summary":"x"}')

        # empty phase field
        self._append_raises(str(badph), '{"phase":"","status":"green","summary":"x"}')

        # routine case still accepted, and it is what creates report.json
        cfq_report.append_phase(str(badph), '{"phase":"03-c","status":"green","summary":"x"}', record_telemetry=False)
        self.assertEqual(
            self._report_json(badph)["phases"][-1]["phase"], "03-c",
            "append no longer accepts a well-formed phase slug",
        )

        out = self._summary(batch)
        self.assertEqual(out["batch"], batch.name)
        self.assertEqual(out["finished"], "2026-01-01T11:00:00+01:00")
        self.assertEqual(out["phases"], {"total": 2, "green": 1, "red": 1, "skipped": 0})
        self.assertEqual(out["totals"], {"turns": 0, "output": 0, "billable_in": 0})
        self.assertEqual(out["deviations"], {"count": 1, "unique": [{"text": "Plan sagte X, gebaut Y", "count": 1}]})

        lf = self.json_out(self.run_cfq("report", "last-failure", str(batch), "02-b"))
        self.assertTrue(lf["found"], f"last-failure should find 02-b's red entry: {lf}")
        self.assertEqual(lf["note"], "fehlgeschlagen", f"last-failure note: {lf}")

        lf = self.json_out(self.run_cfq("report", "last-failure", str(batch), "01-a"))
        self.assertFalse(lf["found"], f"01-a is green, last-failure should be false: {lf}")

        noreport = self._batch("2026-01-03-noreport")
        lf = self.json_out(self.run_cfq("report", "last-failure", str(noreport), "01-a"))
        self.assertFalse(lf["found"], f"last-failure on missing report.json should be false, not crash: {lf}")

        self.run_cfq("report", "security", str(batch), '{"status":"ok","critical":0,"high":0}')
        self.run_cfq("report", "security", str(batch), '{"status":"ok","critical":0,"high":1}')
        sec = len(self._report_json(batch)["security"])
        self.assertEqual(sec, 2, f"security snapshots = {sec}, want 2")

        # security on a fresh batch must create report.json -- this is the planning-time path,
        # where no phase has been appended yet.
        fresh = self._batch("2026-01-02-fresh")
        self.run_cfq("report", "security", str(fresh), '{"available":false,"counts":{}}')
        self.assertTrue((fresh / "report.json").exists(), "security did not create report.json")
        fresh_report = self._report_json(fresh)
        self.assertEqual(len(fresh_report["security"]), 1, f"fresh security snapshots = {len(fresh_report['security'])}, want 1")
        self.assertEqual(fresh_report["batch"], "2026-01-02-fresh", f"batch = {fresh_report['batch']}")

    # ---- batch 051 phase 07: skip entries in the ledger ----------------------------------------

    def _skip_fixture(self, name, ledger, statuses):
        """A batch directory under a throwaway repo: plan files + status.json from `statuses`
        ({slug: status}), the given ledger written first, then phase 03-c skipped through a real
        `phase skip` call (which appends the skip entry)."""
        d = self._repos_dir / "repo-skip" / ".claude" / "cfq" / "impl" / name
        (d / "done").mkdir(parents=True)
        for slug in statuses:
            target = d / "done" if statuses[slug] == "done" else d
            (target / f"{slug}.md").write_text(f"# {slug}\n")
        (d / "03-c.md").write_text("# 03-c\n")
        write_status(d, statuses)
        (d / "report.json").write_text(json.dumps({
            "repo": "", "batch": name, "started": "2026-03-01T08:00:00+00:00", "phases": ledger,
        }))
        self.run_cfq("phase", "skip", str(d), "03", "--reason", "obsolete", check=True)
        return d

    def test_skip_entries_are_ignored_by_outcome_and_counted_separately(self):
        green = {"phase": "01-a", "status": "green", "finished": "2026-03-01T09:00:00+00:00"}
        d = self._skip_fixture("2026-03-01-skipgreen", [green], {"01-a": "done"})
        ledger = self._report_json(d)["phases"]
        self.assertEqual([p["status"] for p in ledger], ["green", "skipped"])
        self.assertEqual(cfq_report.outcome(ledger), "GREEN")
        phases = self._summary(d)["phases"]
        self.assertEqual(phases, {"total": 1, "green": 1, "red": 0, "skipped": 1})  # no skip entry in total

        red = {"phase": "02-b", "status": "red", "finished": "2026-03-01T09:30:00+00:00"}
        d2 = self._skip_fixture(
            "2026-03-02-skipred", [green, red], {"01-a": "done", "02-b": "error"},
        )
        self.assertEqual(cfq_report.outcome(self._report_json(d2)["phases"]), "RED")
        phases2 = self._summary(d2)["phases"]
        self.assertEqual((phases2["total"], phases2["green"], phases2["red"]), (2, 1, 1))

    def test_unskipped_entry_counts_nowhere(self):
        d = self._skip_fixture("2026-03-03-unskip", [], {"01-a": "done"})
        self.run_cfq("phase", "unskip", str(d), "03", check=True)
        ledger = self._report_json(d)["phases"]
        self.assertIn("unskipped", ledger[-1])
        self.assertEqual(self._summary(d)["phases"], {"total": 0, "green": 0, "red": 0, "skipped": 0})
        self.assertEqual(cfq_report.outcome(ledger), "GREEN")

    def test_summary_without_status_file_reports_zero_skipped(self):
        batch = self._batch("2026-03-04-nostatus")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-03-04-nostatus", "started": "2026-03-04T08:00:00+00:00",
            "phases": [{"phase": "01-a", "status": "green", "finished": "2026-03-04T09:00:00+00:00"}],
        }))
        self.assertEqual(self._summary(batch)["phases"]["skipped"], 0)

    # ---- skills (`cfq report skills` lists the used skills from report.json's
    # telemetry.by_skill) ----------------------------------------------------------------------

    def test_skills_used_deduplicated_and_sorted(self):
        batch = self._batch("2026-01-05-skills")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-05-skills", "started": "2026-01-05T10:00:00+01:00",
            "phases": [
                {
                    "phase": "01-a", "status": "green",
                    "telemetry": {
                        "by_skill": {"tdd": 5, "-": 2},
                    },
                },
                {
                    "phase": "02-b", "status": "green",
                    "telemetry": {
                        "by_skill": {"-": 3},
                    },
                },
            ],
        }))
        out = self.json_out(self.run_cfq("report", "skills", str(batch), check=True))
        self.assertEqual(out, {"used": ["tdd"]})

    def test_skills_phase_without_telemetry_is_skipped_not_a_crash(self):
        batch = self._batch("2026-01-06-no-telemetry")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-06-no-telemetry", "started": "2026-01-06T10:00:00+01:00",
            "phases": [{"phase": "01-a", "status": "green"}],
        }))
        out = self.json_out(self.run_cfq("report", "skills", str(batch), check=True))
        self.assertEqual(out, {"used": []})

    def test_skills_empty_phases_array_both_lists_empty(self):
        batch = self._batch("2026-01-07-empty")
        (batch / "report.json").write_text(json.dumps({
            "repo": "", "batch": "2026-01-07-empty", "started": "2026-01-07T10:00:00+01:00",
            "phases": [],
        }))
        out = self.json_out(self.run_cfq("report", "skills", str(batch), check=True))
        self.assertEqual(out, {"used": []})

    # ---- `report summary`: one JSON object, planning kept apart from the batch's own layers ------

    def _write_report(self, name, report):
        batch = self._batch(name)
        report = dict(report, repo="", batch=name, started="2026-01-08T10:00:00+01:00")
        (batch / "report.json").write_text(json.dumps(report))
        return batch

    def test_summary_orchestrator_batch_with_planning_and_all_five_layers(self):
        batch = self._write_report("2026-01-11-five-layers", {
            "planning": {
                "totals": {"turns": 4, "output": 400, "billable_in": 150},
                "by_model": {"opus": {}}, "by_effort": {"high": {}},
            },
            "phases": [{
                "phase": "01-a", "status": "green", "finished": "2026-01-11T11:00:00+01:00",
                "telemetry": {
                    "schema": 3,
                    "layers": {
                        "main": {"turns": 3, "output": 300, "billable_in": 100},
                        "main_explore": {"turns": 1, "output": 50, "billable_in": 10},
                        "worker": {"turns": 6, "output": 700, "billable_in": 200},
                        "worker_explore": {"turns": 2, "output": 150, "billable_in": 20},
                    },
                    "by_model": {"sonnet": {}}, "by_effort": {"medium": {}},
                },
            }],
        })
        out = self._summary(batch)
        self.assertEqual(list(out), ["batch", "finished", "phases", "totals", "layers", "models",
                                     "efforts", "deviations"])
        self.assertEqual(list(out["layers"]),
                         ["planning", "orchestrator", "worker", "explorer", "worker_explorer"])
        self.assertEqual(out["layers"], {
            "planning": {"turns": 4, "output": 400, "billable_in": 150},
            "orchestrator": {"turns": 3, "output": 300, "billable_in": 100},
            "worker": {"turns": 6, "output": 700, "billable_in": 200},
            "explorer": {"turns": 1, "output": 50, "billable_in": 10},
            "worker_explorer": {"turns": 2, "output": 150, "billable_in": 20},
        })
        self.assertEqual(out["totals"], {"turns": 16, "output": 1600, "billable_in": 480})
        self._assert_layers_add_up(out)
        self.assertEqual(out["models"], ["opus", "sonnet"])
        self.assertEqual(out["efforts"], ["high", "medium"])
        self.assertEqual(out["finished"], "2026-01-11T11:00:00+01:00")

    def test_summary_classic_batch_has_no_worker_layers(self):
        batch = self._write_report("2026-01-12-classic", {
            "phases": [{
                "phase": "01-a", "status": "green", "finished": "2026-01-12T11:00:00+01:00",
                "telemetry": {"totals": {"turns": 5, "output": 500, "billable_in": 300}},
            }],
        })
        out = self._summary(batch)
        self.assertEqual(out["layers"]["orchestrator"], {"turns": 5, "output": 500, "billable_in": 300})
        for name in ("worker", "worker_explorer", "explorer", "planning"):
            self.assertEqual(out["layers"][name], {"turns": 0, "output": 0, "billable_in": 0}, name)
        self.assertEqual(out["totals"], out["layers"]["orchestrator"])
        self.assertEqual((out["models"], out["efforts"]), ([], []))

    def test_summary_without_planning_key_has_zero_planning(self):
        batch = self._write_report("2026-01-13-no-planning", {
            "phases": [{"phase": "01-a", "status": "green",
                        "telemetry": {"totals": {"turns": 2, "output": 20, "billable_in": 5}}}],
        })
        out = self._summary(batch)
        self.assertEqual(out["layers"]["planning"], {"turns": 0, "output": 0, "billable_in": 0})
        self._assert_layers_add_up(out)

    def test_summary_planning_explorers_count_as_planning_not_explorer(self):
        batch = self._write_report("2026-01-14-planning-explore", {
            "planning": {"layers": {
                "main": {"turns": 107, "output": 1000, "billable_in": 50},
                "main_explore": {"turns": 9, "output": 90, "billable_in": 5},
                "worker": {}, "worker_explore": {},
            }},
            "phases": [{"phase": "01-a", "status": "green",
                        "telemetry": {"totals": {"turns": 43, "output": 430, "billable_in": 20}}}],
        })
        out = self._summary(batch)
        self.assertEqual(out["layers"]["planning"], {"turns": 116, "output": 1090, "billable_in": 55})
        self.assertEqual(out["layers"]["orchestrator"]["turns"], 43)
        self.assertEqual(out["layers"]["explorer"]["turns"], 0)
        self.assertEqual(out["totals"]["turns"], 159)
        self._assert_layers_add_up(out)

    def test_summary_schema1_phase_without_layers_is_derived(self):
        # No `layers` key: main = totals, worker = subagent_worker (or the legacy collapsed
        # `subagent`), main_explore = subagent_explore, worker_explore = empty.
        batch = self._write_report("2026-01-15-schema1", {
            "phases": [
                {"phase": "01-a", "status": "green", "telemetry": {
                    "totals": {"turns": 10, "output": 1000},
                    "subagent": {"turns": 6, "output": 700}}},
                {"phase": "02-b", "status": "green", "telemetry": {
                    "totals": {"turns": 9, "output": 900, "billable_in": 40},
                    "subagent": {"turns": 88, "output": 8800},
                    "subagent_worker": {"turns": 86, "output": 8600},
                    "subagent_explore": {"turns": 2, "output": 200}}},
            ],
        })
        out = self._summary(batch)
        self.assertEqual(out["layers"]["orchestrator"], {"turns": 19, "output": 1900, "billable_in": 40})
        self.assertEqual(out["layers"]["worker"], {"turns": 92, "output": 9300, "billable_in": 0})
        self.assertEqual(out["layers"]["explorer"], {"turns": 2, "output": 200, "billable_in": 0})
        self.assertEqual(out["layers"]["worker_explorer"], {"turns": 0, "output": 0, "billable_in": 0})
        self.assertEqual(out["totals"]["turns"], 113)
        self._assert_layers_add_up(out)

    def test_summary_schema2_layers_win_over_bogus_totals(self):
        batch = self._write_report("2026-01-16-schema2-layers", {
            "phases": [{"phase": "01-a", "status": "green", "telemetry": {
                "schema": 2,
                "totals": {"turns": 999, "output": 99999, "billable_in": 99999},
                "layers": {"main": {"turns": 3, "output": 300, "billable_in": 100},
                           "main_explore": {}, "worker": {}, "worker_explore": {}},
            }}],
        })
        out = self._summary(batch)
        self.assertEqual(out["totals"], {"turns": 3, "output": 300, "billable_in": 100})

    def test_summary_deviations_are_counted_and_deduplicated(self):
        same = "Plan sagte X, gebaut Y"
        batch = self._write_report("2026-01-17-deviations", {
            "phases": [
                {"phase": "01-a", "status": "green", "deviations": [same, same, "zeta", " alpha "]},
                {"phase": "02-b", "status": "green", "deviations": [same, same, same, "alpha", "zeta"]},
                {"phase": "03-c", "status": "green", "deviations": [same, "beta"]},
            ],
        })
        dev = self._summary(batch)["deviations"]
        self.assertEqual(dev["count"], 11)
        self.assertEqual(dev["unique"], [
            {"text": same, "count": 6}, {"text": "alpha", "count": 2}, {"text": "zeta", "count": 2},
            {"text": "beta", "count": 1},
        ])

    def test_summary_nine_deviations_seven_identical(self):
        same = "identical complaint"
        batch = self._write_report("2026-01-18-seven-same", {
            "phases": [{"phase": f"0{i}-x", "status": "green", "deviations": [same]} for i in range(1, 8)]
                      + [{"phase": "08-y", "status": "green", "deviations": ["b", "a"]}],
        })
        dev = self._summary(batch)["deviations"]
        self.assertEqual(dev["count"], 9)
        self.assertEqual(dev["unique"], [
            {"text": same, "count": 7}, {"text": "a", "count": 1}, {"text": "b", "count": 1},
        ])

    def test_summary_without_deviations(self):
        batch = self._write_report("2026-01-19-no-deviations", {
            "phases": [{"phase": "01-a", "status": "green"}],
        })
        self.assertEqual(self._summary(batch)["deviations"], {"count": 0, "unique": []})

    def test_summary_missing_report_json_exits_1_without_output(self):
        proc = self.run_cfq("report", "summary", str(self._batch("2026-01-20-missing")))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")

    def test_summary_models_and_efforts_are_sorted_json_arrays(self):
        batch = self._write_report("2026-01-21-models", {
            "phases": [
                {"phase": "01-a", "status": "green", "telemetry": {
                    "totals": {"turns": 10, "output": 1000},
                    "by_model": {"sonnet": {}}, "by_effort": {"medium": {}}}},
                {"phase": "02-b", "status": "green", "telemetry": {
                    "totals": {"turns": 1, "output": 10},
                    "by_model": {"haiku": {}, "sonnet": {}}, "by_effort": {"low": {}}}},
            ],
        })
        out = self._summary(batch)
        self.assertEqual(out["models"], ["haiku", "sonnet"])
        self.assertEqual(out["efforts"], ["low", "medium"])

# ---- phase 01: derivation helpers cfq_report.py's summary and the portal funnel through --
# pure functions over a phase dict, no batch directory, no subprocess.

class TestDerivations(unittest.TestCase):
    def setUp(self):
        # parse_ts goes through datetime.astimezone(), which reads the machine's
        # local timezone -- pinned to UTC for the run so the results are portable.
        self._orig_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self._orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._orig_tz
        time.tzset()

    # -- phase_summary --------------------------------------------------------------------

    def test_phase_summary_only_implemented(self):
        self.assertEqual(cfq_report.phase_summary({"implemented": "built X"}), "built X")

    def test_phase_summary_only_summary(self):
        self.assertEqual(cfq_report.phase_summary({"summary": "did Y"}), "did Y")

    def test_phase_summary_both_implemented_wins(self):
        self.assertEqual(
            cfq_report.phase_summary({"implemented": "built X", "summary": "did Y"}), "built X",
        )

    def test_phase_summary_neither_is_empty_string_not_none(self):
        self.assertEqual(cfq_report.phase_summary({}), "")

    # -- phase_finished / batch_finished ---------------------------------------------------

    def test_phase_finished_prefers_finished_field(self):
        self.assertEqual(
            cfq_report.phase_finished({"finished": "2026-01-01T10:00:00+01:00"}),
            "2026-01-01T10:00:00+01:00",
        )

    def test_phase_finished_falls_back_to_telemetry_until(self):
        self.assertEqual(
            cfq_report.phase_finished({"telemetry": {"until": "2026-01-01T11:00:00Z"}}),
            "2026-01-01T11:00:00Z",
        )

    def test_phase_finished_neither_is_empty_string(self):
        self.assertEqual(cfq_report.phase_finished({}), "")

    def test_batch_finished_is_the_maximum_not_the_last_element(self):
        # Written out of time order: 01-a's retry (latest) sits in the middle of the array.
        data = {
            "started": "2026-01-01T00:00:00+01:00",
            "phases": [
                {"phase": "02-b", "finished": "2026-01-01T09:00:00+01:00"},
                {"phase": "01-a", "finished": "2026-01-01T12:00:00+01:00"},
                {"phase": "03-c", "finished": "2026-01-01T10:00:00+01:00"},
            ],
        }
        self.assertEqual(cfq_report.batch_finished(data), "2026-01-01T12:00:00+01:00")

    def test_batch_finished_falls_back_to_started_with_no_timestamps(self):
        data = {
            "started": "2026-01-02T00:00:00+01:00",
            "phases": [{"phase": "01-a"}, {"phase": "02-b"}],
        }
        self.assertEqual(cfq_report.batch_finished(data), "2026-01-02T00:00:00+01:00")

    # -- outcome ----------------------------------------------------------------------------

    def test_outcome_green_red_and_mixed(self):
        green = {"phase": "01-a", "status": "green"}
        red = {"phase": "01-a", "status": "red"}
        other_red = {"phase": "02-b", "status": "red"}
        self.assertEqual(cfq_report.outcome([green]), "GREEN")
        self.assertEqual(cfq_report.outcome([red]), "RED")
        self.assertEqual(cfq_report.outcome([green, other_red]), "RED")
        # a phase that went red and was retried green is MIXED, not RED
        self.assertEqual(cfq_report.outcome([red, green]), "MIXED")

    # -- parse_ts / fmt_duration -----------------------------------------------------------

    def test_parse_ts_z_with_fractional_seconds(self):
        self.assertEqual(
            cfq_report.parse_ts("2026-09-21T13:16:49.329Z"),
            datetime(2026, 9, 21, 13, 16, 49, tzinfo=timezone.utc),
        )

    def test_parse_ts_offset_timestamp(self):
        parsed = cfq_report.parse_ts("2026-01-01T10:30:00+02:00")
        self.assertEqual(parsed, datetime(2026, 1, 1, 8, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(parsed.tzinfo)

    def test_parse_ts_empty_string_returns_none(self):
        self.assertIsNone(cfq_report.parse_ts(""))

    def test_parse_ts_malformed_returns_none_not_an_exception(self):
        self.assertIsNone(cfq_report.parse_ts("not-a-date"))

    def test_fmt_duration_minutes_and_hours(self):
        self.assertEqual(cfq_report.fmt_duration(46), "0:46")
        self.assertEqual(cfq_report.fmt_duration(73), "1:13")
        self.assertEqual(cfq_report.fmt_duration(3723), "1:02:03")

    def test_fmt_duration_zero_and_none_are_dash(self):
        self.assertEqual(cfq_report.fmt_duration(0), "–")
        self.assertEqual(cfq_report.fmt_duration(None), "–")


_ZERO_LAYER = {"turns": 0, "output": 0, "billable_in": 0, "cache_read": 0, "models": []}


def _layer(turns, output, billable_in=0, cache_read=0, models=("model-a",)):
    return {"turns": turns, "output": output, "billable_in": billable_in,
            "cache_read": cache_read, "models": list(models)}


class PhaseCostEntryTest(CfqTestCase):
    """`cfq_report.phase_cost_entry()` -- the `Cost` status line `phase commit` and `worker
    verdict` print when a phase closes."""

    def _dir(self, name="cost-batch"):
        d = self._repos_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _entry(self, layers=None, finished="2026-01-01T10:09:12+00:00", diffstat=True,
               slug="02-x", **tel_extra):
        tel = {"schema": 3, "kind": "phase", "from": "2026-01-01T10:00:00.000Z", "wallclock_s": 35}
        tel["layers"] = layers if layers is not None else {
            "main": _layer(10, 6692, 14561, 985297),
            "main_explore": dict(_ZERO_LAYER),
            "worker": _layer(60, 5615, 158631, 3636035),
            "worker_explore": dict(_ZERO_LAYER),
        }
        tel.update(tel_extra)
        entry = {"phase": slug, "status": "green", "telemetry": tel}
        if finished is not None:
            entry["finished"] = finished
        if diffstat:
            entry["diffstat"] = {"files": 5, "insertions": 212, "deletions": 40}
        return entry

    def _cost(self, *entries, slug="02-x"):
        d = self._dir()
        (d / "report.json").write_text(json.dumps({"batch": "x", "phases": list(entries)}))
        return cfq_report.phase_cost_entry(str(d), slug)

    def test_routine_orchestrator_record(self):
        entry = self._cost(self._entry())
        self.assertEqual(entry["label"], "Cost")
        self.assertEqual(entry["icon"], "done")
        self.assertEqual(entry["detail"], "70 turns · 12k out · 173k in · 4.6M cached · 9:12")
        self.assertEqual(entry["sub"], [
            "session 10 turns · 7k out · worker 60 turns · 6k out",
            "models model-a",
            "diff 5 files · +212 -40",
        ])
        self.assert_status_lines_shape([entry])

    def test_classic_record_has_no_layer_sub_line(self):
        layers = {"main": _layer(8, 3000, 1000, 2000), "main_explore": dict(_ZERO_LAYER),
                  "worker": dict(_ZERO_LAYER), "worker_explore": dict(_ZERO_LAYER)}
        entry = self._cost(self._entry(layers=layers))
        self.assertEqual(entry["sub"], ["models model-a", "diff 5 files · +212 -40"])

    def test_explore_layers_are_ordered(self):
        layers = {"main": _layer(10, 1000), "main_explore": _layer(4, 2000),
                  "worker": _layer(60, 3000), "worker_explore": _layer(3, 4000)}
        entry = self._cost(self._entry(layers=layers))
        self.assertEqual(
            entry["sub"][0],
            "session 10 turns · 1k out · explore 4 turns · 2k out · "
            "worker 60 turns · 3k out · worker explore 3 turns · 4k out",
        )

    def test_models_are_sorted_union(self):
        layers = {"main": _layer(2, 10, models=("model-b", "model-a")),
                  "main_explore": dict(_ZERO_LAYER),
                  "worker": _layer(3, 10, models=("model-b",)), "worker_explore": dict(_ZERO_LAYER)}
        entry = self._cost(self._entry(layers=layers))
        self.assertIn("models model-a · model-b", entry["sub"])

    def test_value_below_1000_is_plain(self):
        layers = {"main": _layer(2, 412, 5, 7), "main_explore": dict(_ZERO_LAYER),
                  "worker": dict(_ZERO_LAYER), "worker_explore": dict(_ZERO_LAYER)}
        entry = self._cost(self._entry(layers=layers))
        self.assertIn("412 out · 5 in · 7 cached", entry["detail"])
        self.assertNotIn("0k", entry["detail"])

    def test_diffstat_singular_and_missing(self):
        e = self._entry()
        e["diffstat"] = {"files": 1, "insertions": 3, "deletions": 0}
        self.assertIn("diff 1 file · +3 -0", self._cost(e)["sub"])
        entry = self._cost(self._entry(diffstat=False))
        self.assertFalse([s for s in entry["sub"] if s.startswith("diff")])

    def test_duration_falls_back_and_is_left_out(self):
        entry = self._cost(self._entry(finished=None))
        self.assertTrue(entry["detail"].endswith("cached · 0:35"), entry["detail"])
        entry = self._cost(self._entry(finished=None, wallclock_s=0))
        self.assertTrue(entry["detail"].endswith("cached"), entry["detail"])
        self.assertFalse(entry["detail"].endswith(" · "))

    def test_record_without_layers_uses_totals_and_by_model(self):
        tel = {"schema": 1, "kind": "phase", "from": "2026-01-01T10:00:00.000Z",
               "totals": {"turns": 5, "output": 2000, "billable_in": 3000, "cache_read": 4000},
               "subagent_worker": {"turns": 7, "output": 1000, "billable_in": 1000, "cache_read": 1000},
               "by_model": {"model-b": {}, "model-a": {}}}
        entry = self._cost({"phase": "02-x", "status": "green", "telemetry": tel,
                            "finished": "2026-01-01T10:01:00+00:00"})
        self.assertEqual(entry["detail"], "12 turns · 3k out · 4k in · 5k cached · 1:00")
        self.assertEqual(entry["sub"][0], "session 5 turns · 2k out · worker 7 turns · 1k out")
        self.assertIn("models model-a · model-b", entry["sub"])

    def test_last_entry_for_the_slug_wins(self):
        first = self._entry()
        first["status"] = "red"
        second = self._entry(layers={"main": _layer(3, 100), "main_explore": dict(_ZERO_LAYER),
                                     "worker": dict(_ZERO_LAYER), "worker_explore": dict(_ZERO_LAYER)})
        self.assertTrue(self._cost(first, second)["detail"].startswith("3 turns"))

    def test_returns_none_without_usable_telemetry(self):
        d = self._dir("none-batch")
        self.assertIsNone(cfq_report.phase_cost_entry(str(d), "02-x"))
        (d / "report.json").write_text("{not json")
        self.assertIsNone(cfq_report.phase_cost_entry(str(d), "02-x"))
        self.assertIsNone(self._cost({"phase": "02-x", "status": "green"}))
        self.assertIsNone(self._cost(self._entry(), slug="09-other"))
        zero = {n: dict(_ZERO_LAYER) for n in cfq_report.LAYER_NAMES}
        self.assertIsNone(self._cost(self._entry(layers=zero)))
        self.assertIsNone(self._cost("not a dict"))

    def test_cost_line_falls_back_to_unavailable(self):
        expected = "unavailable · no usable telemetry for this phase"

        def check(entry):
            self.assertEqual(entry["label"], "Cost")
            self.assertEqual(entry["icon"], "warn")
            self.assertEqual(entry["detail"], expected)

        d = self._dir("line-batch")
        check(cfq_report.phase_cost_line(str(d), "02-x"))
        (d / "report.json").write_text("{not json")
        check(cfq_report.phase_cost_line(str(d), "02-x"))
        d = self._dir()
        (d / "report.json").write_text(json.dumps({"batch": "x", "phases": [{"phase": "02-x", "status": "green"}]}))
        check(cfq_report.phase_cost_line(str(d), "02-x"))
        (d / "report.json").write_text(json.dumps({"batch": "x", "phases": [self._entry()]}))
        check(cfq_report.phase_cost_line(str(d), "09-other"))
        zero = {n: dict(_ZERO_LAYER) for n in cfq_report.LAYER_NAMES}
        (d / "report.json").write_text(json.dumps({"batch": "x", "phases": [self._entry(layers=zero)]}))
        check(cfq_report.phase_cost_line(str(d), "02-x"))
        # the routine record passes through unchanged
        (d / "report.json").write_text(json.dumps({"batch": "x", "phases": [self._entry()]}))
        self.assertEqual(cfq_report.phase_cost_line(str(d), "02-x"), cfq_report.phase_cost_entry(str(d), "02-x"))

    def test_append_phase_stamps_finished(self):
        d = self._dir("stamp-batch")
        cfq_report.append_phase(str(d), json.dumps({"phase": "01-a", "status": "green"}),
                                record_telemetry=False)
        cfq_report.append_phase(
            str(d), json.dumps({"phase": "02-b", "status": "green", "finished": "2026-02-02T01:02:03+00:00"}),
            record_telemetry=False)
        phases = json.loads((d / "report.json").read_text())["phases"]
        self.assertIsNotNone(cfq_report.parse_ts(phases[0]["finished"]))
        self.assertEqual(phases[1]["finished"], "2026-02-02T01:02:03+00:00")


if __name__ == "__main__":
    unittest.main()
