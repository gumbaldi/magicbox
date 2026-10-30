"""The two hosts must discover only their own CFQ instructions."""

import json
import pathlib
import unittest

from cfq_testlib import PLUGIN_ROOT


REPO_ROOT = PLUGIN_ROOT.parents[2]


class CodexPackageTest(unittest.TestCase):
    def test_codex_manifest_selects_only_codex_skills_and_hooks(self):
        manifest = json.loads((PLUGIN_ROOT / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["skills"], "./codex/skills/")
        self.assertEqual(manifest["hooks"], "./codex/hooks/hooks.json")
        self.assertNotEqual(manifest["skills"], "./skills/")
        self.assertTrue((PLUGIN_ROOT / manifest["skills"]).is_dir())
        self.assertTrue((PLUGIN_ROOT / manifest["hooks"]).is_file())

    def test_marketplace_points_to_single_self_contained_package(self):
        marketplace = json.loads((REPO_ROOT / ".agents/plugins/marketplace.json").read_text())
        entry = next(p for p in marketplace["plugins"] if p["name"] == "cfq")
        self.assertEqual(entry["source"]["path"], "./claude/plugins/cfq")
        self.assertTrue((REPO_ROOT / entry["source"]["path"]).is_dir())

    def test_codex_skills_never_load_claude_skill_references(self):
        root = PLUGIN_ROOT / "codex/skills"
        skills = sorted(root.glob("*/SKILL.md"))
        self.assertEqual({p.parent.name for p in skills},
                         {"code-for-queue", "plan-for-queue", "implement-for-queue"})
        for path in skills:
            body = path.read_text()
            self.assertIn("name:", body)
            self.assertIn("description:", body)
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", body)
            self.assertNotIn("../skills/", body)
            self.assertNotIn("references/ifq-", body)
