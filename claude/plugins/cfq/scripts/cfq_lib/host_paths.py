"""The one place that turns an absolute repo path into what the browser's host can open: an
editor link (`vscode://...`), an OS path (for copy-to-clipboard) and a `file://` URL.

Three hosts are supported -- `posix` (Linux, macOS), `windows` (native Windows Python, run
through Git Bash) and `wsl` (Linux under WSL, browser and editors on the Windows side). The three
translation functions are pure (host and distro are passed in); only `detect()` and `resolve()`
touch the environment, and neither ever raises: a host that cannot be classified degrades to
`posix`, so a portal sync never fails on it.
"""

import json
import os
import re
import subprocess
import urllib.parse

from cfq_lib.paths import reports_dir
from cfq_lib.proc import cfq_run

_MNT_RE = re.compile(r"^/mnt/([A-Za-z])(?:/(.*))?$")
_WSLPATH_RE = re.compile(r"^\\\\(?:wsl\.localhost|wsl\$)\\([^\\/]+)")

_OSRELEASE = "/proc/sys/kernel/osrelease"


def _read_osrelease():
    try:
        with open(_OSRELEASE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _run_wslpath():
    """Output of `wslpath -w /` (`\\\\wsl.localhost\\<distro>\\`), None on any failure."""
    try:
        proc = subprocess.run(
            ["wslpath", "-w", "/"], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _distro_from_wslpath(output):
    m = _WSLPATH_RE.match((output or "").strip())
    return m.group(1) if m else ""


def _find_distro(environ=os.environ, run_wslpath=None):
    """`WSL_DISTRO_NAME`, else the first component of `wslpath -w /`; "" when neither yields one."""
    name = environ.get("WSL_DISTRO_NAME", "")
    if name:
        return name
    return _distro_from_wslpath((run_wslpath or _run_wslpath)())


def detect(os_name=None, environ=None, read_osrelease=None, run_wslpath=None):
    """`(platform, distro)` of the machine cfq runs on. WSL without a findable distro is `posix`."""
    os_name = os.name if os_name is None else os_name
    environ = os.environ if environ is None else environ
    read_osrelease = read_osrelease or _read_osrelease
    if os_name == "nt":
        return "windows", ""
    in_wsl = bool(environ.get("WSL_DISTRO_NAME")) or "microsoft" in (read_osrelease() or "").lower()
    if not in_wsl:
        return "posix", ""
    distro = _find_distro(environ, run_wslpath)
    return ("wsl", distro) if distro else ("posix", "")


def resolve(repo, settings=None):
    """`(platform, distro)` for `repo`, honouring the `hostPlatform` and `wslDistro` settings.
    `settings` is the dict of one `settings list --repo` call; None reads it here."""
    if settings is None:
        try:
            proc = cfq_run("settings", "list", "--repo", str(repo))
            settings = json.loads(proc.stdout) if proc.returncode == 0 else {}
        except Exception:
            settings = {}
    platform = settings.get("hostPlatform") or "auto"
    pinned = settings.get("wslDistro") or ""
    if platform in ("windows", "posix"):
        return platform, ""
    if platform == "wsl":
        distro = pinned or _find_distro()
        return ("wsl", distro) if distro else ("posix", "")
    platform, distro = detect()
    if platform == "wsl" and pinned:
        distro = pinned
    return platform, distro


def _quote(path):
    return urllib.parse.quote(path, safe="/:")


def _slashes(path):
    return path.replace("\\", "/")


def _mnt(path):
    """`(DRIVE, rest)` for a `/mnt/<letter>/...` path, else None."""
    m = _MNT_RE.match(path)
    return (m.group(1).upper(), m.group(2) or "") if m else None


def os_path(path, platform, distro):
    """`path` as the host's file manager and clipboard spell it."""
    if platform == "windows":
        return path.replace("/", "\\")
    if platform == "wsl":
        mnt = _mnt(path)
        if mnt:
            return f"{mnt[0]}:\\" + mnt[1].replace("/", "\\")
        return f"\\\\wsl.localhost\\{distro}" + path.replace("/", "\\")
    return path


def editor_url(path, scheme, platform, distro):
    """VS Code-family link that opens `path`; None when `scheme` is `off`."""
    if scheme == "off":
        return None
    if platform == "windows":
        return f"{scheme}://file/{_quote(_slashes(path))}"
    if platform == "wsl":
        mnt = _mnt(path)
        if mnt:
            return f"{scheme}://file/{_quote(f'{mnt[0]}:/{mnt[1]}')}"
        return f"{scheme}://vscode-remote/wsl+{_quote(distro)}{_quote(path)}"
    return f"{scheme}://file{_quote(path)}"


def file_url(path, platform, distro):
    """`file://` URL of `path` as the host's browser needs it."""
    if platform == "windows":
        return f"file:///{_quote(_slashes(path))}"
    if platform == "wsl":
        mnt = _mnt(path)
        if mnt:
            return f"file:///{_quote(f'{mnt[0]}:/{mnt[1]}')}"
        return f"file://wsl.localhost/{_quote(distro)}{_quote(path)}"
    return f"file://{_quote(path)}"


def portal_batch_url(repo, batch_name, platform=None, distro=None):
    """`file://` route for `batch_name` inside `repo`'s repo-local report portal, in the form the
    host's browser opens -- the one place `cfq_finish.py`'s `Report` status line and
    `cfq_brief.py`'s `Portal` line compute this, so they can never disagree on the URL shape.
    `platform=None` resolves the host from the settings; the `#/batch/<name>` fragment is never
    percent-encoded."""
    if platform is None:
        platform, distro = resolve(repo)
    return file_url(f"{reports_dir(repo)}/index.html", platform, distro or "") + "#/batch/" + batch_name
