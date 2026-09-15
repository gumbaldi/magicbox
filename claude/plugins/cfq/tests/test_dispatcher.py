"""Migrated from test-dispatcher.sh (bin/cfq, the single entrypoint).

The 21 scripts under scripts/ stay directly callable and unchanged (every other migrated test
here still calls them that way) — this file only asserts the dispatcher routes to them correctly,
one behaviour per case, all in one run.
"""

import re
import subprocess
import unittest

from cfq_testlib import CFQ_BIN, SCRIPTS_DIR, CfqTestCase

CORE_BINS = ["bash", "dirname", "grep", "sed", "sort", "cat"]


class DispatcherTest(CfqTestCase):
    def test_01_routine_byte_identical_stdout(self):
        # JSON array, JSON object and plain text — three different output shapes.
        repo1 = self.make_repo("repo1")
        a = subprocess.run(
            [str(CFQ_BIN), "settings", "list", "--repo", str(repo1)],
            capture_output=True, text=True,
        )
        b = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "cfq_settings.py"), "list", "--repo", str(repo1)],
            capture_output=True, text=True,
        )
        self.assertEqual(a.stdout, b.stdout, msg="settings list differs between dispatcher and direct call")

        home1 = self._repos_dir / "home1"
        home1.mkdir()
        scan_env = {"HOME": str(home1), "CFQ_SCAN_ROOTS": "/nonexistent-scan-root"}
        a = self.run_clean(str(CFQ_BIN), "scan", env=scan_env)
        b = self.run_clean("python3", str(SCRIPTS_DIR / "cfq_scan.py"), env=scan_env)
        self.assertEqual(a.stdout, b.stdout, msg="scan differs between dispatcher and direct call")

        home2 = self._repos_dir / "home2"
        home2.mkdir()
        doctor_env = {"HOME": str(home2)}
        a = self.run_clean(str(CFQ_BIN), "doctor", "check", env=doctor_env)
        b = self.run_clean("python3", str(SCRIPTS_DIR / "cfq_doctor.py"), "check", env=doctor_env)
        self.assertEqual(a.stdout, b.stdout, msg="doctor check differs between dispatcher and direct call")

    def test_02_argument_passthrough(self):
        repo2 = self.make_repo("repo2")
        tricky = "a value with a space and a $dollar sign"
        self.run_cfq("settings", "set", "--repo", str(repo2), "changelogFile", tricky, check=True)
        got = self.run_cfq("settings", "get", "--repo", str(repo2), "changelogFile").stdout.strip()
        self.assertEqual(got, tricky, msg=f"argument passthrough mangled the value: got '{got}'")

    def test_03_exit_codes_propagate(self):
        rc_dispatcher = self.run_cfq("batch", "allocate", "/no-such-repo-path").returncode
        rc_direct = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "cfq_batch_id.py"), "allocate", "/no-such-repo-path"],
            capture_output=True, text=True,
        ).returncode
        self.assertNotEqual(rc_dispatcher, 0, msg="dispatcher exit 0 on a failing subcommand")
        self.assertEqual(
            rc_dispatcher, rc_direct,
            msg=f"dispatcher exit ({rc_dispatcher}) != direct exit ({rc_direct})",
        )

    def test_04_unknown_noun(self):
        proc = self.run_cfq("nosuchthing")
        self.assertNotEqual(proc.returncode, 0, msg="unknown noun exited 0")
        self.assertIn("nouns:", proc.stderr, msg="unknown noun did not print the noun list to stderr")

    def test_05_no_arguments(self):
        proc = self.run_cfq()
        self.assertNotEqual(proc.returncode, 0, msg="no-args invocation exited 0")
        self.assertIn("nouns:", proc.stderr, msg="no-args invocation did not print the noun list")

    def test_06_help_fallback(self):
        proc = self.run_cfq("--help")
        self.assertEqual(proc.returncode, 0, msg=f"cfq --help exit = {proc.returncode}")
        out = proc.stdout + proc.stderr
        self.assertIn(" settings ", out, msg="cfq --help does not name the settings noun")

        proc = self.run_cfq("settings", "--help")
        self.assertEqual(proc.returncode, 0, msg=f"cfq settings --help exit = {proc.returncode}")
        out = (proc.stdout + proc.stderr).lower()
        self.assertIn("list", out, msg="cfq settings --help does not name its verbs")

        proc = self.run_cfq("batch", "--help")
        self.assertEqual(proc.returncode, 0, msg=f"cfq batch --help exit = {proc.returncode}")
        out = (proc.stdout + proc.stderr).lower()
        self.assertTrue(
            "allocate" in out or "next" in out,
            msg="cfq batch --help (fallback path) does not name its verbs",
        )

    def test_07_completeness_every_script_reachable(self):
        # Extracted straight from bin/cfq's own noun_script() case statement, not retyped here,
        # so this stays a structural check rather than a copy that can silently drift from the
        # real map (a Bash-3.2-compatible `case` function, not a Bash-4 associative array --
        # see test_08 below). Scripts may be shell or Python; scripts/cfq_lib/ is a package, not
        # a command, and a non-recursive glob already excludes it without needing to say so.
        text = CFQ_BIN.read_text()
        pattern = re.compile(r"^\s*[a-z-]+\) echo (cfq[a-z_-]+\.(?:sh|py)|ctx_usage\.py) ;;$", re.MULTILINE)
        mapped = sorted({m.group(1) for m in pattern.finditer(text)})
        on_disk = sorted(
            f.name
            for f in list(SCRIPTS_DIR.glob("*.sh")) + list(SCRIPTS_DIR.glob("*.py"))
        )
        self.assertEqual(
            mapped, on_disk,
            msg="dispatcher routing table and scripts/*.sh + scripts/*.py disagree",
        )

        # Exactly one noun per script (no script mapped twice).
        all_mapped = [m.group(1) for m in pattern.finditer(text)]
        dupes = sorted({s for s in all_mapped if all_mapped.count(s) > 1})
        self.assertEqual(dupes, [], msg=f"script(s) mapped by more than one noun: {dupes}")

    def test_08_every_help_listed_noun_routes(self):
        # Dynamic counterpart to test_07's static table check: actually runs `--help` for every
        # noun bin/cfq itself advertises, catching a typo'd case arm (e.g. a stray noun in the
        # NOUNS list with no matching case branch) that a text-only check would miss.
        listed = self.run_cfq()
        nouns = re.findall(r"^  ([a-z-]+) +\S", listed.stderr, re.MULTILINE)
        self.assertTrue(nouns, msg=f"could not parse any noun from --help output: {listed.stderr}")
        for noun in nouns:
            with self.subTest(noun=noun):
                proc = self.run_cfq(noun, "--help")
                self.assertEqual(
                    proc.returncode, 0, msg=f"cfq {noun} --help exit={proc.returncode}: {proc.stderr}"
                )
                self.assertNotIn(
                    f"unknown noun '{noun}'", proc.stderr, msg=f"{noun} does not route to a script"
                )

    def test_09_bash_32_compatible_syntax_only(self):
        # Static check: macOS ships Bash 3.2 as /bin/bash, which lacks associative arrays,
        # ${!name[@]} key expansion, mapfile/readarray, ;;&/;& case fallthrough and
        # ${var,,}/${var^^} case conversion -- all Bash 4+ features. No construct here proves
        # 3.2 compatibility on its own; this only guards against reintroducing one of them.
        text = CFQ_BIN.read_text()
        self.assertNotIn("declare -A", text, msg="bin/cfq uses a Bash 4 associative array")
        self.assertNotIn("${!", text, msg="bin/cfq uses Bash 4 ${!name[@]} key expansion")
        self.assertNotIn("mapfile", text, msg="bin/cfq uses the Bash 4 mapfile builtin")
        self.assertNotIn("readarray", text, msg="bin/cfq uses the Bash 4 readarray builtin")
        self.assertNotRegex(text, r";;&|;&", msg="bin/cfq uses Bash 4 case fallthrough")
        self.assertNotRegex(
            text, r"\$\{\w+(,,|\^\^)\}", msg="bin/cfq uses Bash 4 ${var,,}/${var^^} case conversion"
        )

        version = subprocess.run(["/bin/bash", "--version"], capture_output=True, text=True)
        if version.returncode == 0 and re.search(r"version 3\.", version.stdout):
            proc = subprocess.run(["/bin/bash", str(CFQ_BIN), "--help"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=f"bin/cfq --help under /bin/bash 3.x: {proc.stderr}")

    def test_10_python_fallback_via_python_symlink(self):
        # Fallback: a PATH with no python3 but a `python` symlink to the real interpreter still
        # works -- the case bin/cfq must handle for a Windows Git Bash host, or any host where
        # only `python` is on PATH.
        path = self.minimal_path(*CORE_BINS, rename={"python": "python3"})
        repo = self.make_repo("repo-fallback")
        proc = self.run_cfq("settings", "get", "--repo", str(repo), "docLevel", env={"PATH": path})
        self.assertEqual(proc.returncode, 0, msg=f"settings get failed under python-only PATH: {proc.stderr}")
        self.assertIn(proc.stdout.strip(), ("minimal", "standard"), msg=f"unexpected docLevel: {proc.stdout!r}")

    def test_11_no_python_at_all_is_exit_127(self):
        # Failure: no python3, no python, no py anywhere on PATH -> exit 127 with the named guard
        # message (reworded from "python3 is required" to "Python 3 is required", since the
        # guard no longer names one specific interpreter binary).
        path = self.minimal_path(*CORE_BINS)
        proc = self.run_cfq("settings", "get", "docLevel", env={"PATH": path})
        self.assertEqual(proc.returncode, 127, msg=f"no-python exit={proc.returncode} (want 127)")
        self.assertIn(
            "cfq: Python 3 is required for 'settings' but was not found on PATH.", proc.stderr,
            msg=f"missing named Python-guard message: {proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
