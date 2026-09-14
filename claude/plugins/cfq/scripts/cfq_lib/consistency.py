"""Reads all four places a batch's completion state is written down -- the filesystem, the
`report.json` ledger, Git commit trailers, and the changelog -- and reports where they disagree.
No printing, no repair: `cfq_batch_id.py` (CLI: `cfq batch verify`/`cfq batch recover`),
`cfq_scan.py` (the cheap filesystem-vs-ledger subset) and the tests all import this module rather
than each re-deriving the comparison.

See `.batch-context.md`'s Decisions: `done/` stays the authority for phase state: this module
never treats a mismatch as license to synthesize plan **text** back from the changelog. It only
ever reconstructs a ledger entry (a JSON record) or restores a file `cfq trash` still holds.
"""

import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import cfq_changelog  # noqa: E402
from . import render  # noqa: E402
from . import trash  # noqa: E402
from .proc import CFQ_BIN  # noqa: E402

STALE_PLANNING_SECONDS = 6 * 3600

_PHASE_LINE_PREFIX = "    - phase: "
_STATUS_LINE_PREFIX = "      status: "
_SUMMARY_LINE_PREFIX = "      summary: "


# ---- source 1: the filesystem --------------------------------------------------------------

def filesystem_state(batch_dir):
    """Open slugs (root `NN-*.md`), done slugs (`done/*.md`), and the `.planning` marker's
    presence/age -- the same glob patterns `cfq_scan.py` counts by, so this never drifts from
    what `/ifq` itself sees as open."""
    batch_dir = pathlib.Path(batch_dir)
    open_slugs = sorted(p.stem for p in batch_dir.glob("[0-9][0-9]-*.md") if p.is_file())
    done_dir = batch_dir / "done"
    done_slugs = sorted(p.stem for p in done_dir.glob("*.md") if p.is_file()) if done_dir.is_dir() else []

    marker = batch_dir / ".planning"
    planning_present = marker.is_file()
    planning_age = None
    if planning_present:
        planning_age = time.time() - marker.stat().st_mtime

    return {
        "openSlugs": open_slugs,
        "doneSlugs": done_slugs,
        "planningPresent": planning_present,
        "planningAgeSeconds": planning_age,
    }


# ---- source 2: the report.json ledger --------------------------------------------------------

def ledger_state(batch_dir):
    """slug -> {status, commit, reopened, textUnrecoverable}, the *latest* entry for each slug --
    `report.json`'s `phases` list is append-only (a redo after `reopen` appends a fresh entry
    rather than overwriting), so iterating in file order and keeping the last write per slug is
    what "latest" means here, the same rule `cfq_phase.py reopen` and `cfq_report.py set-commit`
    already apply."""
    f = pathlib.Path(batch_dir) / "report.json"
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    state = {}
    for p in data.get("phases", []) if isinstance(data, dict) else []:
        if not isinstance(p, dict):
            continue
        slug = p.get("phase")
        if not isinstance(slug, str):
            continue
        state[slug] = {
            "status": p.get("status"),
            "commit": p.get("commit"),
            "reopened": bool(p.get("reopened")),
            "textUnrecoverable": bool(p.get("textUnrecoverable")),
        }
    return state


# ---- source 3: Git commit trailers -----------------------------------------------------------

