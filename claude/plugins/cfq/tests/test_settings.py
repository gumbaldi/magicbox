"""Migrated from test-settings.sh.

Covers cfq-settings.sh's three-tier resolution (defaults, global file, repo file, CFQ_* env
override) -- the logic batch 014 ports to Python first, so this suite is the safety net that port
is verified against.
"""

import contextlib
import json
import os
import pathlib
import tempfile
import unittest

from cfq_testlib import CFQ_BIN, CfqTestCase


class SettingsTest(CfqTestCase):
    @contextlib.contextmanager
    def _home_as(self, home):
        # run_clean always uses self.home; swap it for calls against a different HOME.
        old = self.home
        self.home = pathlib.Path(home)
        try:
            yield
        finally:
            self.home = old

    # 1. Fresh install: list has telemetrySyncRepo, not planPreferredPlugins
    def test_01_fresh_install_list(self):
        out = self.json_out(self.run_cfq("settings", "list", home=self.home))
        self.assertTrue(
            "telemetrySyncRepo" in out, msg="fresh install missing telemetrySyncRepo"
        )
        self.assertFalse(
            "planPreferredPlugins" in out, msg="fresh install still has planPreferredPlugins"
        )

    # 2. Legacy settings.json: has planPreferredPlugins, lacks telemetrySyncRepo
    def test_02_legacy_settings_json(self):
        with tempfile.TemporaryDirectory() as legacy_home:
            legacy_dir = f"{legacy_home}/.claude/code-for-queue"

            pathlib.Path(legacy_dir).mkdir(parents=True, exist_ok=True)
            pathlib.Path(f"{legacy_dir}/settings.json").write_text(
                '{"stopUsed":42,"planPreferredPlugins":["x"]}'
            )

            with self._home_as(legacy_home):
                got = self.run_clean(
                    str(CFQ_BIN), "settings", "get", "telemetrySyncRepo"
                ).stdout.strip()
            self.assertEqual(got, "", msg=f"legacy telemetrySyncRepo = '{got}', want empty")

            got = self.run_cfq(
                "settings", "get", "stopUsed", home=legacy_home
            ).stdout.strip()
            self.assertEqual(
                got, "42", msg=f"legacy stopUsed = '{got}', want 42 (normal key, file value honored)"
            )

            legacy_list = self.json_out(self.run_cfq("settings", "list", home=legacy_home))
            self.assertFalse(
                "planPreferredPlugins" in legacy_list,
                msg="legacy list still shows planPreferredPlugins",
            )

    # 3. set telemetrySyncRepo: absolute writes, empty disables, relative fails
    def test_03_set_telemetry_sync_repo(self):
        self.run_cfq("settings", "set", "telemetrySyncRepo", "/tmp/x", home=self.home, check=True)
        got = self.run_cfq(
            "settings", "get", "telemetrySyncRepo", home=self.home
        ).stdout.strip()
        self.assertEqual(got, "/tmp/x", msg=f"set absolute path -> got '{got}'")

        self.run_cfq("settings", "set", "telemetrySyncRepo", "", home=self.home, check=True)
        got = self.run_cfq(
            "settings", "get", "telemetrySyncRepo", home=self.home
        ).stdout.strip()
        self.assertEqual(got, "", msg=f"set empty -> got '{got}'")

        proc = self.run_cfq("settings", "set", "telemetrySyncRepo", "relativ", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set relative path should fail")

    # 4. Env override beats file
    def test_04_env_override_beats_file(self):
        got = self.run_cfq(
            "settings",
            "get",
            "telemetrySyncRepo",
            home=self.home,
            env={"CFQ_TELEMETRY_SYNC_REPO": "/tmp/y"},
        ).stdout.strip()
        self.assertEqual(got, "/tmp/y", msg=f"env override -> got '{got}'")

    # 5. Unrelated assertions still hold
    def test_05_unrelated_assertions_still_hold(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "stopUsed"
        ).stdout.strip()
        self.assertEqual(got, "100000", msg=f"default stopUsed = '{got}', want 100000")

        proc = self.run_cfq("settings", "set", "grillMode", "klassisch", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set grillMode klassisch should fail")

    # 5b. stopUsed: default, set/round-trip, special values -1 and 0, malformed env falls back, list
    def test_05b_stop_used_lifecycle(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "stopUsed"
        ).stdout.strip()
        self.assertEqual(got, "100000", msg=f"default stopUsed = '{got}', want 100000")

        with tempfile.TemporaryDirectory() as fresh_home, self._home_as(fresh_home):
            got = self.run_clean(
                str(CFQ_BIN), "settings", "get", "stopUsed"
            ).stdout.strip()
            self.assertEqual(
                got, "100000", msg=f"default stopUsed on fresh HOME = '{got}', want 100000"
            )

        self.run_cfq("settings", "set", "stopUsed", "50000", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopUsed", home=self.home).stdout.strip()
        self.assertEqual(got, "50000", msg=f"set stopUsed 50000 -> got '{got}'")

        # routine case
        self.run_cfq("settings", "set", "stopUsed", "250000", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopUsed", home=self.home).stdout.strip()
        self.assertEqual(got, "250000", msg=f"set stopUsed 250000 -> got '{got}'")

        # edge case: 0 (always stop after a phase) is valid, not rejected
        self.run_cfq("settings", "set", "stopUsed", "0", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopUsed", home=self.home).stdout.strip()
        self.assertEqual(got, "0", msg=f"set stopUsed 0 -> got '{got}'")

        # edge case: -1 (never stop) is valid, not rejected
        self.run_cfq("settings", "set", "stopUsed", "-1", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopUsed", home=self.home).stdout.strip()
        self.assertEqual(got, "-1", msg=f"set stopUsed -1 -> got '{got}'")

        # failure case: below -1 is rejected
        proc = self.run_cfq("settings", "set", "stopUsed", "-2", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set stopUsed -2 should fail")

        self.run_cfq("settings", "set", "stopUsed", "100000", home=self.home, check=True)

        got = self.run_cfq(
            "settings", "get", "stopUsed", home=self.home, env={"CFQ_STOP_USED": "75000"}
        ).stdout.strip()
        self.assertEqual(got, "75000", msg=f"env override stopUsed -> got '{got}'")

        got = self.run_cfq(
            "settings", "get", "stopUsed", home=self.home, env={"CFQ_STOP_USED": "abc"}
        ).stdout.strip()
        self.assertEqual(
            got, "100000", msg=f"malformed CFQ_STOP_USED -> got '{got}', want 100000"
        )

        out = self.json_out(self.run_cfq("settings", "list", home=self.home))
        self.assertEqual(
            out["stopUsed"], 100000, msg=f"list stopUsed on fresh install = '{out['stopUsed']}', want 100000"
        )

        # phaseContextGrowth is gone
        got = self.run_cfq("settings", "get", "phaseContextGrowth", home=self.home).stdout.strip()
        self.assertEqual(got, "null", msg=f"phaseContextGrowth still present, got '{got}'")

    # 5d. CFQ_SCAN_ROOTS is comma-delimited now (uniform array env delimiter)
    def test_05d_scan_roots_comma_delimited(self):
        got = self.run_cfq(
            "settings", "get", "scanRoots", home=self.home, env={"CFQ_SCAN_ROOTS": "a,b"}
        ).stdout.strip()
        self.assertEqual(got, "a,b", msg=f"CFQ_SCAN_ROOTS comma round-trip -> got '{got}'")

    # 5e. gitStatePolicy: default, set, invalid
    def test_05e_git_state_policy(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "gitStatePolicy"
        ).stdout.strip()
        self.assertEqual(got, "local", msg=f"default gitStatePolicy = '{got}', want local")

        self.run_cfq("settings", "set", "gitStatePolicy", "trackable", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "gitStatePolicy", home=self.home).stdout.strip()
        self.assertEqual(got, "trackable", msg=f"set gitStatePolicy trackable -> got '{got}'")

        proc = self.run_cfq("settings", "set", "gitStatePolicy", "bogus", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set gitStatePolicy bogus should fail")

    # 5f. Regression guard: every pre-existing key's default is unchanged by the schema rewrite.
    def test_05f_regression_defaults_unchanged(self):
        want = {
            "grillMode": "stepwise",
            "planModels": "opus,fable",
            "implModels": "sonnet",
            "planExploreModel": "haiku",
            "implExploreModel": "haiku",
            "allowAnyModel": "false",
            "scanRoots": "~/git",
            "useMattpocockGrilling": "true",
            "usePonytailAudit": "true",
            "codeLanguage": "en",
            "docLanguages": "",
            "docLevel": "minimal",
            "maintenanceEvery": "50",
            "branchPerBatch": "true",
            "changelogFile": ".claude/cfq/changelog.yml",
            "htmlReport": "false",
            "planBlockedPlugins": "superpowers",
            "implBlockedPlugins": "superpowers",
            "telemetrySyncRepo": "",
        }
        with tempfile.TemporaryDirectory() as reg_home, self._home_as(reg_home):
            for key, expected in want.items():
                got = self.run_clean(
                    str(CFQ_BIN), "settings", "get", key
                ).stdout.strip()
                self.assertEqual(
                    got, expected, msg=f"regression default {key} = '{got}', want '{expected}'"
                )

    # 6. maintenanceEvery: default, set 0, invalid, env override
    def test_06_maintenance_every(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "maintenanceEvery"
        ).stdout.strip()
        self.assertEqual(got, "50", msg=f"default maintenanceEvery = '{got}', want 50")

        self.run_cfq("settings", "set", "maintenanceEvery", "0", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "maintenanceEvery", home=self.home).stdout.strip()
        self.assertEqual(got, "0", msg=f"set maintenanceEvery 0 -> got '{got}'")

        proc = self.run_cfq("settings", "set", "maintenanceEvery", "abc", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set maintenanceEvery abc should fail")

        got = self.run_cfq(
            "settings", "get", "maintenanceEvery", home=self.home, env={"CFQ_MAINTENANCE_EVERY": "10"}
        ).stdout.strip()
        self.assertEqual(got, "10", msg=f"env override maintenanceEvery -> got '{got}'")

    # 7. codeLanguage, docLanguages, docLevel: defaults, set, invalid, env override, gone key
    def test_07_code_language_doc_languages_doc_level(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "codeLanguage"
        ).stdout.strip()
        self.assertEqual(got, "en", msg=f"default codeLanguage = '{got}', want en")

        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "docLanguages"
        ).stdout.strip()
        self.assertEqual(got, "", msg=f"default docLanguages = '{got}', want empty")

        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "docLevel"
        ).stdout.strip()
        self.assertEqual(got, "minimal", msg=f"default docLevel = '{got}', want minimal")

        # edge: a CFQ_* var exported by the caller must not leak into an isolated default read
        os.environ["CFQ_DOC_LEVEL"] = "standard"
        try:
            got = self.run_cfq("settings", "get", "docLevel", home=self.home).stdout.strip()
        finally:
            del os.environ["CFQ_DOC_LEVEL"]
        self.assertEqual(
            got, "minimal", msg=f"default docLevel under leaked CFQ_DOC_LEVEL = '{got}', want minimal"
        )

        self.run_cfq("settings", "set", "docLevel", "standard", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "docLevel", home=self.home).stdout.strip()
        self.assertEqual(got, "standard", msg=f"set docLevel standard -> got '{got}'")

        proc = self.run_cfq("settings", "set", "docLevel", "bogus", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set docLevel bogus should fail")

        self.run_cfq("settings", "set", "codeLanguage", "de", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "codeLanguage", home=self.home).stdout.strip()
        self.assertEqual(got, "de", msg=f"set codeLanguage de -> got '{got}'")

        proc = self.run_cfq("settings", "set", "codeLanguage", "de DE", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set codeLanguage 'de DE' should fail")

        self.run_cfq("settings", "set", "docLanguages", "de,fr", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "docLanguages", home=self.home).stdout.strip()
        self.assertEqual(got, "de,fr", msg=f"set docLanguages de,fr -> got '{got}'")

        got = self.run_cfq(
            "settings", "get", "codeLanguage", home=self.home, env={"CFQ_CODE_LANGUAGE": "pt-BR"}
        ).stdout.strip()
        self.assertEqual(got, "pt-BR", msg=f"env override codeLanguage -> got '{got}'")

        got = self.run_cfq(
            "settings", "get", "docLanguages", home=self.home, env={"CFQ_DOC_LANGUAGES": "es"}
        ).stdout.strip()
        self.assertEqual(got, "es", msg=f"env override docLanguages -> got '{got}'")

        got = self.run_cfq(
            "settings", "get", "docLevel", home=self.home, env={"CFQ_DOC_LEVEL": "full"}
        ).stdout.strip()
        self.assertEqual(got, "full", msg=f"env override docLevel -> got '{got}'")

        got = self.run_cfq("settings", "get", "ponytailAuditEvery", home=self.home).stdout.strip()
        self.assertEqual(got, "null", msg=f"ponytailAuditEvery still present, got '{got}'")

    # 8. branchPerBatch, changelogFile, htmlReport: defaults, boolean validation, arbitrary string
    def test_08_branch_per_batch_changelog_file_html_report(self):
        out = self.json_out(
            self.run_clean(str(CFQ_BIN), "settings", "list")
        )
        self.assertEqual(
            out["branchPerBatch"], True, msg=f"default branchPerBatch = {out['branchPerBatch']}, want true"
        )
        self.assertEqual(
            out["changelogFile"],
            ".claude/cfq/changelog.yml",
            msg=f"default changelogFile = {out['changelogFile']}, want .claude/cfq/changelog.yml",
        )
        self.assertEqual(
            out["htmlReport"], False, msg=f"default htmlReport = {out['htmlReport']}, want false"
        )

        proc = self.run_cfq("settings", "set", "branchPerBatch", "nope", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set branchPerBatch nope should fail")
        proc = self.run_cfq("settings", "set", "htmlReport", "nope", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set htmlReport nope should fail")

        self.run_cfq("settings", "set", "branchPerBatch", "false", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "branchPerBatch", home=self.home).stdout.strip()
        self.assertEqual(got, "false", msg=f"set branchPerBatch false -> got '{got}'")

        self.run_cfq("settings", "set", "htmlReport", "true", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "htmlReport", home=self.home).stdout.strip()
        self.assertEqual(got, "true", msg=f"set htmlReport true -> got '{got}'")

        self.run_cfq(
            "settings", "set", "changelogFile", "my.changelog.yml", home=self.home, check=True
        )
        got = self.run_cfq("settings", "get", "changelogFile", home=self.home).stdout.strip()
        self.assertEqual(got, "my.changelog.yml", msg=f"set changelogFile -> got '{got}'")

        self.run_cfq("settings", "set", "changelogFile", "", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "changelogFile", home=self.home).stdout.strip()
        self.assertEqual(got, "", msg=f"set changelogFile empty -> got '{got}'")

    # 9. planExploreModel: default, set, env override
    def test_09_plan_explore_model(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "planExploreModel"
        ).stdout.strip()
        self.assertEqual(got, "haiku", msg=f"default planExploreModel = '{got}', want haiku")

        self.run_cfq("settings", "set", "planExploreModel", "opus", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "planExploreModel", home=self.home).stdout.strip()
        self.assertEqual(got, "opus", msg=f"set planExploreModel opus -> got '{got}'")

        got = self.run_cfq(
            "settings",
            "get",
            "planExploreModel",
            home=self.home,
            env={"CFQ_PLAN_EXPLORE_MODEL": "haiku-fast"},
        ).stdout.strip()
        self.assertEqual(got, "haiku-fast", msg=f"env override planExploreModel -> got '{got}'")

    # 9b. implExploreModel: default, set, env override
    def test_09b_impl_explore_model(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "implExploreModel"
        ).stdout.strip()
        self.assertEqual(got, "haiku", msg=f"default implExploreModel = '{got}', want haiku")

        self.run_cfq("settings", "set", "implExploreModel", "opus", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "implExploreModel", home=self.home).stdout.strip()
        self.assertEqual(got, "opus", msg=f"set implExploreModel opus -> got '{got}'")

        got = self.run_cfq(
            "settings",
            "get",
            "implExploreModel",
            home=self.home,
            env={"CFQ_IMPL_EXPLORE_MODEL": "haiku-fast"},
        ).stdout.strip()
        self.assertEqual(got, "haiku-fast", msg=f"env override implExploreModel -> got '{got}'")

    # 9b (regression). An unrelated global `get` (e.g. cfq-runtime.sh's internal `get
    # ctxWindowLimits` call inside cfq-dash.sh) must not make every other untouched key report
    # source "global" afterwards -- ensure() only ever materializes an empty {}, never a full copy
    # of the defaults.
    def test_09c_unrelated_global_get_does_not_pollute_source(self):
        with tempfile.TemporaryDirectory() as marker_home, self._home_as(marker_home):
            self.run_clean(
                str(CFQ_BIN), "settings", "get", "ctxWindowLimits", check=True
            )
            got = self.run_clean(
                str(CFQ_BIN),
                "settings",
                "get",
                "--source",
                "maintenanceEvery",
            ).stdout.strip()
            self.assertEqual(
                got,
                '{"value":50,"source":"default"}',
                msg=f"untouched key after unrelated get -> got '{got}', want source default",
            )

    # 10. Repo-scoped settings: precedence chain, scope rejection, unset fall-through, legacy
    # detection, migrate. Fresh HOME and a throwaway fixture repo -- never the real repo.
    def test_10_repo_scoped_settings_precedence_and_migrate(self):
        with tempfile.TemporaryDirectory() as repo_home, tempfile.TemporaryDirectory() as fixture_s:
            fixture = pathlib.Path(fixture_s)

            with self._home_as(repo_home):
                got = self.run_clean(
                    str(CFQ_BIN),
                    "settings",
                    "get",
                    "--repo",
                    str(fixture),
                    "--source",
                    "maintenanceEvery",
                ).stdout.strip()
            self.assertEqual(
                got, '{"value":50,"source":"default"}', msg=f"precedence step 1 (default) -> got '{got}'"
            )

            self.run_cfq(
                "settings", "set", "maintenanceEvery", "20", home=repo_home, check=True
            )
            got = self.run_cfq(
                "settings", "get", "--repo", str(fixture), "--source", "maintenanceEvery", home=repo_home
            ).stdout.strip()
            self.assertEqual(
                got, '{"value":20,"source":"global"}', msg=f"precedence step 2 (global) -> got '{got}'"
            )

            self.run_cfq(
                "settings",
                "set",
                "--repo",
                str(fixture),
                "maintenanceEvery",
                "5",
                home=repo_home,
                check=True,
            )
            got = self.run_cfq(
                "settings", "get", "--repo", str(fixture), "--source", "maintenanceEvery", home=repo_home
            ).stdout.strip()
            self.assertEqual(
                got, '{"value":5,"source":"repo"}', msg=f"precedence step 3 (repo) -> got '{got}'"
            )

            got = self.run_cfq(
                "settings",
                "get",
                "--repo",
                str(fixture),
                "--source",
                "maintenanceEvery",
                home=repo_home,
                env={"CFQ_MAINTENANCE_EVERY": "99"},
            ).stdout.strip()
            self.assertEqual(
                got,
                '{"value":99,"source":"env:process"}',
                msg=f"precedence step 4 (env) -> got '{got}'",
            )

            # scanRoots is global-only; --repo set must fail
            proc = self.run_cfq(
                "settings", "set", "--repo", str(fixture), "scanRoots", "/tmp", home=repo_home
            )
            self.assertNotEqual(
                proc.returncode, 0, msg="set scanRoots --repo should fail (global-only scope)"
            )

            # unset --repo falls through to the global value
            self.run_cfq(
                "settings", "unset", "--repo", str(fixture), "maintenanceEvery", home=repo_home, check=True
            )
            got = self.run_cfq(
                "settings", "get", "--repo", str(fixture), "--source", "maintenanceEvery", home=repo_home
            ).stdout.strip()
            self.assertEqual(
                got, '{"value":20,"source":"global"}', msg=f"unset --repo fall-through -> got '{got}'"
            )

            # Legacy detection: a repo's own .claude/settings.json "env" block is
            # read-only/informational
            (fixture / ".claude").mkdir(parents=True, exist_ok=True)
            (fixture / ".claude" / "settings.json").write_text(
                '{"env":{"CFQ_DOC_LEVEL":"standard"}}'
            )
            out = self.json_out(
                self.run_cfq(
                    "settings",
                    "list",
                    "--repo",
                    str(fixture),
                    "--sources",
                    home=repo_home,
                    env={"CFQ_DOC_LEVEL": "standard"},
                )
            )
            got_source = out["docLevel"]
            self.assertEqual(
                got_source,
                {"value": "standard", "source": "env:repo-legacy"},
                msg=f"legacy detection -> got '{got_source}'",
            )

            # migrate writes the equivalent key into <fixture>/.claude/cfq/settings.json via
            # `set --repo` and never touches the original .claude/settings.json
            legacy_before = (fixture / ".claude" / "settings.json").read_text()
            self.run_cfq("settings", "migrate", str(fixture), home=repo_home, check=True)
            got = json.loads(
                (fixture / ".claude" / "cfq" / "settings.json").read_text()
            )["docLevel"]
            self.assertEqual(got, "standard", msg=f"migrate docLevel -> got '{got}'")
            legacy_after = (fixture / ".claude" / "settings.json").read_text()
            self.assertEqual(
                legacy_before,
                legacy_after,
                msg="migrate modified the original .claude/settings.json",
            )

    # 11. describe: well-formed JSON with type/default/scope/env/description, single key and all keys
    def test_11_describe(self):
        out = self.json_out(
            self.run_cfq("settings", "describe", "stopPct", home=self.home)
        )
        for field in ("type", "default", "scope", "env", "description"):
            self.assertIn(field, out, msg=f"describe stopPct missing field '{field}'")

        out = self.json_out(self.run_cfq("settings", "describe", home=self.home))
        for key, entry in out.items():
            for field in ("type", "default", "scope", "env", "description"):
                self.assertIn(
                    field, entry, msg=f"describe (all keys) missing field '{field}' for '{key}'"
                )

    # 12. state store: separate schema-less key/value file, distinct from settings.json
    def test_12_state_store(self):
        with tempfile.TemporaryDirectory() as state_home:
            got = self.run_cfq(
                "settings", "state", "get", "anything", home=state_home
            ).stdout.strip()
            self.assertEqual(got, "null", msg=f"state get on missing key -> got '{got}', want null")

            self.run_cfq(
                "settings", "state", "set", "setupDone", "true", home=state_home, check=True
            )
            got = self.run_cfq(
                "settings", "state", "get", "setupDone", home=state_home
            ).stdout.strip()
            self.assertEqual(got, "true", msg=f"state set/get setupDone round-trip -> got '{got}'")

            # touch settings.json too, then confirm both files exist independently
            self.run_cfq(
                "settings", "set", "maintenanceEvery", "10", home=state_home, check=True
            )

            self.assertTrue(
                pathlib.Path(f"{state_home}/.claude/code-for-queue/settings.json").is_file(),
                msg="settings.json missing after set",
            )
            self.assertTrue(
                pathlib.Path(f"{state_home}/.claude/code-for-queue/state.json").is_file(),
                msg="state.json missing after state set",
            )

            # setupDone is fully gone from the settings schema -- get falls through to its
            # existing unknown-key convention (bare "null"), same as any other key absent from
            # $schema
            got = self.run_cfq(
                "settings", "get", "setupDone", home=state_home
            ).stdout.strip()
            self.assertEqual(
                got, "null", msg=f"get setupDone (removed key) -> got '{got}', want null"
            )

            proc = self.run_cfq("settings", "set", "setupDone", "true", home=state_home)
            self.assertNotEqual(
                proc.returncode, 0, msg="set setupDone should fail (removed from schema)"
            )

            out = self.json_out(self.run_cfq("settings", "list", home=state_home))
            self.assertFalse("setupDone" in out, msg="list still shows setupDone")

    # 13. securityTimeoutSeconds / securityFindingsCap: documented defaults
    def test_13_security_timeout_and_findings_cap(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "securityTimeoutSeconds"
        ).stdout.strip()
        self.assertEqual(got, "30", msg=f"default securityTimeoutSeconds = '{got}', want 30")

        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "securityFindingsCap"
        ).stdout.strip()
        self.assertEqual(got, "20", msg=f"default securityFindingsCap = '{got}', want 20")

    # 14. onePhasePerSession: default, list, set/unset round-trip, invalid value, env override
    def test_14_one_phase_per_session(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "onePhasePerSession"
        ).stdout.strip()
        self.assertEqual(got, "true", msg=f"default onePhasePerSession = '{got}', want true")

        out = self.json_out(
            self.run_clean(str(CFQ_BIN), "settings", "list")
        )
        self.assertEqual(
            out["onePhasePerSession"], True, msg=f"list onePhasePerSession = '{out['onePhasePerSession']}', want true"
        )

        proc = self.run_cfq("settings", "set", "onePhasePerSession", "nope", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set onePhasePerSession nope should fail")

        self.run_cfq(
            "settings", "set", "onePhasePerSession", "false", home=self.home, check=True
        )
        got = self.run_cfq(
            "settings", "get", "onePhasePerSession", home=self.home
        ).stdout.strip()
        self.assertEqual(got, "false", msg=f"set onePhasePerSession false -> got '{got}'")

        self.run_cfq("settings", "unset", "onePhasePerSession", home=self.home, check=True)
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "onePhasePerSession"
        ).stdout.strip()
        self.assertEqual(
            got, "true", msg=f"unset onePhasePerSession -> got '{got}', want default true"
        )

        got = self.run_cfq(
            "settings",
            "get",
            "onePhasePerSession",
            home=self.home,
            env={"CFQ_ONE_PHASE_PER_SESSION": "false"},
        ).stdout.strip()
        self.assertEqual(got, "false", msg=f"env override onePhasePerSession -> got '{got}'")

    # 15. i18nExcludePatterns: default, list, set/unset round-trip
    def test_15_i18n_exclude_patterns(self):
        default_i18n = "*/locales/*,*/locale/*,*/i18n/*,*/lang/*,*/translations/*"
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "i18nExcludePatterns"
        ).stdout.strip()
        self.assertEqual(
            got, default_i18n, msg=f"default i18nExcludePatterns = '{got}', want '{default_i18n}'"
        )

        out = self.json_out(
            self.run_clean(str(CFQ_BIN), "settings", "list")
        )
        got = ",".join(out["i18nExcludePatterns"])
        self.assertEqual(
            got, default_i18n, msg=f"list i18nExcludePatterns = '{got}', want '{default_i18n}'"
        )

        self.run_cfq(
            "settings",
            "set",
            "i18nExcludePatterns",
            "*/vendor/*,*/gen/*",
            home=self.home,
            check=True,
        )
        got = self.run_cfq(
            "settings", "get", "i18nExcludePatterns", home=self.home
        ).stdout.strip()
        self.assertEqual(
            got, "*/vendor/*,*/gen/*", msg=f"set i18nExcludePatterns -> got '{got}'"
        )

        self.run_cfq("settings", "unset", "i18nExcludePatterns", home=self.home, check=True)
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "i18nExcludePatterns"
        ).stdout.strip()
        self.assertEqual(
            got, default_i18n, msg=f"unset i18nExcludePatterns -> got '{got}', want default"
        )

    # 16. stopFiveHourPct / stopSevenDayPct: defaults, set/round-trip, -1 (disabled) is valid,
    # below -1 rejected, env override, malformed env falls back to default, list
    def test_16_stop_five_hour_and_seven_day_pct(self):
        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "stopFiveHourPct"
        ).stdout.strip()
        self.assertEqual(got, "70", msg=f"default stopFiveHourPct = '{got}', want 70")

        got = self.run_clean(
            str(CFQ_BIN), "settings", "get", "stopSevenDayPct"
        ).stdout.strip()
        self.assertEqual(got, "95", msg=f"default stopSevenDayPct = '{got}', want 95")

        self.run_cfq("settings", "set", "stopFiveHourPct", "60", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopFiveHourPct", home=self.home).stdout.strip()
        self.assertEqual(got, "60", msg=f"set stopFiveHourPct 60 -> got '{got}'")

        self.run_cfq("settings", "set", "stopFiveHourPct", "-1", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopFiveHourPct", home=self.home).stdout.strip()
        self.assertEqual(got, "-1", msg=f"set stopFiveHourPct -1 -> got '{got}'")

        proc = self.run_cfq("settings", "set", "stopFiveHourPct", "-2", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set stopFiveHourPct -2 should fail")
        self.run_cfq("settings", "set", "stopFiveHourPct", "70", home=self.home, check=True)

        self.run_cfq("settings", "set", "stopSevenDayPct", "-1", home=self.home, check=True)
        got = self.run_cfq("settings", "get", "stopSevenDayPct", home=self.home).stdout.strip()
        self.assertEqual(got, "-1", msg=f"set stopSevenDayPct -1 -> got '{got}'")

        proc = self.run_cfq("settings", "set", "stopSevenDayPct", "-2", home=self.home)
        self.assertNotEqual(proc.returncode, 0, msg="set stopSevenDayPct -2 should fail")
        self.run_cfq("settings", "set", "stopSevenDayPct", "95", home=self.home, check=True)

        got = self.run_cfq(
            "settings", "get", "stopFiveHourPct", home=self.home, env={"CFQ_STOP_FIVE_HOUR_PCT": "50"}
        ).stdout.strip()
        self.assertEqual(got, "50", msg=f"env override stopFiveHourPct -> got '{got}'")

        got = self.run_cfq(
            "settings",
            "get",
            "stopFiveHourPct",
            home=self.home,
            env={"CFQ_STOP_FIVE_HOUR_PCT": "abc"},
        ).stdout.strip()
        self.assertEqual(
            got, "70", msg=f"malformed CFQ_STOP_FIVE_HOUR_PCT -> got '{got}', want 70"
        )

        got = self.run_cfq(
            "settings", "get", "stopSevenDayPct", home=self.home, env={"CFQ_STOP_SEVEN_DAY_PCT": "50"}
        ).stdout.strip()
        self.assertEqual(got, "50", msg=f"env override stopSevenDayPct -> got '{got}'")

        got = self.run_cfq(
            "settings",
            "get",
            "stopSevenDayPct",
            home=self.home,
            env={"CFQ_STOP_SEVEN_DAY_PCT": "abc"},
        ).stdout.strip()
        self.assertEqual(
            got, "95", msg=f"malformed CFQ_STOP_SEVEN_DAY_PCT -> got '{got}', want 95"
        )

        out = self.json_out(self.run_cfq("settings", "list", home=self.home))
        self.assertEqual(
            out["stopFiveHourPct"], 70, msg=f"list stopFiveHourPct = '{out['stopFiveHourPct']}', want 70"
        )
        self.assertEqual(
            out["stopSevenDayPct"], 95, msg=f"list stopSevenDayPct = '{out['stopSevenDayPct']}', want 95"
        )


if __name__ == "__main__":
    unittest.main()
