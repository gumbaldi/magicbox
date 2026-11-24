"""Self-test for scripts/cfq_planning.py (bin/cfq planning open|close)."""

import json
import os
import pathlib
import re
import subprocess
import unittest

from cfq_testlib import CfqTestCase, write_status
from test_telemetry import TRANSCRIPT_TURNS

from cfq_lib import host_paths


class PlanningTestBase(CfqTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_repo("repo")
        self.qdir = self.repo / ".claude" / "cfq"
        self.session = "testsid"
        # Transcript where `telemetry record` looks for the session (mirrors test_telemetry.py).
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.repo))
        tdir = self.home / ".claude" / "projects" / slug
        tdir.mkdir(parents=True)
        (tdir / f"{self.session}.jsonl").write_text(TRANSCRIPT_TURNS)

    def _env(self, **extra):
        env = {"CLAUDE_CODE_SESSION_ID": self.session}
        env.update(extra)
        return env

    def _npm_env(self, findings):
        """A PATH with a fake `npm` whose audit reports `findings` (severity -> fixable)."""
        bindir = self._repos_dir / "fakebin"
        bindir.mkdir(exist_ok=True)
        vulns = {f"pkg{i}": {"severity": sev, "fixAvailable": fix} for i, (sev, fix) in enumerate(findings)}
        stub = bindir / "npm"
        stub.write_text(f"#!/usr/bin/env bash\nif [ \"$1\" = audit ]; then cat <<'EOF'\n"
                        f"{json.dumps({'vulnerabilities': vulns})}\nEOF\nfi\nexit 0\n")
        stub.chmod(0o755)
        (self.repo / "package.json").write_text('{"name":"x","version":"1.0.0"}')
        return {"PATH": f"{bindir}:{os.environ.get('PATH', '')}"}

    def _open(self, slug="demo", env=None):
        return self.run_cfq("planning", "open", str(self.repo), "2026-11-23", slug,
                            cwd=self.repo, env=self._env(**(env or {})))

    def _line(self, out, label):
        return next(e for e in out["statusLines"] if e["label"] == label)

    def _linted_batch(self):
        out = self.json_out(self._open())
        batch_dir = pathlib.Path(out["batchDir"])
        target = self._repos_dir / "target.txt"
        target.touch()
        (batch_dir / "01-a.md").write_text(f"""# Phase A
## Summary
x
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
""")
        (batch_dir / ".batch-context.md").write_text("# Batch Context\n\n## Goal\nTest the bundle.\n")
        write_status(batch_dir)
        return batch_dir

    def _close(self, batch_dir, depth="quick", env=None, extra=()):
        return self.run_cfq("planning", "close", str(batch_dir), "--depth", depth, *extra,
                            cwd=self.repo, env=self._env(**(env or {})))


class TestPlanningOpen(PlanningTestBase):
    def test_routine_with_findings(self):
        proc = self._open(env=self._npm_env([("critical", True), ("high", False), ("low", False)]))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "OK")
        batch_dir = pathlib.Path(out["batchDir"])
        self.assertEqual(batch_dir.name, out["batch"])
        self.assertTrue(batch_dir.is_dir())
        self.assertTrue((batch_dir / ".planning").exists())
        self.assertTrue(out["security"]["available"])
        self.assertEqual(out["securityEntry"], {"needed": True, "exists": False})
        line = self._line(out, "Security")
        self.assertEqual(line["icon"], "warn")
        self.assertIn("critical: 1", line["detail"])
        self.assertIn("low: 1", line["detail"])
        self.assert_status_lines_shape(out["statusLines"])
        report = json.loads((batch_dir / "report.json").read_text())
        self.assertEqual(len(report["security"]), 1, "snapshot written exactly once")
        self.assertEqual(out["errors"], [])

    def test_security_unavailable(self):
        out = self.json_out(self._open())
        self.assertEqual(out["status"], "OK")
        self.assertFalse(out["security"]["available"])
        self.assertEqual(out["securityEntry"]["needed"], False)
        line = self._line(out, "Security")
        self.assertEqual(line["icon"], "warn")
        self.assertEqual(line["detail"], out["security"]["hint"])
        self.assertTrue(pathlib.Path(out["batchDir"]).is_dir())

    def test_clean_scan_is_skipped_line(self):
        out = self.json_out(self._open(env=self._npm_env([])))
        line = self._line(out, "Security")
        if out["security"]["available"]:
            self.assertEqual((line["icon"], line["detail"]), ("skip", "no findings"))

    def test_existing_security_entry(self):
        plan = self.qdir / "plan"
        plan.mkdir(parents=True)
        (plan / "2026-11-01-security-findings.md").write_text("# x\n")
        out = self.json_out(self._open(env=self._npm_env([("high", True)])))
        self.assertEqual(out["securityEntry"], {"needed": True, "exists": True})

    def test_allocate_refusal(self):
        (self.qdir / "impl" / "2026-08-01-still-active").mkdir(parents=True)
        self.run_cfq("changelog", "reserve", str(self.repo), "999", "999-2026-08-01-a")
        (self.qdir / "impl" / "done" / "999-2026-08-01-a").mkdir(parents=True)
        proc = self._open()
        self.assertEqual(proc.returncode, 1)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "BATCH_WIDTH_MIGRATION_BLOCKED")
        self.assertEqual(out["step"], "allocate")
        self.assertIn("nextNumber", out)
        self.assertNotIn("statusLines", out)
        reports = list((self.qdir / "impl").glob("*/report.json"))
        self.assertEqual(reports, [], "no snapshot written after a refused allocation")

    def test_usage_error(self):
        proc = self.run_cfq("planning", "open")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)