def git_state(repo, batch):
    """slug -> {status, commit} from every commit whose message carries `CFQ-Batch: <batch>`,
    keeping the newest commit per slug (a slug committed twice -- a redo after `reopen` -- keeps
    the one `git log` (newest-first) sees first). Empty when `repo` has no Git directory at all --
    a degraded verify, not an error. Every trailer recorded here is `green`: `cfq_changelog.py
    commit-message` refuses to stamp a commit for a red phase, so a red attempt never reaches
    history at all."""
    if not cfq_changelog.is_git_repo(repo):
        return {}
    # One commit at a time (`-1 <hash>`), never a single multi-trailer --format across every
    # match: the trailers placeholder appends its own trailing newline, so packing two of them
    # plus %H into one --format line for many commits at once makes the record boundaries
    # ambiguous. Same one-commit-at-a-time shape as cfq_changelog.py's own
    # scan_trailer_batch_for_max.
    hashes = subprocess.run(
        ["git", "-C", repo, "log", "--all", "--fixed-strings", f"--grep=CFQ-Batch: {batch}", "--format=%H"],
        capture_output=True, text=True,
    ).stdout.split()
    state = {}
    for sha in hashes:
        phase = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%(trailers:key=CFQ-Phase,valueonly)", sha],
            capture_output=True, text=True,
        ).stdout.strip()
        if not phase or phase in state:
            continue
        status = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--format=%(trailers:key=CFQ-Phase-Status,valueonly)", sha],
            capture_output=True, text=True,
        ).stdout.strip()
        state[phase] = {"status": status, "commit": sha}
    return state


# ---- source 4: the changelog ------------------------------------------------------------------

def _parse_changelog_phases(block):
    """The `phases:` sub-block `cfq_changelog.py`'s `phases_yaml()` writes -- three fixed lines
    per phase (`phase`/`status`/`summary`, each a JSON-encoded string), parsed back positionally
    rather than through a YAML library, same reasoning as `cfq_changelog.py` itself."""
    lines = block.split("\n")
    phases = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith(_PHASE_LINE_PREFIX):
            i += 1
            continue
        phase = json.loads(lines[i][len(_PHASE_LINE_PREFIX):] or '""')
        status = ""
        summary = ""
        if i + 1 < len(lines) and lines[i + 1].startswith(_STATUS_LINE_PREFIX):
            status = json.loads(lines[i + 1][len(_STATUS_LINE_PREFIX):] or '""')
        if i + 2 < len(lines) and lines[i + 2].startswith(_SUMMARY_LINE_PREFIX):
            summary = json.loads(lines[i + 2][len(_SUMMARY_LINE_PREFIX):] or '""')
        phases.append({"phase": phase, "status": status, "summary": summary})
        i += 3
    return phases


def changelog_state(repo, batch):
    """{status, branch, phases} for `batch`'s block, read through `cfq_changelog.py`'s own
    line-oriented block reader (verbatim, no second YAML reader) -- None when the changelog is
    disabled, missing, or has no block for this batch."""
    target = cfq_changelog.changelog_file(repo)
    if target is None or not pathlib.Path(target).is_file():
        return None
    start = cfq_changelog.find_block_start(target, "  batch:", batch)
    if start is None:
        return None
    lines = cfq_changelog.read_lines(target)
    block = cfq_changelog.block_text(lines, start)
    return {
        "status": cfq_changelog.block_field(block, "  status:"),
        "branch": cfq_changelog.block_field(block, "  branch:"),
        "phases": _parse_changelog_phases(block),
    }


# ---- findings -----------------------------------------------------------------------------

