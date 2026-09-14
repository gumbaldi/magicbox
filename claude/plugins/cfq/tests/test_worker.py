"""Self-test for scripts/cfq_worker.py (the orchestrator's `worker brief` / `worker verdict`
deterministic spine, batch 020 phase 02).

Synthetic minimal batch fixtures in the style of test_brief_park.py, not a copy of a real batch
tree.
"""

import json
import subprocess
import textwrap
import unittest

from cfq_testlib import CFQ_BIN, CfqTestCase

PHASE_WITH_RECOMMENDED = textwrap.dedent("""\
    # Some phase

    ## Size

    M

    ## Context

    First context line.
    Second context line.

    ## Affected Files

    - `/tmp/example/foo.py`

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


class WorkerBriefTest(CfqTestCase):
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

    def test_routine_brief_carries_every_field(self):
        proc = self._brief("02", home=self.home)
        body = self.json_out(proc)
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
        self.assertIn("phaseRecord", body["commands"])

    def test_no_batch_context_is_null_not_an_error(self):
        (self.batch_dir / ".batch-context.md").unlink()
        body = self.json_out(self._brief("02"))
        self.assertEqual(body["status"], "OK")
        self.assertIsNone(body["batchContext"])

    def test_missing_size_heading_degrades_to_m(self):
        (self.batch_dir / "03-nosize.md").write_text(PHASE_NO_SIZE)
        body = self.json_out(self._brief("03"))
        self.assertEqual(body["status"], "OK")
        self.assertEqual(body["size"], "M")

    def test_blocked_plugin_filtered_from_recommended_skills(self):
        body = self.json_out(self._brief("02"))
        self.assertNotIn("superpowers", body["recommendedSkills"], f"blocked plugin leaked: {body}")
        self.assertIn("mattpocock-skills:tdd", body["recommendedSkills"], f"kept entry missing: {body}")

    def test_unknown_phase_number_is_no_batch(self):
        proc = self._brief("99")
        body = self.json_out(proc)
        self.assertEqual(body["status"], "NO_BATCH", f"unexpected status: {body}")

    def test_missing_batch_directory_is_no_batch(self):
        proc = self.run_cfq(
            "worker", "brief", str(self.repo / ".claude/cfq/impl/no-such-batch"), "--phase", "01",
            home=self.home,
        )
        body = self.json_out(proc)
        self.assertEqual(body["status"], "NO_BATCH", f"unexpected status: {body}")


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