class TestPlanningClose(PlanningTestBase):
    def test_routine(self):
        batch_dir = self._linted_batch()
        proc = self._close(batch_dir, env={"CFQ_HTML_REPORT": "false"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["batch"], batch_dir.name)
        self.assertFalse((batch_dir / ".planning").exists())
        self.assertEqual({e["label"] for e in out["statusLines"]}, {"Lint", "Release", "Telemetry", "Portal"})
        self.assertEqual(self._line(out, "Lint")["icon"], "done")
        self.assertEqual(self._line(out, "Release")["icon"], "done")
        self.assertIsInstance(out["cost"], dict, out["errors"])
        self.assertEqual(out["errors"], [])
        self.assert_status_lines_shape(out["statusLines"])
        self.assertIsNone(out["portal"])
        self.assertEqual(self._line(out, "Portal")["icon"], "skip")

    def test_portal_link_when_html_report_on(self):
        batch_dir = self._linted_batch()
        out = self.json_out(self._close(batch_dir))
        self.assertEqual(out["portal"], host_paths.portal_batch_url(str(self.repo), batch_dir.name))
        self.assertEqual(self._line(out, "Portal")["detail"], out["portal"])

    def test_lint_finding_stops_everything(self):
        batch_dir = self._linted_batch()
        (batch_dir / "01-a.md").write_text("# Phase A\n## Size\nM\n")
        proc = self._close(batch_dir)
        self.assertEqual(proc.returncode, 1)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "LINT_FAILED")
        self.assertTrue(out["findings"])
        self.assertTrue(any("01-a" in f for f in out["findings"]), out["findings"])
        self.assertTrue((batch_dir / ".planning").exists())
        report = json.loads((batch_dir / "report.json").read_text()) if (batch_dir / "report.json").exists() else {}
        self.assertNotIn("planning", report, "no telemetry recorded after a lint finding")

    def test_audit_running_refuses(self):
        batch_dir = self._linted_batch()
        (batch_dir / ".audit").write_text("")
        proc = self._close(batch_dir)
        self.assertEqual(proc.returncode, 1)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "NOT_READY")
        self.assertIn("audit", out["detail"])
        self.assertTrue((batch_dir / ".audit").exists())
        self.assertTrue((batch_dir / ".planning").exists())

    def test_telemetry_failure_is_not_fatal(self):
        batch_dir = self._linted_batch()
        for transcript in (self.home / ".claude" / "projects").rglob("*.jsonl"):
            transcript.unlink()
        proc = self._close(batch_dir)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = self.json_out(proc)
        self.assertEqual(out["status"], "OK")
        self.assertTrue(out["errors"])
        self.assertEqual(self._line(out, "Telemetry")["icon"], "warn")
        self.assertFalse((batch_dir / ".planning").exists())

    def test_idempotent(self):
        batch_dir = self._linted_batch()
        self.assertEqual(self._close(batch_dir).returncode, 0)
        proc = self._close(batch_dir)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.json_out(proc)["status"], "OK")

    def _planning_record(self, batch_dir):
        return json.loads((batch_dir / "report.json").read_text())["planning"]

    def test_preflight_is_passed_to_telemetry(self):
        for value in ("injected", "fallback"):
            batch_dir = self._linted_batch()
            proc = self._close(batch_dir, extra=("--preflight", value))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(self._planning_record(batch_dir)["preflight"], value)

    def test_preflight_invalid_value_is_rejected(self):
        batch_dir = self._linted_batch()
        proc = self._close(batch_dir, extra=("--preflight", "maybe"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertTrue((batch_dir / ".planning").exists(), "nothing ran after a usage error")

    def test_preflight_omitted_leaves_record_unchanged(self):
        batch_dir = self._linted_batch()
        self.assertEqual(self._close(batch_dir).returncode, 0)
        self.assertNotIn("preflight", self._planning_record(batch_dir))

    def test_usage_error(self):
        proc = self.run_cfq("planning", "close")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
