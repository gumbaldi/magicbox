"""Unit tests for cfq_lib/host_paths.py, the one place that turns an absolute repo path into an
editor link, an OS path and a `file://` URL for the host the browser runs on. The translation
functions are pure, so these tests pin host and distro explicitly and pass on any machine."""

import json
import subprocess
import sys
import unittest
from unittest import mock

from cfq_testlib import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import host_paths  # noqa: E402

SPACED = "/home/code/my repo/.claude/cfq/impl/001-a/01-x.md"
MNT = "/mnt/c/Users/Tobi/my repo/plan.md"


def _wslpath(output):
    return lambda: output


class TranslationTest(unittest.TestCase):
    def test_posix(self):
        self.assertEqual(host_paths.os_path(SPACED, "posix", ""), SPACED)
        self.assertEqual(
            host_paths.editor_url(SPACED, "vscode", "posix", ""),
            "vscode://file/home/code/my%20repo/.claude/cfq/impl/001-a/01-x.md",
        )
        self.assertEqual(
            host_paths.file_url(SPACED, "posix", ""),
            "file:///home/code/my%20repo/.claude/cfq/impl/001-a/01-x.md",
        )

    def test_windows(self):
        p = "C:/Users/Tobi/my repo/plan.md"
        self.assertEqual(host_paths.os_path(p, "windows", ""), "C:\\Users\\Tobi\\my repo\\plan.md")
        self.assertEqual(
            host_paths.os_path("C:\\Users\\Tobi\\plan.md", "windows", ""),
            "C:\\Users\\Tobi\\plan.md",
        )
        self.assertEqual(
            host_paths.editor_url(p, "vscode", "windows", ""),
            "vscode://file/C:/Users/Tobi/my%20repo/plan.md",
        )
        self.assertEqual(
            host_paths.editor_url("C:\\Users\\Tobi\\plan.md", "vscode", "windows", ""),
            "vscode://file/C:/Users/Tobi/plan.md",
        )
        self.assertEqual(
            host_paths.file_url(p, "windows", ""),
            "file:///C:/Users/Tobi/my%20repo/plan.md",
        )

    def test_wsl_mnt_drive(self):
        self.assertEqual(
            host_paths.os_path(MNT, "wsl", "Ubuntu"), "C:\\Users\\Tobi\\my repo\\plan.md"
        )
        self.assertEqual(
            host_paths.editor_url(MNT, "vscode", "wsl", "Ubuntu"),
            "vscode://file/C:/Users/Tobi/my%20repo/plan.md",
        )
        self.assertEqual(
            host_paths.file_url(MNT, "wsl", "Ubuntu"),
            "file:///C:/Users/Tobi/my%20repo/plan.md",
        )

    def test_wsl_linux_path(self):
        self.assertEqual(
            host_paths.os_path(SPACED, "wsl", "AlmaLinux9"),
            "\\\\wsl.localhost\\AlmaLinux9\\home\\code\\my repo\\.claude\\cfq\\impl\\001-a\\01-x.md",
        )
        self.assertEqual(
            host_paths.editor_url(SPACED, "vscode", "wsl", "AlmaLinux9"),
            "vscode://vscode-remote/wsl+AlmaLinux9/home/code/my%20repo/.claude/cfq/impl/001-a/01-x.md",
        )
        self.assertEqual(
            host_paths.file_url(SPACED, "wsl", "AlmaLinux9"),
            "file://wsl.localhost/AlmaLinux9/home/code/my%20repo/.claude/cfq/impl/001-a/01-x.md",
        )

    def test_wsl_mnt_requires_single_letter_drive(self):
        p = "/mnt/wsl/foo"
        self.assertTrue(host_paths.os_path(p, "wsl", "U").startswith("\\\\wsl.localhost\\U\\mnt"))

    def test_non_ascii_percent_encoded_in_urls_only(self):
        p = "/home/code/übung/a.md"
        self.assertEqual(host_paths.os_path(p, "posix", ""), p)
        self.assertEqual(
            host_paths.editor_url(p, "vscode", "posix", ""), "vscode://file/home/code/%C3%BCbung/a.md"
        )

    def test_off_returns_none(self):
        self.assertIsNone(host_paths.editor_url(SPACED, "off", "posix", ""))
        self.assertIsNone(host_paths.editor_url(SPACED, "off", "wsl", "Ubuntu"))

    def test_fork_scheme_only_changes_scheme(self):
        a = host_paths.editor_url(SPACED, "vscode", "wsl", "Ubuntu")
        b = host_paths.editor_url(SPACED, "cursor", "wsl", "Ubuntu")
        self.assertEqual(b, a.replace("vscode://", "cursor://", 1))


