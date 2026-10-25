"""Self-test for scripts/cfq_worker.py (the orchestrator's `worker brief` / `worker verdict`
deterministic spine, batch 020 phase 02).

Synthetic minimal batch fixtures in the style of test_brief_park.py, not a copy of a real batch
tree.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap
import unittest

from cfq_testlib import CFQ_BIN, CfqTestCase, PhaseDirsStatus, write_status

from cfq_brief import parse_phase_body, phase_num, render_phase  # noqa: E402

PHASE_WITH_RECOMMENDED = textwrap.dedent("""\
    # Some phase

    ## Size

    M

    ## Context

    First context line.
    Second context line.

    ## Affected Files

    - `/tmp/example/foo.py`

    ## Changes

    1. First step of the phase.
    2. Second step of the phase.

    ## Recommended skills

    - superpowers half a sentence why (blocked, must be filtered)
    - mattpocock-skills:tdd half a sentence why (kept)

    ## Verification

    ```bash
    echo done
    ```
    """)

PHASE_NO_SIZE = textwrap.dedent("""\
    # Sizeless phase

    ## Affected Files

    - `/tmp/example/only.py`
    """)


class WorkerBriefTest(PhaseDirsStatus, CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo("workerrepo")
        self.batch_dir = self.repo / ".claude/cfq/impl/2026-01-01-workerbatch"
        self.batch_dir.mkdir(parents=True)
        (self.batch_dir / "02-something.md").write_text(PHASE_WITH_RECOMMENDED)
        (self.batch_dir / ".batch-context.md").write_text("# Batch Context\n")

    def _brief(self, phase, home=None):
        return self.run_cfq(
            "worker", "brief", str(self.batch_dir), "--phase", phase,
            home=(home or self.home),
        )

    def _file(self):
        return json.loads((self.batch_dir / ".worker-brief.json").read_text())

    def _brief_file(self, phase="02"):
        out = self.json_out(self._brief(phase))
        self.assertEqual(out["status"], "OK", f"unexpected status: {out}")
        return self._file()

    def test_routine_brief_carries_every_field(self):
        out = self.json_out(self._brief("02", home=self.home))
        self.assertEqual(out["status"], "OK", f"unexpected status: {out}")
        body = dict(self._file(), announcement=out["announcement"])
        self.assertEqual(body["status"], "OK", f"unexpected status: {body}")
        self.assertEqual(body["batch"], "2026-01-01-workerbatch")
        self.assertTrue(body["batchDir"].startswith("/"), f"batchDir not absolute: {body}")
        self.assertEqual(body["phase"], "02-something")
        self.assertTrue(body["phaseFile"].endswith("02-something.md"))
        self.assertTrue(body["phaseFile"].startswith("/"), f"phaseFile not absolute: {body}")
        self.assertEqual(body["size"], "M")
        self.assertTrue(body["batchContext"].endswith(".batch-context.md"))
        self.assertIn("branch", body)
        self.assertIn("language", body)
        self.assertIn("codeLanguage", body["language"])
        self.assertIn("blockedPlugins", body)
        self.assertIn("exploreModels", body)
        self.assertIn("failedAttempt", body)
        self.assertEqual(body["failedAttempt"], {"found": False})
        self.assertIn("priorDeviations", body)
        self.assertEqual(body["priorDeviations"], [])
        self.assertIn("commands", body)
        self.assertIn("phaseCommit", body["commands"])
        self.assertIn("phaseRecordRed", body["commands"])
        self.assertIn("announcement", body)
        self.assertTrue(body["announcement"].startswith("PHASE 02 · "), f"announcement: {body['announcement']!r}")
        self.assertFalse(
            any(l.endswith(" ") for l in body["announcement"].splitlines()),
            f"announcement must carry no trailing whitespace: {body['announcement']!r}",
        )

    def test_stdout_names_the_briefing_file_and_a_one_line_prompt(self):
        out = self.json_out(self._brief("02"))
        brief_file = out["briefFile"]
        self.assertTrue(brief_file.startswith("/"), out)
        self.assertEqual(brief_file, str(self.batch_dir.resolve() / ".worker-brief.json"))
        self.assertTrue(pathlib.Path(brief_file).is_file(), out)
        self.assertNotIn("\n", out["prompt"])
        self.assertIn(brief_file, out["prompt"])
        self.assertEqual(
            out["prompt"], f"Read your briefing at {brief_file} first, then implement that phase."
        )
        self.assertTrue(out["announcement"].startswith("PHASE 02 · "), out)
        self.assertEqual(
            {"status", "batch", "batchDir", "phase", "briefFile", "prompt", "announcement",
             "model", "escalation"},
            set(out),
        )

    def test_stdout_does_not_leak_the_briefing(self):
        out = self.json_out(self._brief("02"))
        for key in ("priorDeviations", "commands", "handover", "phaseFile", "language"):
            self.assertNotIn(key, out)

    def test_stdout_size_is_constant_in_the_number_of_deviations(self):
        empty = self._brief("02").stdout
        (self.batch_dir / "report.json").write_text(json.dumps({"batch": "x", "phases": [{
            "phase": "01-prior", "status": "green", "summary": "s",
            "deviations": [f"deviation number {i} with some text" for i in range(20)],
            "finished": "2026-01-01T10:00:00+00:00",
        }]}))
        full = self._brief("02").stdout
        self.assertEqual(len(full), len(empty))
        self.assertEqual(len(self._file()["priorDeviations"]), 20)

    def test_second_call_replaces_the_file(self):
        (self.batch_dir / "03-other.md").write_text(PHASE_NO_SIZE)
        self.assertEqual(self._brief_file("02")["phase"], "02-something")
        self.assertEqual(self._brief_file("03")["phase"], "03-other")

    def test_file_has_no_announcement(self):
        out = self.json_out(self._brief("02"))
        self.assertNotIn("announcement", self._file())
        self.assertIn("announcement", out)

    def test_no_batch_writes_no_file_and_leaves_an_existing_one(self):
        self._brief("99")
        self.assertFalse((self.batch_dir / ".worker-brief.json").exists())
        self._brief("02")
        before = (self.batch_dir / ".worker-brief.json").read_text()
        self._brief("99")
        self.assertEqual((self.batch_dir / ".worker-brief.json").read_text(), before)
        gone = self.repo / ".claude/cfq/impl/no-such-batch"
        self.run_cfq("worker", "brief", str(gone), "--phase", "01", home=self.home)
        self.assertFalse((gone / ".worker-brief.json").exists())

    @unittest.skipIf(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "read-only directories do not stop root or Windows")
    def test_unwritable_batch_directory_fails_without_output(self):
        self._prepare_status()
        os.chmod(self.batch_dir, 0o555)
        try:
            proc = self._brief("02")
        finally:
            os.chmod(self.batch_dir, 0o755)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        self.assertTrue(proc.stderr.strip())
        self.assertNotIn("Traceback", proc.stderr)

    def test_announcement_matches_cfq_brief_render_phase(self):
        body = self.json_out(self._brief("02"))
        phase_file = self.batch_dir / "02-something.md"
        expected = render_phase(
            phase_num(phase_file), parse_phase_body(phase_file.read_text(), fallback_title=phase_file.stem)
        )
        self.assertEqual(body["announcement"], expected)
        self.assertIn("  Steps    1. First step of the phase.\n           2. Second step of the phase.", body["announcement"])

    def test_note_plan_framework_command_inserts_flag_after_note_plan(self):
        body = self._brief_file()
        note_plan = body["commands"]["notePlan"]
        note_plan_framework = body["commands"]["notePlanFramework"]
        self.assertEqual(
            note_plan_framework,
            note_plan.replace("note plan ", "note plan --framework ", 1),
            msg=f"notePlanFramework must be notePlan with --framework inserted after 'note plan': "
            f"{body['commands']}",
        )
        self.assertNotIn(
            "--framework", note_plan, msg="notePlan itself must stay unchanged"
        )

    def test_no_batch_context_is_null_not_an_error(self):
        (self.batch_dir / ".batch-context.md").unlink()
        body = self._brief_file()
        self.assertEqual(body["status"], "OK")
        self.assertIsNone(body["batchContext"])

    def test_missing_size_heading_degrades_to_m(self):
        (self.batch_dir / "03-nosize.md").write_text(PHASE_NO_SIZE)
        body = self._brief_file("03")
        self.assertEqual(body["status"], "OK")
        self.assertEqual(body["size"], "M")

    def test_blocked_plugin_filtered_from_recommended_skills(self):
        body = self._brief_file()
        self.assertNotIn("superpowers", body["recommendedSkills"], f"blocked plugin leaked: {body}")
        self.assertIn("mattpocock-skills:tdd", body["recommendedSkills"], f"kept entry missing: {body}")

    def test_brief_finds_a_phase_lying_in_skipped(self):
        write_status(self.batch_dir, **{"02_something": {"status": "skipped", "reason": "obsolete"}})
        self.assertTrue((self.batch_dir / "skipped" / "02-something.md").is_file())
        body = self.json_out(self._brief("02"))
        self.assertEqual(body["status"], "OK", f"unexpected status: {body}")
        self.assertEqual(body["phase"], "02-something")
        self.assertTrue(self._file()["phaseFile"].endswith("skipped/02-something.md"))

    def test_unknown_phase_number_is_no_batch(self):
        proc = self._brief("99")
        body = self.json_out(proc)
        self.assertEqual(body["status"], "NO_BATCH", f"unexpected status: {body}")
        self.assertNotIn("announcement", body, f"NO_BATCH must not carry an announcement: {body}")

    def test_missing_batch_directory_is_no_batch(self):
        proc = self.run_cfq(
            "worker", "brief", str(self.repo / ".claude/cfq/impl/no-such-batch"), "--phase", "01",
            home=self.home,
        )
        body = self.json_out(proc)
        self.assertEqual(body["status"], "NO_BATCH", f"unexpected status: {body}")
        self.assertNotIn("announcement", body, f"NO_BATCH must not carry an announcement: {body}")


class WorkerModelTest(PhaseDirsStatus, CfqTestCase):
    """Model resolution, escalation target, override and handover of `worker brief`, and the
    `escalate` verdict (batch 053 phase 10)."""

    def setUp(self):
        super().setUp()
        self.repo = self.make_repo("modelrepo")
        self.batch_dir = self.repo / ".claude/cfq/impl/2026-01-01-modelbatch"
        self.batch_dir.mkdir(parents=True)
        (self.batch_dir / ".batch-context.md").write_text("# Batch Context\n")

    def _phase(self, model=None):
        text = PHASE_WITH_RECOMMENDED
        if model:
            text = text.replace("## Context", f"## Model\n\n{model}\n\n## Context", 1)
        (self.batch_dir / "02-something.md").write_text(text)

    def _settings(self, **values):
        d = self.repo / ".claude/cfq"
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").write_text(json.dumps(values))

    def _failed(self):
        (self.batch_dir / "report.json").write_text(json.dumps({"batch": "x", "phases": [{
            "phase": "02-something", "status": "red", "summary": "boom",
            "finished": "2026-01-01T10:00:00+00:00",
        }]}))

    def _brief(self, *extra):
        return self.run_cfq("worker", "brief", str(self.batch_dir), "--phase", "02", *extra)

    def _read(self, proc):
        """Standard output of a brief call, checked, merged over the file's object."""
        out = self.json_out(proc)
        self.assertEqual(out["status"], "OK", out)
        return dict(json.loads((self.batch_dir / ".worker-brief.json").read_text()), **out)

    def _resolved(self, phase_model, settings, failed=False):
        self._phase(phase_model)
        self._settings(**settings)
        if failed:
            self._failed()
        return self._read(self._brief())

    def test_model_resolution_table(self):
        both = {"implModels": ["sonnet", "haiku"]}
        rows = [
            (None, {"implModels": ["sonnet"]}, False, "sonnet", "default"),
            ("haiku", both, False, "haiku", "phase"),
            ("haiku", {"implModels": ["sonnet"]}, False, "sonnet", "default-not-allowed"),
            ("haiku", both, True, "sonnet", "default-after-failure"),
            ("haiku", dict(both, orchestratorModels=["opus"]), False, "haiku", "phase"),
            (None, dict(both, orchestratorModels=["opus"]), False, "opus", "default"),
        ]
        for phase_model, settings, failed, model, source in rows:
            with self.subTest(phase_model=phase_model, settings=settings, failed=failed):
                body = self._resolved(phase_model, settings, failed)
                self.assertEqual(body["status"], "OK", body)
                self.assertEqual((body["model"], body["modelSource"]), (model, source), body)
                self.assertIsNone(body["handover"])
            # a clean slate for the next row
            for f in (self.batch_dir / "report.json",):
                if f.exists():
                    f.unlink()

    def test_escalation_next(self):
        rows = [
            ("haiku", {"implModels": ["sonnet", "haiku"]}, "sonnet"),
            ("sonnet", {"implModels": ["sonnet", "haiku"]}, None),
            ("haiku", {"implModels": ["haiku", "opus"]}, "opus"),
            ("haiku", {"implModels": ["haiku", "mystery"]}, None),
        ]
        for phase_model, settings, expected in rows:
            with self.subTest(phase_model=phase_model, settings=settings):
                body = self._resolved(phase_model, settings)
                self.assertEqual(body["model"], phase_model, body)
                self.assertEqual(body["escalation"], {"next": expected}, body)

    def test_default_model_counts_as_escalation_target(self):
        body = self._resolved("haiku", {"implModels": ["haiku"], "orchestratorModels": ["sonnet"]})
        self.assertEqual((body["model"], body["escalation"]["next"]), ("haiku", "sonnet"), body)
        body = self._resolved(None, {"implModels": ["sonnet", "haiku"], "orchestratorModels": ["opus"]})
        self.assertEqual((body["model"], body["escalation"]["next"]), ("opus", None), body)

    def test_override_with_handover(self):
        self._phase("haiku")
        self._settings(implModels=["sonnet", "haiku"])
        handover = {"done": "nothing", "remaining": "everything", "filesTouched": ["/tmp/x.py"]}
        hf = self._repos_dir / "handover.json"
        hf.write_text(json.dumps(handover))
        body = self._read(self._brief("--model-override", "sonnet", "--handover-file", str(hf)))
        self.assertEqual(body["status"], "OK", body)
        self.assertEqual((body["model"], body["modelSource"]), ("sonnet", "escalated"), body)
        self.assertEqual(body["handover"], handover)

    def test_override_must_be_allowed(self):
        self._phase("haiku")
        self._settings(implModels=["sonnet", "haiku"])
        proc = self._brief("--model-override", "opus")
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(json.loads(proc.stderr)["status"], "MODEL_OVERRIDE_NOT_ALLOWED")

    def test_missing_or_unparsable_handover_fails_with_a_code(self):
        self._phase("haiku")
        self._settings(implModels=["sonnet", "haiku"])
        proc = self._brief("--model-override", "sonnet", "--handover-file", str(self._repos_dir / "nope.json"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(json.loads(proc.stderr)["status"], "HANDOVER_UNREADABLE")
        bad = self._repos_dir / "bad.json"
        bad.write_text("{not json")
        proc = self._brief("--model-override", "sonnet", "--handover-file", str(bad))
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(json.loads(proc.stderr)["status"], "HANDOVER_UNREADABLE")


class WorkerVerdictTest(CfqTestCase):
    def _verdict(self, report_obj, batch_dir="/tmp/does-not-need-to-exist"):
        run_env = self._base_env()
        run_env["HOME"] = str(self.home)
        return subprocess.run(
            [str(CFQ_BIN), "worker", "verdict", batch_dir],
            input=json.dumps(report_obj), capture_output=True, text=True, env=run_env,
        )

    def test_green_with_no_triggers_continues(self):
        proc = self._verdict({"phase": "02-x", "status": "green", "deviations": []})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = json.loads(proc.stdout)
        self.assertEqual(body["verdict"], "CONTINUE")
        self.assertEqual(body["triggers"], [])

    def test_red_stops_regardless_of_other_content(self):
        proc = self._verdict({
            "phase": "02-x", "status": "red", "errors": ["boom"],
            "triggers": ["omitted"],
        })
        body = json.loads(proc.stdout)
        self.assertEqual(body["verdict"], "STOP")
        self.assertEqual(body["triggers"], ["red"])

    def test_green_with_omitted_trigger_asks(self):
        proc = self._verdict({
            "phase": "02-x", "status": "green",
            "deviations": ["Left out the retry-backoff change the plan specified."],
            "triggers": ["omitted"],
        })
        body = json.loads(proc.stdout)
        self.assertEqual(body["verdict"], "ASK")
        self.assertEqual(body["triggers"], ["omitted"])

    def test_green_with_new_dependency_asks(self):
        proc = self._verdict({
            "phase": "02-x", "status": "green",
            "deviations": ["Added the 'requests' dependency, not named in the plan."],
            "triggers": ["dependency"],
        })
        body = json.loads(proc.stdout)
        self.assertEqual(body["verdict"], "ASK")
        self.assertEqual(body["triggers"], ["dependency"])

    def test_question_status_asks_and_relays_question_verbatim(self):
        proc = self._verdict({
            "phase": "02-x", "status": "question",
            "question": "Two defensible approaches -- which one?",
        })
        body = json.loads(proc.stdout)
        self.assertEqual(body["verdict"], "ASK")
        self.assertEqual(body["triggers"], [])
        self.assertEqual(body["question"], "Two defensible approaches -- which one?")

    def test_escalate_carries_the_handover(self):
        handover = {"done": "nothing", "remaining": "a design decision", "filesTouched": []}
        proc = self._verdict({"phase": "02-x", "status": "escalate", "handover": handover})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = json.loads(proc.stdout)
        self.assertEqual(body["status"], "OK")
        self.assertEqual(body["verdict"], "ESCALATE")
        self.assertEqual(body["triggers"], [])
        self.assertIsNone(body["question"])
        self.assertEqual(body["handover"], handover)

    def test_escalate_without_handover_is_malformed(self):
        for report in ({"phase": "02-x", "status": "escalate"},
                       {"phase": "02-x", "status": "escalate", "handover": "text"}):
            proc = self._verdict(report)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(json.loads(proc.stderr)["status"], "MALFORMED_REPORT")

    def _batch_with_telemetry(self):
        d = self._repos_dir / "verdict-batch"
        d.mkdir(parents=True, exist_ok=True)
        layer = {"turns": 4, "output": 2000, "billable_in": 3000, "cache_read": 4000, "models": ["model-a"]}
        zero = {"turns": 0, "output": 0, "billable_in": 0, "cache_read": 0, "models": []}
        (d / "report.json").write_text(json.dumps({"batch": "x", "phases": [{
            "phase": "02-x", "status": "green", "finished": "2026-01-01T10:09:12+00:00",
            "telemetry": {"schema": 3, "kind": "phase", "from": "2026-01-01T10:00:00.000Z",
                          "layers": {"main": layer, "main_explore": zero, "worker": zero,
                                     "worker_explore": zero}},
        }]}))
        return str(d)

    def test_green_and_red_carry_the_cost_line(self):
        d = self._batch_with_telemetry()
        for report, verdict in (
            ({"phase": "02-x", "status": "green"}, "CONTINUE"),
            ({"phase": "02-x", "status": "red", "errors": ["boom"]}, "STOP"),
            ({"phase": "02-x", "status": "green", "triggers": ["omitted"]}, "ASK"),
        ):
            body = json.loads(self._verdict(report, batch_dir=d).stdout)
            self.assertEqual(body["verdict"], verdict)
            self.assert_status_lines_shape(body["statusLines"])
            self.assertEqual([e["label"] for e in body["statusLines"]], ["Cost"])

    def test_question_and_missing_batch_have_no_status_lines(self):
        d = self._batch_with_telemetry()
        body = json.loads(self._verdict({"phase": "02-x", "status": "question", "question": "?"}, batch_dir=d).stdout)
        self.assertEqual(body["statusLines"], [])
        proc = self._verdict({"phase": "02-x", "status": "green"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = json.loads(proc.stdout)
        self.assertEqual(body["statusLines"], [])
        self.assertEqual(body["verdict"], "CONTINUE")

    def test_malformed_json_fails_loudly_never_silent_continue(self):
        run_env = self._base_env()
        run_env["HOME"] = str(self.home)
        proc = subprocess.run(
            [str(CFQ_BIN), "worker", "verdict", "/tmp/does-not-need-to-exist"],
            input="{not json", capture_output=True, text=True, env=run_env,
        )
        self.assertNotEqual(proc.returncode, 0, "malformed JSON must not exit 0")
        self.assertEqual(proc.stdout.strip(), "", msg="expected no stdout on failure")
        err = json.loads(proc.stderr)
        self.assertIn("status", err)
        self.assertNotEqual(err["status"], "OK")


if __name__ == "__main__":
    unittest.main()