def findings(batch_dir, repo, batch):
    """Compares all four sources and returns `[{"code", "phase", "detail"}, ...]` -- `phase` is
    None for a batch-level finding (`STALE_PLANNING`, `COMPLETE_NOT_ARCHIVED`,
    `CHANGELOG_STATUS_MISMATCH`)."""
    batch_dir = pathlib.Path(batch_dir)
    fs = filesystem_state(batch_dir)
    ledger = ledger_state(batch_dir)
    git = git_state(repo, batch)
    changelog = changelog_state(repo, batch)

    open_set = set(fs["openSlugs"])
    done_set = set(fs["doneSlugs"])
    result = []

    for slug, entry in ledger.items():
        if entry.get("status") != "green":
            continue
        if slug in done_set or slug in open_set:
            continue
        if entry.get("textUnrecoverable"):
            result.append({
                "code": "TEXT_UNRECOVERABLE", "phase": slug,
                "detail": f"{slug}: green in report.json, missing from done/, not recoverable from trash",
            })
        else:
            result.append({
                "code": "DONE_FILE_MISSING", "phase": slug,
                "detail": f"{slug}: green in report.json but missing from done/",
            })

    for slug in git:
        if slug not in ledger:
            result.append({
                "code": "LEDGER_MISSING_PHASE", "phase": slug,
                "detail": f"{slug}: commit {git[slug]['commit'][:12]} carries a green "
                          "CFQ-Phase-Status trailer but report.json has no entry for it",
            })

    for slug in done_set:
        if slug not in ledger and slug not in git:
            result.append({
                "code": "DONE_FILE_UNRECORDED", "phase": slug,
                "detail": f"{slug}: file in done/ has neither a ledger entry nor a commit trailer",
            })

    if fs["planningPresent"] and (fs["planningAgeSeconds"] or 0) > STALE_PLANNING_SECONDS:
        age_h = fs["planningAgeSeconds"] / 3600
        result.append({
            "code": "STALE_PLANNING", "phase": None,
            "detail": f".planning marker is {age_h:.1f}h old (stale past {STALE_PLANNING_SECONDS // 3600}h)",
        })

    complete = not open_set and bool(ledger) and all(e.get("status") == "green" for e in ledger.values())
    if complete:
        result.append({
            "code": "COMPLETE_NOT_ARCHIVED", "phase": None,
            "detail": f"{batch}: no open phases, {len(ledger)} phase(s) green, still under impl/",
        })

    if changelog is not None:
        status = changelog.get("status")
        if status == "done" and open_set:
            result.append({
                "code": "CHANGELOG_STATUS_MISMATCH", "phase": None,
                "detail": f"changelog status is 'done' but {len(open_set)} phase(s) are still open",
            })
        elif status == "in-progress" and complete:
            result.append({
                "code": "CHANGELOG_STATUS_MISMATCH", "phase": None,
                "detail": "changelog status is 'in-progress' but every phase is green and none are open",
            })

    return result


# ---- the cheap subset scan.py uses on every repo, every run ---------------------------------

def scan_consistency(batch_dir):
    """"ok"/"divergent"/"unknown" from the filesystem vs. the ledger only -- no Git, no
    changelog, since `cfq_scan.py` runs this across every registered repo and must stay fast.
    "divergent" mirrors `findings()`'s DONE_FILE_MISSING/DONE_FILE_UNRECORDED conditions without
    the Git/changelog sources; "unknown" is a `report.json` that exists but doesn't parse."""
    batch_dir = pathlib.Path(batch_dir)
    report_file = batch_dir / "report.json"
    if not report_file.is_file():
        return "ok"
    try:
        data = json.loads(report_file.read_text())
    except (OSError, json.JSONDecodeError):
        return "unknown"

    ledger = {}
    for p in data.get("phases", []) if isinstance(data, dict) else []:
        if isinstance(p, dict) and isinstance(p.get("phase"), str):
            ledger[p["phase"]] = p

    fs = filesystem_state(batch_dir)
    open_set = set(fs["openSlugs"])
    done_set = set(fs["doneSlugs"])

    for slug, entry in ledger.items():
        if entry.get("status") == "green" and slug not in done_set and slug not in open_set:
            return "divergent"
    for slug in done_set:
        if slug not in ledger:
            return "divergent"
    return "ok"


# ---- recover: apply the repairs findings() can name automatically ---------------------------

def _reconstruct_summary(repo, batch, slug, commit):
    changelog = changelog_state(repo, batch)
    if changelog:
        for p in changelog["phases"]:
            if p["phase"] == slug and p.get("summary"):
                return p["summary"]
    return subprocess.run(
        ["git", "-C", repo, "log", "-1", "--format=%s", commit], capture_output=True, text=True,
    ).stdout.strip()


