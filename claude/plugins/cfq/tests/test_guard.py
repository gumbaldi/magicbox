"""Behavior tests for `bin/cfq guard pretooluse` (scripts/cfq_guard.py).

The PreToolUse guard that makes a raw shell mutation of `.claude/cfq/` impossible -- see
`.claude/cfq/impl/019-2026-09-09-deterministic-queue-mutations/.batch-context.md` for the incident
and the decisions behind it. Drives the script the way Claude Code's harness does: pipe a
PreToolUse JSON payload on stdin, read the JSON (deny) or empty (allow) stdout back.
"""

import json
import subprocess
import unittest

from cfq_testlib import CFQ_BIN, CfqTestCase


class GuardTest(CfqTestCase):
    def _run(self, tool_name, tool_input, cwd):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": cwd,
        }
        return subprocess.run(
            [str(CFQ_BIN), "guard", "pretooluse"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def _bash(self, command, cwd="/repo"):
        return self._run("Bash", {"command": command}, cwd)

    def _write(self, file_path, tool_name="Write"):
        return self._run(tool_name, {"file_path": file_path, "content": "x"}, "/repo")

    def assertDenied(self, proc, *, contains=None):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        decision = out["hookSpecificOutput"]
        self.assertEqual(decision["hookEventName"], "PreToolUse")
        self.assertEqual(decision["permissionDecision"], "deny")
        if contains:
            self.assertIn(contains, decision["permissionDecisionReason"])
        return decision["permissionDecisionReason"]

    def assertAllowed(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "", proc.stdout)

    # -- deny: destructive Bash commands -------------------------------------------------------

    def test_deny_rm_rf_done_absolute_path(self):
        proc = self._bash(
            "rm -rf /repo/.claude/cfq/impl/019-x/done", cwd="/somewhere/else",
        )
        self.assertDenied(proc, contains="trash put")

    def test_deny_rm_rf_done_relative_to_cwd(self):
        proc = self._bash("rm -rf done/", cwd="/repo/.claude/cfq/impl/019-x")
        self.assertDenied(proc, contains="trash put")

    def test_deny_rm_rf_done_after_cd(self):
        proc = self._bash(
            "cd /repo/.claude/cfq/impl/019-x && rm -rf done/", cwd="/repo",
        )
        self.assertDenied(proc, contains="trash put")

    def test_deny_mv_into_done_names_phase_record(self):
        proc = self._bash(
            "mv /repo/.claude/cfq/impl/019-x/03-a.md /repo/.claude/cfq/impl/019-x/done/",
            cwd="/repo",
        )
        self.assertDenied(proc, contains="bin/cfq phase record")

    def test_deny_redirect_into_queue(self):
        proc = self._bash(
            "echo x > /repo/.claude/cfq/impl/019-x/report.json", cwd="/repo",
        )
        self.assertDenied(proc)

    def test_deny_find_delete_in_queue(self):
        proc = self._bash("find /repo/.claude/cfq -name '*.md' -delete", cwd="/repo")
        self.assertDenied(proc)

    # -- deny: destructive commands wrapped in another process -------------------------------

    def test_deny_rm_wrapped_in_bash_c(self):
        proc = self._bash("bash -c 'rm -rf .claude/cfq/impl/x/done'", cwd="/repo")
        self.assertDenied(proc)

    def test_deny_mv_wrapped_in_sh_c(self):
        proc = self._bash('sh -c "mv .claude/cfq/impl/x/01-a.md /tmp"', cwd="/repo")
        self.assertDenied(proc)

    def test_deny_rm_wrapped_in_env_with_assignment(self):
        proc = self._bash("env FOO=1 rm -rf .claude/cfq", cwd="/repo")
        self.assertDenied(proc)

    def test_deny_rm_wrapped_in_xargs(self):
        proc = self._bash("xargs rm -rf .claude/cfq/impl", cwd="/repo")
        self.assertDenied(proc)

    def test_deny_rm_wrapped_in_sudo(self):
        proc = self._bash("sudo rm -r .claude/cfq", cwd="/repo")
        self.assertDenied(proc)

    def test_deny_rm_wrapped_in_nice(self):
        proc = self._bash("nice -n 5 rm .claude/cfq/impl/x/01-a.md", cwd="/repo")
        self.assertDenied(proc)

    def test_deny_rm_wrapped_in_timeout(self):
        proc = self._bash("timeout 5 rm -rf .claude/cfq", cwd="/repo")
        self.assertDenied(proc)

    # -- allow: wrappers around a non-destructive or unrelated command -----------------------

    def test_allow_read_wrapped_in_bash_c(self):
        self.assertAllowed(self._bash("bash -c 'ls .claude/cfq'", cwd="/repo"))

    def test_allow_env_rm_outside_queue(self):
        self.assertAllowed(self._bash("env rm -rf build/", cwd="/repo"))

    def test_allow_echo_of_rm_wrapped_in_bash_c(self):
        self.assertAllowed(self._bash("bash -c 'echo rm .claude/cfq'", cwd="/repo"))

    # -- allow: reads and unrelated destructive commands ---------------------------------------

    def test_allow_rm_rf_outside_queue(self):
        self.assertAllowed(self._bash("rm -rf /repo/node_modules", cwd="/repo"))
        self.assertAllowed(self._bash("rm -rf build/", cwd="/repo"))

    def test_allow_reads_of_the_queue(self):
        self.assertAllowed(
            self._bash("cat /repo/.claude/cfq/impl/019-x/report.json", cwd="/repo")
        )
        self.assertAllowed(self._bash("ls", cwd="/repo"))
        self.assertAllowed(self._bash("grep -r x /repo/.claude/cfq", cwd="/repo"))

    def test_allow_bin_cfq_calls(self):
        self.assertAllowed(
            self._bash(
                "claude/plugins/cfq/bin/cfq phase record /repo/.claude/cfq/impl/019-x report.json",
                cwd="/repo",
            )
        )
        self.assertAllowed(self._bash("claude/plugins/cfq/bin/cfq trash put /repo x", cwd="/repo"))

    # -- Write/Edit into done/ -------------------------------------------------------------------

    def test_deny_write_into_done_batch_subdir(self):
        proc = self._write("/repo/.claude/cfq/impl/019-x/done/06-foo.md")
        self.assertDenied(proc, contains="bin/cfq phase record")

    def test_deny_write_into_done_impl_subdir(self):
        proc = self._write("/repo/.claude/cfq/impl/done/019-x/06-foo.md", tool_name="Edit")
        self.assertDenied(proc, contains="bin/cfq phase record")

    def test_allow_write_open_phase_file_and_markers(self):
        self.assertAllowed(self._write("/repo/.claude/cfq/impl/019-x/06-foo.md"))
        self.assertAllowed(self._write("/repo/.claude/cfq/impl/019-x/.batch-context.md"))
        self.assertAllowed(self._write("/repo/.claude/cfq/plan/2026-09-14-foo.md"))
        self.assertAllowed(self._write("/repo/.claude/cfq/.writeprobe"))

    # -- edge cases -------------------------------------------------------------------------------

    def test_unbalanced_quote_falls_back_to_substring_check(self):
        proc = self._bash("rm -rf '/repo/.claude/cfq/impl/019-x/done", cwd="/repo")
        self.assertDenied(proc)

    def test_unbalanced_quote_without_destructive_verb_is_allowed(self):
        proc = self._bash("echo '/repo/.claude/cfq/impl/019-x", cwd="/repo")
        self.assertAllowed(proc)

    def test_internal_error_fails_open(self):
        proc = subprocess.run(
            [str(CFQ_BIN), "guard", "pretooluse"],
            input="not json at all {{{",
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
