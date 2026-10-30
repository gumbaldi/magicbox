"""Codex and Claude share CFQ state without sharing harness instructions."""

import json
import pathlib
import subprocess
import sys
import unittest

from cfq_testlib import CfqTestCase, PLUGIN_ROOT, SCRIPTS_DIR, write_status


class CodexBridgeTest(CfqTestCase):
    def _transcript(self, name="codex-a"):
        path = self.home / ".codex" / "sessions" / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"type": "session_meta", "timestamp": "2026-10-30T10:00:00Z",
             "payload": {"id": name, "cli_version": "1.0"}},
            {"type": "turn_context", "timestamp": "2026-10-30T10:00:01Z",
             "payload": {"model": "gpt-6.1-sol", "effort": "high"}},
            {"type": "token_usage_record", "timestamp": "2026-10-30T10:00:02Z",
             "payload": {"response_id": "response-1", "session_id": name,
                         "usage": {"input_tokens": 120, "cached_input_tokens": 20,
                                   "cache_write_input_tokens": 10, "output_tokens": 40}}},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return path

    def _env(self, transcript, session="codex-a"):
        return {"CFQ_HARNESS": "codex", "CFQ_SESSION_ID": session,
                "CFQ_TRANSCRIPT_PATH": str(transcript), "CFQ_MODEL": "gpt-6.1-sol"}

    def test_codex_runtime_reads_bound_session_and_context(self):
        transcript = self._transcript()
        env = self._env(transcript)
        self.assertEqual(self.run_cfq("runtime", "session-id", env=env).stdout.strip(), "codex-a")
        self.assertEqual(
            self.run_cfq("runtime", "transcript-path", "--exact", env=env).stdout.strip(),
            str(transcript),
        )
        context = self.json_out(self.run_cfq("runtime", "context", env=env))
        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["used"], 120)  # Codex input_tokens already includes cached input.
        self.assertEqual(context["model"], "gpt-6.1-sol")
        self.assertEqual(context["effort"], "high")

    def test_codex_role_defaults_are_distinct_and_harness_only(self):
        env = self._env(self._transcript())
        values = self.json_out(self.run_cfq("settings", "list", env=env))
        self.assertEqual(values["codexPlanModels"], ["gpt-6.1-sol"])
        self.assertEqual(values["codexOrchestratorModels"], ["gpt-6.1-sol"])
        self.assertEqual(values["codexImplModels"], ["gpt-6-luna"])
        for key in ("codexPlanExploreModel", "codexPlanExploreModelComplex",
                    "codexImplExploreModel", "codexImplExploreModelComplex"):
            self.assertEqual(values[key], "gpt-6-luna")
        self.assertEqual(values["codexPlanEffort"], "high")
        self.assertEqual(values["codexOrchestratorEffort"], "medium")
        self.assertEqual(values["codexExplorerEffort"], "high")
        self.assertEqual(values["codexWorkerEffort"], "xhigh")
        claude = self.json_out(self.run_cfq("settings", "list"))
        self.assertNotIn("codexWorkerEffort", claude)

    def test_codex_lock_requires_binding_and_blocks_claude(self):
        repo = self.make_repo("shared-lock")
        transcript = self._transcript()
        unbound = self.run_cfq("lock", "acquire", str(repo), "batch", env={"CFQ_HARNESS": "codex"})
        self.assertNotEqual(unbound.returncode, 0)
        self.assertFalse((repo / ".claude/cfq/.lock").exists())
        bound = self.run_cfq("lock", "acquire", str(repo), "batch", env=self._env(transcript))
        self.assertEqual(bound.returncode, 0, bound.stderr)
        claude = self.run_cfq("lock", "acquire", str(repo), "other",
                              env={"CLAUDE_CODE_SESSION_ID": "claude-b"})
        self.assertNotEqual(claude.returncode, 0)
        self.assertIn("LOCKED", claude.stderr)

    def test_hook_injects_codex_runtime_without_extra_prompt_context(self):
        transcript = self._transcript()
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "session_id": "codex-a", "transcript_path": str(transcript),
                   "model": "gpt-6.1-sol", "cwd": str(self._repos_dir),
                   "tool_input": {"command": f"{PLUGIN_ROOT}/bin/cfq runtime session-id"}}
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "pretooluse"],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(result["permissionDecision"], "allow")
        self.assertIn("CFQ_SESSION_ID=codex-a", result["updatedInput"]["command"])
        self.assertTrue(result["updatedInput"]["command"].startswith("export "))
        self.assertNotIn("additionalContext", result)

    def test_hook_binding_survives_compound_commands(self):
        transcript = self._transcript()
        command = f"true && {PLUGIN_ROOT}/bin/cfq runtime session-id"
        payload = {"tool_name": "Bash", "session_id": "codex-a",
                   "transcript_path": str(transcript), "model": "gpt-6.1-sol",
                   "cwd": str(self._repos_dir), "tool_input": {"command": command}}
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "pretooluse"],
                              input=json.dumps(payload), text=True, capture_output=True)
        rewritten = json.loads(proc.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
        result = subprocess.run(["bash", "-c", rewritten], capture_output=True, text=True,
                                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(self.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "codex-a")

    def test_hook_blocks_direct_status_file_patch(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                   "session_id": "codex-a", "cwd": str(self._repos_dir),
                   "tool_input": {"command": "*** Begin Patch\n*** Update File: "
                                  f"{self._repos_dir}/.claude/cfq/impl/b/status.json\n"
                                  "+changed\n*** End Patch"}}
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "pretooluse"],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(result["permissionDecision"], "deny")

    def test_hook_resolves_patch_parent_segments(self):
        payload = {"tool_name": "apply_patch", "cwd": str(self._repos_dir),
                   "tool_input": {"command": "*** Begin Patch\n*** Update File: "
                                  f"{self._repos_dir}/.claude/cfq/impl/b/tmp/../status.json\n"
                                  "+changed\n*** End Patch"}}
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "pretooluse"],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_blocks_patch_move_into_done(self):
        payload = {"tool_name": "apply_patch", "cwd": str(self._repos_dir),
                   "tool_input": {"command": "*** Begin Patch\n*** Update File: source.md\n"
                                  f"*** Move to: {self._repos_dir}/.claude/cfq/impl/b/done/01-a.md\n"
                                  "*** End Patch"}}
        proc = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "pretooluse"],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_codex_worker_uses_its_own_model_order_and_ignores_claude_hint(self):
        repo = self.make_repo("worker-models")
        batch = repo / ".claude/cfq/impl/001-2026-10-30-shared"
        batch.mkdir(parents=True)
        (batch / "01-work.md").write_text(
            "# Work\n\n## Model\n\nhaiku\n\n## Size\n\nS\n\n"
            "## Changes\n\n1. Do the work.\n\n## Verification\n\n```bash\ntrue\n```\n"
        )
        write_status(batch)
        env = self._env(self._transcript())
        set_models = self.run_cfq("settings", "set", "--repo", str(repo),
                                  "codexImplModels", "gpt-small,gpt-large", env=env)
        self.assertEqual(set_models.returncode, 0, set_models.stderr)
        brief = self.json_out(self.run_cfq("worker", "brief", str(batch), "--phase", "01", env=env))
        self.assertEqual(brief["model"], "gpt-small")
        self.assertEqual(brief["effort"], "xhigh")
        self.assertEqual(brief["escalation"]["next"], "gpt-large")
        file = json.loads((batch / ".worker-brief.json").read_text())
        self.assertEqual(file["modelSource"], "default")
        self.assertEqual(file["blockedPlugins"], [])
        self.assertEqual(file["exploreModels"]["implExploreModel"], "gpt-6-luna")
        self.assertEqual(file["exploreEffort"], "high")
        self.assertNotIn("Model haiku", brief["announcement"])
        self.assertNotIn("## Model", pathlib.Path(file["phaseFile"]).read_text())
        self.assertIn("## Changes", pathlib.Path(file["phaseFile"]).read_text())

    def test_codex_worker_default_does_not_inherit_orchestrator_model(self):
        repo = self.make_repo("worker-default")
        batch = repo / ".claude/cfq/impl/001-2026-10-30-default"
        batch.mkdir(parents=True)
        (batch / "01-work.md").write_text("# Work\n\n## Size\n\nS\n\n## Changes\n\n1. Work.\n")
        write_status(batch)
        brief = self.json_out(self.run_cfq("worker", "brief", str(batch), "--phase", "01",
                                           env=self._env(self._transcript())))
        self.assertEqual(brief["model"], "gpt-6-luna")
        self.assertEqual(brief["effort"], "xhigh")

    def test_codex_plan_preflight_does_not_load_claude_plugin_policy(self):
        repo = self.make_repo("planner")
        env = self._env(self._transcript())
        out = self.json_out(self.run_cfq("preflight-plan", str(repo), env=env))
        self.assertEqual(out["status"], "OK")
        self.assertEqual(out["planningPolicy"]["planModels"], ["gpt-6.1-sol"])
        self.assertEqual(out["planningPolicy"]["currentModel"], "gpt-6.1-sol")
        self.assertEqual(out["planningPolicy"]["planExploreModel"], "gpt-6-luna")
        self.assertEqual(out["planningPolicy"]["exploreEffort"], "high")
        self.assertEqual(out["effort"]["required"], "high")
        self.assertEqual(out["effort"]["current"], "high")
        self.assertNotIn("planBlockedPlugins", out["planningPolicy"])
        self.assertNotIn("useMattpocockGrilling", out["planningPolicy"])
        self.assertNotIn("usePonytailAudit", out["planningPolicy"])

    def test_codex_planning_explorer_usage_is_recorded_then_unbound(self):
        repo = self.make_repo("planning-agent")
        env = self._env(self._transcript())
        self.assertEqual(self.run_cfq("preflight-plan", str(repo), env=env).returncode, 0)
        marker = repo / ".claude/cfq/.codex-planning/codex-a"
        self.assertTrue(marker.is_file())
        agent_transcript = self._transcript("planning-explorer")
        payload = {"session_id": "codex-a", "cwd": str(repo), "agent_id": "planning-explorer",
                   "agent_type": "explorer", "agent_transcript_path": str(agent_transcript),
                   "transcript_path": env["CFQ_TRANSCRIPT_PATH"]}
        hook = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "subagent-stop"],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(hook.returncode, 0, hook.stderr)
        batch = repo / ".claude/cfq/impl/001-2026-10-30-plan"
        batch.mkdir(parents=True)
        result = self.run_cfq("telemetry", "record", str(batch), "planning", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        planning = json.loads((batch / "report.json").read_text())["planning"]
        self.assertEqual(planning["layers"]["main_explore"]["turns"], 1)
        self.assertFalse(marker.exists())

    def test_settings_and_dashboard_expose_only_current_harness_policy(self):
        repo = self.make_repo("settings-isolation")
        env = self._env(self._transcript())
        codex = self.json_out(self.run_cfq("settings", "list", "--repo", str(repo), env=env))
        claude = self.json_out(self.run_cfq("settings", "list", "--repo", str(repo)))
        self.assertIn("codexImplModels", codex)
        self.assertNotIn("implModels", codex)
        self.assertNotIn("usePonytailAudit", codex)
        self.assertNotIn("ctxWindowLimits", codex)
        self.assertIn("implModels", claude)
        self.assertNotIn("codexImplModels", claude)
        codex_menu = self.json_out(self.run_cfq("settings", "menu", "--format", "json", env=env))
        codex_keys = {item["key"] for group in codex_menu["groups"] for item in group["keys"]}
        self.assertTrue(all(group["keys"] for group in codex_menu["groups"]))
        self.assertIn("codexImplModels", codex_keys)
        self.assertNotIn("useMattpocockGrilling", codex_keys)
        dash = self.json_out(self.run_cfq("dash", env=env, cwd=repo))
        self.assertIsNone(dash["plugins"])
        self.assertFalse(any(row["key"] == "implModels" for row in dash["settings"]))

    def test_codex_impl_preflight_projects_only_codex_models(self):
        repo = self.make_repo("impl-policy")
        env = self._env(self._transcript())
        proc = self.run_cfq("preflight-impl", str(repo), env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = self.json_out(proc)
        self.assertIn(out["status"], ("NO_BATCH", "BLOCKED"))
        self.assertEqual(out["policy"]["implModels"], ["gpt-6-luna"])
        self.assertEqual(out["policy"]["currentModel"], "gpt-6.1-sol")
        self.assertEqual(out["policy"]["orchestratorModels"], ["gpt-6.1-sol"])
        self.assertEqual(out["policy"]["implExploreModel"], "gpt-6-luna")
        self.assertEqual(out["policy"]["exploreEffort"], "high")
        self.assertEqual(out["effort"]["required"], "medium")
        self.assertEqual(out["effort"]["current"], "high")
        self.assertFalse(out["effort"]["ok"])
        self.assertNotIn("batchReview", out["policy"])
        self.assertNotIn("implBlockedPlugins", out["policy"])

    def test_claude_and_codex_continue_the_same_phase_queue(self):
        repo = self.make_repo("handoff")
        batch = repo / ".claude/cfq/impl/001-2026-10-30-handoff"
        batch.mkdir(parents=True)
        for slug in ("01-first", "02-second"):
            (batch / f"{slug}.md").write_text(
                f"# {slug}\n\n## Size\n\nS\n\n## Changes\n\n1. Work.\n\n"
                "## Verification\n\n```bash\ntrue\n```\n"
            )
        write_status(batch)
        (batch / "report.json").write_text(json.dumps({"repo": str(repo), "batch": batch.name,
                                                        "phases": []}))
        self.assertEqual(self.run_cfq("registry", "add", str(repo)).returncode, 0)
        codex_env = self._env(self._transcript())
        first = self.json_out(self.run_cfq("preflight-impl", str(repo), env=codex_env))
        self.assertEqual(first["nextPhase"]["slug"], "01-first")
        phase_report = batch / "_phase.json"
        phase_report.write_text(json.dumps({"phase": "01-first", "status": "green",
                                            "summary": "done", "verification": "true -> PASS",
                                            "deviations": [], "errors": [], "commit": ""}))
        recorded = self.run_cfq("phase", "record", str(batch), str(phase_report),
                                "--no-telemetry", env=codex_env)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        second = self.json_out(self.run_cfq("preflight-impl", str(repo)))
        self.assertEqual(second["nextPhase"]["slug"], "02-second")
        self.assertTrue((batch / "done/01-first.md").is_file())

    def test_codex_worker_usage_flows_into_shared_report(self):
        repo = self.make_repo("telemetry")
        batch = repo / ".claude/cfq/impl/001-2026-10-30-telemetry"
        batch.mkdir(parents=True)
        main_transcript = self._transcript()
        agent_transcript = self._transcript("agent-one")
        env = self._env(main_transcript)
        self.assertEqual(self.run_cfq("lock", "acquire", str(repo), batch.name, env=env).returncode, 0)
        (batch / "report.json").write_text(json.dumps({"repo": str(repo), "batch": batch.name,
                                                        "phases": [{"phase": "01-work", "status": "green"}]}))
        initial = self.run_cfq("telemetry", "record", str(batch), "phase", "01-work", env=env)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        payload = {"hook_event_name": "SubagentStop", "session_id": "codex-a",
                   "cwd": str(repo), "agent_id": "agent-one", "agent_type": "worker",
                   "transcript_path": str(main_transcript), "model": "gpt-6.1-sol",
                   "agent_transcript_path": str(agent_transcript),
                   "turn_id": "turn-one"}
        hook = subprocess.run([sys.executable, str(SCRIPTS_DIR / "cfq_codex_hook.py"), "subagent-stop"],
                              input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(hook.returncode, 0, hook.stderr)
        ledger = repo / ".claude/cfq/telemetry.jsonl"
        record = json.loads(ledger.read_text().splitlines()[-1])
        self.assertEqual(record["harness"], "codex")
        self.assertEqual(record["mode"], "orchestrator")
        self.assertEqual(record["totals"]["billable_in"], 100)
        self.assertEqual(record["layers"]["worker"]["turns"], 1)
        self.assertEqual(record["layers"]["worker"]["by_model"]["gpt-6.1-sol"]["turns"], 1)
        report = json.loads((batch / "report.json").read_text())
        self.assertEqual(report["phases"][-1]["telemetry"]["layers"]["worker"]["turns"], 1)


if __name__ == "__main__":
    unittest.main()