def _mark_text_unrecoverable(batch_dir, slug):
    f = pathlib.Path(batch_dir) / "report.json"
    data = json.loads(f.read_text())
    phases = data.get("phases", [])
    matches = [i for i, p in enumerate(phases) if isinstance(p, dict) and p.get("phase") == slug]
    if matches:
        phases[matches[-1]]["textUnrecoverable"] = True
        render.write_json(str(f), data)


def recover(batch_dir, repo, batch, dry_run=False):
    """Applies exactly the repairs `findings()` can name automatically (never writes a phase
    `.md` file back -- that text is gone for good once it's neither in `done/` nor in `cfq
    trash`): `LEDGER_MISSING_PHASE` reconstructs the ledger entry from the commit,
    `DONE_FILE_MISSING` restores from `cfq trash` when a matching entry exists there and
    otherwise marks the phase `textUnrecoverable` (so it reports as `TEXT_UNRECOVERABLE`, not
    `DONE_FILE_MISSING`, from here on), `STALE_PLANNING` removes the marker, and
    `COMPLETE_NOT_ARCHIVED` only prints the ready-to-run `finish` command -- archiving is a
    session that meant to finish a batch, not a repair pass. Returns `(result, ok)`, `ok` False
    while any finding remains after the repairs (including the ones above that are
    print-only/unactionable) -- mirrors `cfq_batch_id.py reconcile`'s own `(result, ok)` shape."""
    batch_dir = pathlib.Path(batch_dir)
    initial = findings(batch_dir, repo, batch)
    repairs = []
    changed = False

    for finding in initial:
        code, slug = finding["code"], finding["phase"]

        if code == "LEDGER_MISSING_PHASE":
            g = git_state(repo, batch)[slug]
            entry = {
                "phase": slug, "status": "green", "commit": g["commit"],
                "summary": _reconstruct_summary(repo, batch, slug, g["commit"]),
                "recovered": True,
            }
            if not dry_run:
                report_file = batch_dir / "report.json"
                data = json.loads(report_file.read_text()) if report_file.is_file() else {"phases": []}
                data.setdefault("phases", []).append(entry)
                render.write_json(str(report_file), data)
                changed = True
            repairs.append({
                "code": code, "phase": slug,
                "action": f"reconstructed ledger entry from commit {g['commit'][:12]}",
            })

        elif code == "DONE_FILE_MISSING":
            target_path = str((batch_dir / "done" / f"{slug}.md").resolve())
            match = next((e for e in trash.entries(repo) if e["originalPath"] == target_path), None)
            if match is not None:
                if not dry_run:
                    trash.restore(repo, match["id"])
                    changed = True
                repairs.append({
                    "code": code, "phase": slug, "action": f"restored from trash entry {match['id']}",
                })
            else:
                if not dry_run:
                    _mark_text_unrecoverable(batch_dir, slug)
                    changed = True
                repairs.append({
                    "code": "TEXT_UNRECOVERABLE", "phase": slug,
                    "action": "not found in cfq trash; marked textUnrecoverable, text is gone",
                })

        elif code == "STALE_PLANNING":
            if not dry_run:
                (batch_dir / ".planning").unlink(missing_ok=True)
                changed = True
            repairs.append({"code": code, "phase": None, "action": "removed the .planning marker"})

        elif code == "COMPLETE_NOT_ARCHIVED":
            changelog = changelog_state(repo, batch)
            branch = changelog.get("branch") if changelog else None
            if branch:
                cmd = f"{CFQ_BIN} finish {repo} {batch_dir} {branch}"
            else:
                cmd = f"{CFQ_BIN} finish {repo} {batch_dir} <branch -- none on record in the changelog>"
            repairs.append({"code": code, "phase": None, "action": f"run manually: {cmd}"})

        else:
            repairs.append({"code": code, "phase": slug, "action": "no automatic repair"})

    final = findings(batch_dir, repo, batch) if changed else initial
    result = {
        "status": "OK", "batch": batch, "dryRun": dry_run, "repairs": repairs, "findings": final,
    }
    return result, len(final) == 0