class DetectTest(unittest.TestCase):
    def detect(self, os_name="posix", environ=None, osrelease="6.5.0-generic", wslpath=None):
        return host_paths.detect(
            os_name=os_name,
            environ=environ or {},
            read_osrelease=lambda: osrelease,
            run_wslpath=wslpath or (lambda: None),
        )

    def test_nt_is_windows(self):
        self.assertEqual(self.detect(os_name="nt"), ("windows", ""))

    def test_env_distro(self):
        self.assertEqual(
            self.detect(environ={"WSL_DISTRO_NAME": "Ubuntu"}), ("wsl", "Ubuntu")
        )

    def test_wslpath_fallback_localhost(self):
        got = self.detect(
            environ={"WSL_DISTRO_NAME": ""},
            osrelease="6.6.87.1-microsoft-standard-WSL2",
            wslpath=_wslpath("\\\\wsl.localhost\\AlmaLinux9\\\n"),
        )
        self.assertEqual(got, ("wsl", "AlmaLinux9"))

    def test_wslpath_fallback_old_dollar_form(self):
        got = self.detect(
            osrelease="5.15.0-Microsoft", wslpath=_wslpath("\\\\wsl$\\Debian\\")
        )
        self.assertEqual(got, ("wsl", "Debian"))

    def test_plain_linux(self):
        self.assertEqual(self.detect(), ("posix", ""))

    def test_wsl_without_distro_degrades_to_posix(self):
        got = self.detect(osrelease="6.6.87.1-microsoft-standard-WSL2", wslpath=lambda: None)
        self.assertEqual(got, ("posix", ""))
        got = self.detect(
            osrelease="6.6.87.1-microsoft-standard-WSL2", wslpath=_wslpath("garbage")
        )
        self.assertEqual(got, ("posix", ""))

    def test_osrelease_unreadable(self):
        got = host_paths.detect(
            os_name="posix", environ={}, read_osrelease=lambda: None, run_wslpath=lambda: None
        )
        self.assertEqual(got, ("posix", ""))

    def test_default_wslpath_runner_swallows_errors(self):
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(host_paths._run_wslpath())
        failed = subprocess.CompletedProcess(["wslpath"], 1, stdout="", stderr="x")
        with mock.patch.object(subprocess, "run", return_value=failed):
            self.assertIsNone(host_paths._run_wslpath())


class ResolveTest(unittest.TestCase):
    def test_override_windows_on_linux(self):
        self.assertEqual(
            host_paths.resolve("/r", {"hostPlatform": "windows", "wslDistro": ""}),
            ("windows", ""),
        )

    def test_override_posix(self):
        self.assertEqual(host_paths.resolve("/r", {"hostPlatform": "posix"}), ("posix", ""))

    def test_override_wsl_with_distro_setting(self):
        self.assertEqual(
            host_paths.resolve("/r", {"hostPlatform": "wsl", "wslDistro": "Fedora"}),
            ("wsl", "Fedora"),
        )

    def test_override_wsl_without_any_distro_degrades(self):
        with mock.patch.object(host_paths, "_find_distro", return_value=""):
            self.assertEqual(
                host_paths.resolve("/r", {"hostPlatform": "wsl", "wslDistro": ""}),
                ("posix", ""),
            )

    def test_auto_uses_detect_and_distro_setting_wins(self):
        with mock.patch.object(host_paths, "detect", return_value=("wsl", "FromWslpath")):
            self.assertEqual(
                host_paths.resolve("/r", {"hostPlatform": "auto", "wslDistro": "Pinned"}),
                ("wsl", "Pinned"),
            )
            self.assertEqual(
                host_paths.resolve("/r", {"hostPlatform": "auto", "wslDistro": ""}),
                ("wsl", "FromWslpath"),
            )

    def test_auto_detects_windows_ignores_distro_setting(self):
        with mock.patch.object(host_paths, "detect", return_value=("windows", "")):
            self.assertEqual(
                host_paths.resolve("/r", {"hostPlatform": "auto", "wslDistro": "Pinned"}),
                ("windows", ""),
            )

    def test_settings_none_reads_one_bulk_call(self):
        out = json.dumps({"hostPlatform": "windows", "wslDistro": ""})
        proc = subprocess.CompletedProcess([], 0, stdout=out, stderr="")
        with mock.patch.object(host_paths, "cfq_run", return_value=proc) as run:
            self.assertEqual(host_paths.resolve("/repo"), ("windows", ""))
        run.assert_called_once_with("settings", "list", "--repo", "/repo")

    def test_settings_read_failure_falls_back_to_detection(self):
        proc = subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        with mock.patch.object(host_paths, "cfq_run", return_value=proc), mock.patch.object(
            host_paths, "detect", return_value=("posix", "")
        ):
            self.assertEqual(host_paths.resolve("/repo"), ("posix", ""))
        with mock.patch.object(host_paths, "cfq_run", side_effect=RuntimeError("no bash")), \
                mock.patch.object(host_paths, "detect", return_value=("posix", "")):
            self.assertEqual(host_paths.resolve("/repo"), ("posix", ""))


if __name__ == "__main__":
    unittest.main()
