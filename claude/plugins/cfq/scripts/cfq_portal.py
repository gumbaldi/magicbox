#!/usr/bin/env python3
# Usage: cfq_portal.py sync <repo-root> [--batch <name>]...
#        cfq_portal.py rebuild <repo-root> [--migrate]
"""Writes both halves of `<repo>/.claude/cfq/reports/index.html`: the fixed viewer shell
(`index.html` plus `assets/*`, copied in from the plugin's own `portal/` source by
`install_shell()` whenever `reports/.portal-version` differs from the running plugin's own
version) and the data layer it reads, under `reports/data/`:

    site.js            {mode, repo, commitUrl, pluginVersion}
    queue.js           the repo overview: totals, one row per batch, one row per entry
    batch/<name>.js    one file per batch (also one without a report.json): context, planning,
                       phases with their attempts, cost, notes, closing result, security
    entry/<id>.js      one file per todo card / plan-inbox entry, open and closed (the archive)

Every data file registers a JSON payload on `window.CFQ_DATA` rather than being fetched, since
browsers block `fetch()` of a local JSON file under `file://` but a `<script src>` tag still works:

    window.CFQ_DATA = window.CFQ_DATA || {}; window.CFQ_DATA["batch/<b>"] = { ... };

A data file's path below `data/` is always its key plus `.js` -- `write(key, payload)` derives the
path from the key, so the viewer can derive it the same way. The payload shapes are the contract
in `.batch-context.md` (Portal data files). Cost is turns and tokens (input, output, cache read,
cache creation) split by model, never a price.

Deterministic, at zero model-token cost: no timestamp is ever written beyond one already present
in the source data (`report.json`, a queue-entry filename), and every payload's object keys are
sorted, so a re-sync that changes nothing writes nothing. `sync <repo-root> [--batch <name>]...`
recomputes the shell (when its version stamp moved on -- which also deletes the legacy flat
`reports/<batch>.html` files), `queue.js`, `site.js`, the named batches' own files (every batch
when `--batch` is omitted) and every entry file; it also deletes a `batch/*.js`/`entry/*.js` file
whose source batch or entry no longer exists (this is what retires the old
`batch/<name>.plan.js`/`.impl.js` pair). `rebuild <repo-root>` is `sync` with no `--batch`
filter, kept as its own verb for manual repair and, with `--migrate`, the one-time removal of the
legacy HTML in this repo's own `reportDir` mirror too. Flags (`cfq_lib/flags.py`) and the per-size
baselines/calibration points in `queue.js` are derived from every batch's payload: a batch outside
the `--batch` filter is read back from its existing data file, its `flags` recomputed against the
current baselines and the file rewritten only if they changed. Both print one JSON object: `{"status",
"written", "unchanged", "removed"}`.

`merged` (queue row and batch payload) is read from Git, never from a queue file: `true` when the
batch's tip is reachable from the default branch (`cfq_lib.proc.default_branch`, `origin` first),
`false` when not, `null` when it cannot be told (batch not done, no `branch:` in the changelog block,
no tip, no default branch, no Git repository). The tip is, in this order, the local branch named in
the changelog block, the same branch on `origin`, the full-SHA `commit` of the last ledger phase
that has one (so a branch deleted after the merge stays `true`). Two Git calls per `sync`
(`git_merge_lookup()`), none per batch; a squash-merged branch stays `false`.

Reuses rather than re-derives: `cfq_brief.parse_phase_body` for a phase file's title/size,
`cfq_queue_overlap.extract_affected_files` for its affected files, `cfq_report.read_batch_context`
for `.batch-context.md`'s sections, `cfq_report.phase_layer_sums` (the four-layer cost split) for
every layer total, `cfq_changelog` for a batch's branch and base, and `cfq_scan.scan_repo` (the
same per-repo record builder the dashboard uses) for batch status -- never a second scan.

When the `reportDir` setting resolves to a non-empty absolute path, `sync()` additionally mirrors
every data file it just wrote (repo-local) to `<reportDir>/<repo-name>[-<hash>]/data/...` --
`<repo-name>` is the repo directory's basename, suffixed with a short hash of the absolute repo
path only on a collision with a different repo already mirrored under that name, a mapping
recorded (and kept stable across syncs) in `<reportDir>/data/repos.js`. The fixed viewer shell is
installed once at `<reportDir>/` itself (not per repo), and `<reportDir>/data/site.js` carries
`{"mode": "global"}` so the viewer renders the cross-repo index instead of one repo's overview. A
mirror failure (permission denied, `reportDir` not creatable) never fails the repo-local sync --
the JSON result carries `"mirror": {"status": "ERROR", "detail": ...}` instead, with the
repo-local files written exactly as if `reportDir` were unset.
"""

import argparse
import copy
import hashlib
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_brief import parse_phase_body  # noqa: E402
from cfq_queue_overlap import extract_affected_files  # noqa: E402
from cfq_lib import flags as cfq_flags  # noqa: E402
from cfq_lib import markdown as cfq_lib_markdown  # noqa: E402
from cfq_lib import paths as cfq_lib_paths  # noqa: E402
from cfq_lib import phase_state  # noqa: E402
from cfq_lib import render  # noqa: E402
from cfq_lib.proc import default_branch, git, settings_get  # noqa: E402

import cfq_changelog  # noqa: E402
import cfq_report  # noqa: E402
import cfq_scan  # noqa: E402

PROG = "cfq_portal.py"

ENTRY_KINDS = ("plan", "todo")
ENTRY_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
CHECK_RE = re.compile(r"^check:\s*(.+)$")


# ---- layout ------------------------------------------------------------------------------------

def reports_dir(repo_root):
    return pathlib.Path(repo_root) / ".claude" / "cfq" / "reports"


def data_dir(repo_root):
    return reports_dir(repo_root) / "data"


def plugin_root():
    """`scripts/` -> the plugin root, one level up -- the same relative layout in a checkout and
    in an installed plugin cache. Used to locate both the viewer's own source (`portal/`) and
    `.claude-plugin/plugin.json` for the version stamp below."""
    return pathlib.Path(__file__).resolve().parent.parent


def plugin_version():
    try:
        data = json.loads((plugin_root() / ".claude-plugin" / "plugin.json").read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return data.get("version", "") if isinstance(data, dict) else ""


def batch_directory(repo_root, batch_record):
    base = (
        cfq_lib_paths.impl_done_dir(repo_root)
        if batch_record.get("archived")
        else cfq_lib_paths.impl_dir(repo_root)
    )
    return pathlib.Path(base) / batch_record["name"]


# ---- write-if-changed ---------------------------------------------------------------------------

def _dump_json(obj):
    """Sorted-key, indented JSON -- deterministic across syncs so an unchanged payload never
    trips `write_if_changed`. `render.dump_json` (compact, insertion order) isn't used here on
    purpose: it doesn't sort keys, which this module's determinism contract requires."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def render_data_file(key, payload):
    return (
        "window.CFQ_DATA = window.CFQ_DATA || {};\n"
        f"window.CFQ_DATA[{json.dumps(key, ensure_ascii=False)}] = {_dump_json(payload)};\n"
    )


def write_if_changed(path, content):
    """True if `path` was written (didn't exist, or existed with different content), False if
    left untouched. Writes through `render.write_text_atomic`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            if path.read_text() == content:
                return False
        except OSError:
            pass
    render.write_text_atomic(path, content)
    return True


def cleanup_stale(out_dir, expected_rel):
    """Removes every `batch/*.js`/`entry/*.js` file not in `expected_rel` -- a closed entry or a
    deleted batch loses its data file. Never touches `queue.js` itself (always expected, always
    rewritten) or anything outside `batch/`/`entry/`."""
    removed = []
    for sub in ("batch", "entry"):
        d = out_dir / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.js")):
            rel = f"{sub}/{f.name}"
            if rel not in expected_rel:
                f.unlink()
                removed.append(rel)
    return removed


# ---- install: the fixed viewer shell, copied in only when the plugin version moved on ----------

def shell_files():
    """`[(source name, path relative to the install root)]` for every file in the plugin's own
    `portal/` directory: `index.html` goes to the root, every other file to `assets/`."""
    src = plugin_root() / "portal"
    try:
        names = sorted(f.name for f in src.iterdir() if f.is_file() and not f.name.startswith("."))
    except OSError:
        return []
    return [(n, n if n == "index.html" else f"assets/{n}") for n in names]


def install_shell(out_dir, removed=None):
    """Copies the fixed viewer shell from the plugin's own `portal/` source (`index.html` to the
    root, every other file to `assets/`) into `out_dir` (a repo's `.claude/cfq/reports/`, or a
    `reportDir` root for the global mirror) whenever the installed stamp
    (`<out_dir>/.portal-version`) differs from the running plugin's own version -- an unchanged
    version copies nothing and removes nothing, so a sync never rewrites the tree on every call.
    A version change also deletes the files in `assets/` that `portal/` no longer has and the
    legacy flat `<batch>.html` files directly under `out_dir` (`remove_legacy_html`); their paths
    are appended to the `removed` list when one is passed.
    Returns the list of paths (relative to `out_dir`) actually written."""
    stamp_path = out_dir / ".portal-version"
    version = plugin_version()
    try:
        current = stamp_path.read_text().strip()
    except OSError:
        current = None
    if current == version:
        return []

    written = []
    files = shell_files()
    for src_name, rel in files:
        src = plugin_root() / "portal" / src_name
        try:
            content = src.read_text()
        except OSError:
            continue
        if write_if_changed(out_dir / rel, content):
            written.append(rel)
    kept = {rel for _src, rel in files}
    assets = out_dir / "assets"
    stale = []
    if assets.is_dir():
        for f in sorted(assets.iterdir()):
            if f.is_file() and f"assets/{f.name}" not in kept:
                f.unlink()
                stale.append(str(f))
    write_if_changed(stamp_path, version)
    legacy = remove_legacy_html(out_dir)
    if removed is not None:
        removed.extend(stale)
        removed.extend(legacy)
    return written


# ---- reportDir mirror: an additional copy of every repo's portal, plus a cross-repo index ------

DATA_FILE_RE = re.compile(
    r"^window\.CFQ_DATA = window\.CFQ_DATA \|\| \{\};\n"
    r"window\.CFQ_DATA\[.*?\] = (?P<payload>.*);\n\Z",
    re.S,
)


def report_dir_setting(repo_root):
    """`""`/`"null"` both mean "mirroring is off"."""
    value = settings_get(repo_root, "reportDir")
    return value if value not in ("", "null") else ""


def read_data_payload(path):
    """Parses a `window.CFQ_DATA[...] = <payload>;` data file back into its JSON payload -- the
    one place `repos.js` (this module's only data file ever read back, not just written) needs
    reading. Missing file, unreadable file or unexpected shape all degrade to `None` rather than
    raising, since a first sync into a fresh `reportDir` has no `repos.js` yet."""
    try:
        content = path.read_text()
    except OSError:
        return None
    m = DATA_FILE_RE.match(content)
    if not m:
        return None
    try:
        return json.loads(m.group("payload"))
    except json.JSONDecodeError:
        return None


def repos_js_path(report_dir):
    return pathlib.Path(report_dir) / "data" / "repos.js"


def resolve_mirror_name(existing_repos, repo_root):
    """The mirror directory name for `repo_root` under `reportDir`: stable once recorded --
    a repo already listed in `repos.js` (matched by its absolute `source` path, not by name) keeps
    its existing `mirror` value forever, even if a *third* repo later collides with its basename.
    A repo seen for the first time gets its own basename, unless another *different* repo already
    claimed that exact mirror name, in which case it gets a `-<short hash of its own absolute
    path>` suffix -- deterministic (the same repo always hashes to the same suffix) and stable
    (recorded here, in `repos.js`, the moment it's chosen)."""
    for r in existing_repos:
        if isinstance(r, dict) and r.get("source") == repo_root:
            return r.get("mirror") or pathlib.Path(repo_root).name
    base = pathlib.Path(repo_root).name
    used = {r.get("mirror") for r in existing_repos if isinstance(r, dict)}
    if base not in used:
        return base
    digest = hashlib.sha1(repo_root.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def repo_counts(queue_payload):
    """`{"batches": {"inProgress", "planned", "done"}, "todos", "planEntries"}` -- read straight off
    the queue payload's `totals`, so the cross-repo index can render a repo's card without loading
    and grouping that repo's full `queue.js` itself."""
    totals = queue_payload.get("totals", {})
    return {
        "batches": totals.get("batches", {"inProgress": 0, "planned": 0, "done": 0}),
        "todos": totals.get("todos", 0),
        "planEntries": totals.get("planEntries", 0),
    }


def update_repos_list(existing_repos, repo_root, mirror_name, counts):
    """Read-modify-write over the parsed `repos.js` list: only the row for `repo_root` changes
    (updated in place if present, appended otherwise) -- every other repo's row, including its
    position, is left untouched, so two repos syncing independently never race on each other's
    data."""
    name = pathlib.Path(repo_root).name
    row = {"name": name, "mirror": mirror_name, "source": repo_root, "counts": counts}
    rows, replaced = [], False
    for r in existing_repos:
        if isinstance(r, dict) and r.get("source") == repo_root:
            rows.append(row)
            replaced = True
        else:
            rows.append(r)
    if not replaced:
        rows.append(row)
    return rows


def mirror_sync(report_dir, repo_root, queue_payload, docs):
    """Mirrors `docs` (the `(key, payload)` pairs `sync()` just wrote repo-locally) into
    `<report_dir>/<mirror-name>/data/...`, installs the global shell once at `<report_dir>/`
    itself, and updates the cross-repo `<report_dir>/data/{site,repos}.js`. Raises on any
    filesystem failure -- the caller isolates it, since a mirror failure must never fail the
    repo-local sync it rides along with."""
    report_root = pathlib.Path(report_dir)
    shell_removed = []
    written = list(install_shell(report_root, shell_removed))
    unchanged = 0

    if write_if_changed(report_root / "data" / "site.js", render_data_file("site", {"mode": "global"})):
        written.append("data/site.js")
    else:
        unchanged += 1

    existing_repos = read_data_payload(repos_js_path(report_dir))
    if not isinstance(existing_repos, list):
        existing_repos = []
    mirror_name = resolve_mirror_name(existing_repos, repo_root)
    new_repos = update_repos_list(existing_repos, repo_root, mirror_name, repo_counts(queue_payload))
    if write_if_changed(repos_js_path(report_dir), render_data_file("repos", new_repos)):
        written.append("data/repos.js")
    else:
        unchanged += 1

    out_dir = report_root / mirror_name / "data"
    expected = set()
    for key, payload in docs:
        rel = f"{key}.js"
        expected.add(rel)
        if write_if_changed(out_dir / rel, render_data_file(key, payload)):
            written.append(f"{mirror_name}/data/{rel}")
        else:
            unchanged += 1
    removed = [f"{mirror_name}/data/{rel}" for rel in cleanup_stale(out_dir, expected)] + shell_removed

    return {"status": "OK", "written": sorted(written), "unchanged": unchanged, "removed": sorted(removed)}


# ---- cost: turns and tokens split by model, never a price -------------------------------------

T5_FIELDS = ("turns", "input", "output", "cache_read", "cache_creation")


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def t5(source):
    """`T` without `billable_in`, every field defaulting to 0 -- also for a non-dict `source`."""
    source = source if isinstance(source, dict) else {}
    return {f: _num(source.get(f)) for f in T5_FIELDS}


def add_t5(a, b):
    return {f: a[f] + b[f] for f in T5_FIELDS}


def zero_t5():
    return {f: 0 for f in T5_FIELDS}


def model_map(by_model):
    """`{model: T5}` from a record's/layer's/agent's `by_model`; `{}` when there is none (or it
    holds anything but per-model token dicts, as in the legacy `{model: turns}` shape)."""
    if not isinstance(by_model, dict):
        return {}
    return {m: t5(v) for m, v in by_model.items() if isinstance(v, dict)}


def merge_models(dst, src):
    for model, tokens in src.items():
        dst[model] = add_t5(dst[model], tokens) if model in dst else dict(tokens)


def empty_layers():
    return {name: {"total": zero_t5(), "byModel": {}, "count": 0} for name in cfq_report.LAYER_NAMES}


def cost_of(tel):
    """The contract's `COST` for one telemetry record, or `None` without one. Layer totals come
    from `cfq_report.phase_layer_sums()` (schema-1 fallback included); the per-model maps from
    each layer's and agent's own `by_model`."""
    if not isinstance(tel, dict):
        return None
    sums = cfq_report.phase_layer_sums(tel)
    layers, total, by_model = {}, zero_t5(), {}
    for name in cfq_report.LAYER_NAMES:
        src = sums[name]
        layer_total, layer_models = t5(src), model_map(src.get("by_model"))
        count = src.get("count")
        layers[name] = {
            "total": layer_total,
            "byModel": layer_models,
            "count": count if isinstance(count, int) and not isinstance(count, bool) else 0,
        }
        total = add_t5(total, layer_total)
        merge_models(by_model, layer_models)
    agents = []
    for a in tel.get("agents") if isinstance(tel.get("agents"), list) else []:
        if not isinstance(a, dict):
            continue
        agents.append({
            "id": render.jq_alt(a.get("id"), ""),
            "type": render.jq_alt(a.get("type"), ""),
            "description": render.jq_alt(a.get("description"), ""),
            "layer": render.jq_alt(a.get("layer"), ""),
            "parent": a.get("parent"),
            "total": t5(a.get("totals")),
            "byModel": model_map(a.get("by_model")),
        })
    return {"total": total, "byModel": by_model, "layers": layers, "agents": agents}


def merge_costs(costs):
    """Sums several `COST`s (layers and models field by field, agents concatenated in order);
    `None` when there is nothing to sum."""
    costs = [c for c in costs if c is not None]
    if not costs:
        return None
    total, by_model, layers, agents = zero_t5(), {}, empty_layers(), []
    for c in costs:
        total = add_t5(total, c["total"])
        merge_models(by_model, c["byModel"])
        for name in cfq_report.LAYER_NAMES:
            layers[name]["total"] = add_t5(layers[name]["total"], c["layers"][name]["total"])
            merge_models(layers[name]["byModel"], c["layers"][name]["byModel"])
            layers[name]["count"] += c["layers"][name]["count"]
        agents.extend(c["agents"])
    return {"total": total, "byModel": by_model, "layers": layers, "agents": agents}


def is_settled(tel):
    """Only an explicit `settled: false` is provisional -- a record without the key is final."""
    return not (isinstance(tel, dict) and tel.get("settled") is False)


def report_phases(data):
    phases = data.get("phases") if isinstance(data, dict) else None
    return [p for p in phases if isinstance(p, dict)] if isinstance(phases, list) else []


def telemetry_records(data):
    """The planning record (if any) followed by every attempt's telemetry, in ledger order."""
    planning = data.get("planning") if isinstance(data, dict) else None
    records = [planning] if isinstance(planning, dict) else []
    records += [p["telemetry"] for p in report_phases(data) if isinstance(p.get("telemetry"), dict)]
    return records


def batch_cost(data):
    return merge_costs([cost_of(tel) for tel in telemetry_records(data)])


def count_deviations(data):
    total = 0
    for p in report_phases(data):
        d = p.get("deviations")
        if isinstance(d, list):
            total += len(d)
    return total


# ---- batch identity: directory name, changelog block, merged state -------------------------------

BATCH_NAME_RE = re.compile(r"^(?:(\d+)-)?(\d{4}-\d{2}-\d{2})-(.+)$")


def parse_batch_name(name):
    """`NNN-YYYY-MM-DD-slug` or the older `YYYY-MM-DD-slug` -> `(number | None, date, title)`;
    the title is the slug with hyphens replaced by spaces."""
    m = BATCH_NAME_RE.match(name)
    if not m:
        return None, "", name.replace("-", " ")
    number = int(m.group(1)) if m.group(1) is not None else None
    return number, m.group(2), m.group(3).replace("-", " ")


def load_changelog(repo_root):
    """`{batch name: {"branch", "base"}}` from the repo's changelog -- the newest block of a name
    wins (the file is newest first). `{}` when the changelog is disabled or missing."""
    path = cfq_changelog.changelog_file(repo_root)
    if not path or not os.path.isfile(path):
        return {}
    try:
        lines = cfq_changelog.read_lines(path)
    except OSError:
        return {}
    blocks = {}
    for start in cfq_changelog.block_starts(lines):
        block = cfq_changelog.block_text(lines, start)
        name = cfq_changelog.block_field(block, "  batch:")
        if name and name not in blocks:
            blocks[name] = {
                "branch": cfq_changelog.block_field(block, "  branch:") or "",
                "base": cfq_changelog.block_field(block, "  base:") or "",
            }
    return blocks


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def git_merge_lookup(repo_root):
    """Two Git calls, once per `sync`: `{"merged": {commits reachable from the default branch},
    "refs": {ref name: commit}}` for `refs/heads` and `refs/remotes/origin`. `{}` when the default
    branch cannot be resolved, the directory is no Git repository or either call fails."""
    _name, ref = default_branch(repo_root, True)
    try:
        reach = git(repo_root, "rev-list", ref)
        listing = git(repo_root, "for-each-ref", "--format=%(refname) %(objectname)",
                      "refs/heads", "refs/remotes/origin")
    except OSError:
        return {}
    if reach.returncode != 0 or listing.returncode != 0:
        return {}
    refs = {}
    for line in listing.stdout.splitlines():
        name, _, sha = line.partition(" ")
        if name and sha:
            refs[name] = sha
    return {"merged": set(reach.stdout.split()), "refs": refs}


def merge_state(lookup, status, branch, phases):
    """`True` when the batch's tip is reachable from the default branch, `False` when not, `None`
    when it cannot be told. The tip is the local branch, else the same branch on `origin`, else the
    full-SHA `commit` of the last ledger phase that has one. No Git call: `lookup` is
    `git_merge_lookup()`'s result."""
    if status != "done" or not branch or not lookup:
        return None
    refs = lookup["refs"]
    tip = refs.get(f"refs/heads/{branch}") or refs.get(f"refs/remotes/origin/{branch}")
    if not tip:
        for p in reversed(phases):
            commit = p.get("commit") if isinstance(p, dict) else None
            if isinstance(commit, str) and FULL_SHA_RE.match(commit):
                tip = commit
                break
    if not tip:
        return None
    return tip in lookup["merged"]


# ---- site.js -------------------------------------------------------------------------------------

_SCP_REMOTE_RE = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):(?!//)([^/\s]+/[^\s]+?)(?:\.git)?/?$")
_URL_REMOTE_RE = re.compile(r"^(?:https?|ssh|git)://(?:[^@/\s]+@)?([^/:\s]+)(?::\d+)?/([^/\s]+/[^\s]+?)(?:\.git)?/?$")


def commit_url_from_remote(remote):
    """`https://<host>/<owner>/<repo>/commit/` for a `git@host:owner/repo.git`, `https://host/
    owner/repo(.git)` or `ssh://git@host/owner/repo.git` remote, `""` for anything else."""
    remote = (remote or "").strip()
    m = _URL_REMOTE_RE.match(remote) or _SCP_REMOTE_RE.match(remote)
    if not m:
        return ""
    return f"https://{m.group(1)}/{m.group(2)}/commit/"


def build_site_payload(repo_root):
    proc = git(repo_root, "remote", "get-url", "origin")
    remote = proc.stdout.strip() if proc.returncode == 0 else ""
    return {
        "mode": "repo",
        "repo": pathlib.Path(repo_root).name,
        "commitUrl": commit_url_from_remote(remote),
        "pluginVersion": plugin_version(),
    }


# ---- queue entries: todo cards and plan-inbox entries, open and closed ------------------------

def entry_dir(repo_root, kind, state="open"):
    base = pathlib.Path(cfq_lib_paths.plan_dir(repo_root) if kind == "plan" else cfq_lib_paths.todo_dir(repo_root))
    return base / "done" if state == "done" else base


def entry_files(repo_root, kind, state="open"):
    d = entry_dir(repo_root, kind, state)
    return sorted(d.glob("*.md")) if d.is_dir() else []


def entry_title(text):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def closed_text(text):
    """The body of a `## Closed` section (up to the next `## ` heading), `""` without one."""
    lines, collecting, out = text.splitlines(), False, []
    for line in lines:
        if line.startswith("## "):
            if collecting:
                break
            collecting = line[3:].strip().lower() == "closed"
            continue
        if collecting:
            out.append(line)
    return "\n".join(out).strip()


def note_stem(filename):
    name = os.path.basename(str(filename))
    return name[:-3] if name.endswith(".md") else name


def build_link_index(reports):
    """Where each entry came from and where it was parked, built once per sync from every
    batch's `notes`, `parkedPlanEntries` and `fromPlan`: `{"origin": {entry id: {batch, phase}},
    "parkedInto": {entry id: batch}}`. A notes-ledger origin wins over a `parkedPlanEntries`
    one; the first batch (by name) wins on a repeat."""
    origin, parked_into = {}, {}
    for name in sorted(reports):
        data = reports[name]
        for n in data.get("notes") if isinstance(data.get("notes"), list) else []:
            if isinstance(n, dict) and n.get("kind") in ENTRY_KINDS and n.get("file"):
                origin.setdefault(f"{n['kind']}-{note_stem(n['file'])}", {"batch": name, "phase": n.get("phase")})
    for name in sorted(reports):
        data = reports[name]
        for p in report_phases(data):
            for f in p.get("parkedPlanEntries") if isinstance(p.get("parkedPlanEntries"), list) else []:
                if isinstance(f, str) and f:
                    origin.setdefault(f"plan-{note_stem(f)}", {"batch": name, "phase": p.get("phase")})
        for f in data.get("fromPlan") if isinstance(data.get("fromPlan"), list) else []:
            if isinstance(f, str) and f:
                parked_into.setdefault(f"plan-{note_stem(f)}", name)
    return {"origin": origin, "parkedInto": parked_into}


def build_entry_payload(kind, path, state, links):
    text = path.read_text()
    m = ENTRY_FILENAME_RE.match(path.name)
    entry_id = f"{kind}-{path.stem}"
    return {
        "id": entry_id,
        "kind": kind,
        "state": state,
        "date": m.group(1) if m else "",
        "title": entry_title(text),
        "check": any(CHECK_RE.match(line.strip()) for line in text.splitlines()),
        "closed": closed_text(text),
        "origin": links["origin"].get(entry_id),
        "parkedInto": links["parkedInto"].get(entry_id),
        "bodyHtml": cfq_lib_markdown.md_min(text, keep_h1=False),
    }


def entry_summary(full):
    return {k: v for k, v in full.items() if k != "bodyHtml"}


def collect_entries(repo_root, links):
    """Every open entry, then every closed one whose id no open entry already took."""
    fulls, seen = [], set()
    for state in ("open", "done"):
        for kind in ENTRY_KINDS:
            for f in entry_files(repo_root, kind, state):
                e = build_entry_payload(kind, f, state, links)
                if e["id"] not in seen:
                    seen.add(e["id"])
                    fulls.append(e)
    return fulls


# ---- batches ---------------------------------------------------------------------------------------

def batch_status(b):
    """`planning|awaiting_review|planned|blocked|in_progress|done` -- the six values the viewer
    is contracted to show. Precedence: done (archived) > blocked > awaiting_review (a `.review`
    marker) > planning > in_progress > planned; an archived batch never carries any of the other
    flags (`cfq_scan.archived_batch_record`), so checking it first never shadows a real one."""
    if b.get("archived"):
        return "done"
    if b.get("blocked"):
        return "blocked"
    if b.get("review"):
        return "awaiting_review"
    if b.get("planning"):
        return "planning"
    if b.get("inProgress"):
        return "in_progress"
    return "planned"


def load_report(batch_dir):
    f = batch_dir / "report.json"
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def first_paragraph_html(markdown):
    """The whole first paragraph (up to the first blank line) with inline formatting -- not cut
    at the first line break."""
    lines = []
    for line in (markdown or "").splitlines():
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line.strip())
    return cfq_lib_markdown.md_inline(cfq_lib_markdown.esc(" ".join(lines))) if lines else ""


def build_queue_batch_row(b, bd, data, changelog, merge_lookup):
    number, date, title = parse_batch_name(b["name"])
    status = batch_status(b)
    cost = batch_cost(data)
    info = changelog.get(b["name"], {"branch": "", "base": ""})
    records = telemetry_records(data)
    sections = cfq_report.read_batch_context(str(bd))
    return {
        "name": b["name"],
        "number": number,
        "title": title,
        "date": date,
        "status": status,
        "priority": b.get("priority", ""),
        "dependsOn": b.get("dependsOn", []),
        "unknownDeps": b.get("unknownDeps", []),
        "phases": {
            "done": b.get("done", 0),
            "total": b.get("done", 0) + b.get("open", 0) + b.get("skipped", 0),
            "skipped": b.get("skipped", 0),
            "error": b.get("error", 0),
        },
        "goalHtml": first_paragraph_html(sections.get("goal", "")),
        "started": render.jq_alt(data.get("started"), ""),
        "finished": cfq_report.batch_finished(data) if status == "done" else "",
        "cost": {"total": cost["total"], "byModel": cost["byModel"]} if cost else None,
        "deviations": count_deviations(data),
        "flags": {"warn": 0, "info": 0},
        "branch": info["branch"],
        "base": info["base"],
        "merged": merge_state(merge_lookup, status, info["branch"], report_phases(data)),
        "settled": all(is_settled(t) for t in records),
    }


def build_queue_payload(repo_root, rows, entries, base=None, points=None):
    groups = {"inProgress": 0, "planned": 0, "done": 0}
    for r in rows:
        if r["status"] == "in_progress":
            groups["inProgress"] += 1
        elif r["status"] == "done":
            groups["done"] += 1
        else:
            groups["planned"] += 1
    cost = zero_t5()
    for r in rows:
        if r["cost"]:
            cost = add_t5(cost, r["cost"]["total"])
    open_entries = [e for e in entries if e["state"] == "open"]
    return {
        "repo": repo_root,
        "totals": {
            "batches": groups,
            "todos": sum(1 for e in open_entries if e["kind"] == "todo"),
            "planEntries": sum(1 for e in open_entries if e["kind"] == "plan"),
            "deviations": sum(r["deviations"] for r in rows),
            "flags": {
                "warn": sum(r["flags"]["warn"] for r in rows),
                "info": sum(r["flags"]["info"] for r in rows),
            },
            "cost": cost,
        },
        "baselines": base or {},
        "sizes": points or [],
        "batches": sorted(rows, key=lambda r: r["name"]),
        "entries": sorted(entries, key=lambda e: e["id"]),
    }


def time_of(tel):
    tel = tel if isinstance(tel, dict) else {}
    return {
        "from": render.jq_alt(tel.get("from"), ""),
        "until": render.jq_alt(tel.get("until"), ""),
        "wallclock_s": _num(tel.get("wallclock_s")),
    }


def attempt_payload(p):
    tel = p.get("telemetry") if isinstance(p.get("telemetry"), dict) else None
    tel_or_empty = tel or {}
    by_skill = tel_or_empty.get("by_skill") if isinstance(tel_or_empty.get("by_skill"), dict) else {}
    tools = tel_or_empty.get("tools")
    return {
        "status": render.jq_alt(p.get("status"), ""),
        "summary": cfq_report.phase_summary(p),
        "verification": render.jq_alt(p.get("verification"), ""),
        "deviations": render.jq_alt(p.get("deviations"), []),
        "observations": render.jq_alt(p.get("observations"), []),
        "errors": render.jq_alt(p.get("errors"), []),
        "triggers": render.jq_alt(p.get("triggers"), []),
        "question": render.jq_alt(p.get("question"), ""),
        "commit": render.jq_alt(p.get("commit"), ""),
        "reopened": render.jq_alt(p.get("reopened"), ""),
        "diffstat": p.get("diffstat") if isinstance(p.get("diffstat"), dict) else None,
        "filesTouched": render.jq_alt(p.get("filesTouched"), []),
        "parkedPlanEntries": render.jq_alt(p.get("parkedPlanEntries"), []),
        "time": time_of(tel),
        "settled": is_settled(tel),
        "mode": render.jq_alt(tel_or_empty.get("mode"), ""),
        "cost": cost_of(tel),
        "tools": tools if isinstance(tools, dict) else {},
        "skills": {"used": sorted(k for k in by_skill if k != "-")},
    }


def phase_payloads(bd, data):
    """One object per `status.json` entry, in slug order; `[]` for a batch whose status.json is
    missing or unreadable (the sync never fails on it)."""
    try:
        records = phase_state.phases(bd)
    except phase_state.PhaseStateError:
        return []
    attempts = {}
    for p in report_phases(data):
        attempts.setdefault(p.get("phase", ""), []).append(attempt_payload(p))
    phases = []
    for rec in records:
        slug, f = rec["slug"], rec["path"]
        text = f.read_text() if f else ""
        fields = parse_phase_body(text, fallback_title=slug) if f else {}
        num = re.match(r"^(\d+)-", slug)
        phase = {
            "slug": slug,
            "num": int(num.group(1)) if num else None,
            "title": fields.get("title") or slug,
            "size": fields.get("size") or "",
            "state": rec["status"],
            "planHtml": cfq_lib_markdown.md_min(text, keep_h1=False) if f else "",
            "affectedFiles": extract_affected_files(text) if f else [],
            "attempts": attempts.get(slug, []),
            "flags": [],
        }
        if rec["status"] == "skipped":
            phase["skipReason"] = rec["reason"] or ""
        phases.append(phase)
    return phases


def note_payloads(data, entry_states):
    notes = []
    for n in data.get("notes") if isinstance(data.get("notes"), list) else []:
        if not isinstance(n, dict) or n.get("kind") not in ENTRY_KINDS or not n.get("file"):
            continue
        entry_id = f"{n['kind']}-{note_stem(n['file'])}"
        notes.append({
            "kind": n["kind"],
            "id": entry_id,
            "title": render.jq_alt(n.get("title"), ""),
            "at": render.jq_alt(n.get("at"), ""),
            "phase": n.get("phase"),
            "framework": bool(n.get("framework")),
            "state": entry_states.get(entry_id, "missing"),
        })
    return notes


def build_batch_payload(b, bd, data, row, entry_states, entry_titles):
    planning = data.get("planning") if isinstance(data.get("planning"), dict) else None
    security = data.get("security")
    sections = cfq_report.read_batch_context(str(bd))
    return {
        "name": b["name"],
        "status": row["status"],
        "priority": row["priority"],
        "dependsOn": row["dependsOn"],
        "branch": row["branch"],
        "base": row["base"],
        "merged": row["merged"],
        "started": row["started"],
        "finished": row["finished"],
        "outcome": cfq_report.outcome(report_phases(data)),
        "context": {key: cfq_lib_markdown.md_min(body, keep_h1=False) for key, body in sections.items()},
        "planning": None if planning is None else {
            **time_of(planning), "settled": is_settled(planning), "cost": cost_of(planning),
        },
        "phases": phase_payloads(bd, data),
        "cost": batch_cost(data),
        "notes": note_payloads(data, entry_states),
        "fromPlan": [
            {"id": f"plan-{note_stem(f)}", "title": entry_titles.get(f"plan-{note_stem(f)}", "")}
            for f in data.get("fromPlan") if isinstance(f, str)
        ] if isinstance(data.get("fromPlan"), list) else [],
        "closing": data.get("finish") if isinstance(data.get("finish"), dict) else None,
        "security": security[-1] if isinstance(security, list) and security else None,
        "flags": [],
    }


# ---- sync / rebuild -------------------------------------------------------------------------

def sync(repo_root, batch_names=None):
    repo_root = str(pathlib.Path(repo_root).resolve())
    scan = cfq_scan.scan_repo(repo_root)
    if scan is None:
        return {"status": "NO_REPO", "written": [], "unchanged": 0, "removed": []}

    out_dir = data_dir(repo_root)
    removed = []
    written = list(install_shell(reports_dir(repo_root), removed))
    unchanged = 0
    docs = []  # every (key, payload) pair actually considered this sync -- mirrored as-is

    def write(key, payload):
        nonlocal unchanged
        docs.append((key, payload))
        if write_if_changed(out_dir / f"{key}.js", render_data_file(key, payload)):
            written.append(f"{key}.js")
        else:
            unchanged += 1

    dirs = {b["name"]: batch_directory(repo_root, b) for b in scan["batches"]}
    reports = {name: load_report(bd) for name, bd in dirs.items()}
    links = build_link_index(reports)
    entry_fulls = collect_entries(repo_root, links)
    entries = [entry_summary(e) for e in entry_fulls]
    entry_states = {e["id"]: e["state"] for e in entries}
    entry_titles = {e["id"]: e["title"] for e in entries}

    changelog = load_changelog(repo_root)
    merge_lookup = git_merge_lookup(repo_root)
    rows = {
        b["name"]: build_queue_batch_row(b, dirs[b["name"]], reports[b["name"]], changelog, merge_lookup)
        for b in scan["batches"]
    }

    write("site", build_site_payload(repo_root))

    # one payload per batch: built fresh inside the filter (or when no usable data file exists),
    # read back otherwise -- flags and baselines need every batch's attempts either way
    payloads, fresh = {}, set()
    for b in scan["batches"]:
        name = b["name"]
        payload = None
        if batch_names is not None and name not in batch_names:
            payload = read_data_payload(out_dir / "batch" / f"{name}.js")
            if not (isinstance(payload, dict) and isinstance(payload.get("phases"), list) and "flags" in payload):
                payload = None
        if payload is None:
            fresh.add(name)
            payload = build_batch_payload(b, dirs[name], reports[name], rows[name], entry_states, entry_titles)
        payloads[name] = payload

    original = {name: copy.deepcopy(p) for name, p in payloads.items() if name not in fresh}
    points = cfq_flags.size_points(payloads.values())
    base = cfq_flags.baselines(points)
    for name, payload in payloads.items():
        for ph in payload["phases"]:
            ph["flags"] = cfq_flags.phase_flags(ph, base, repo_root)
        payload["flags"] = cfq_flags.batch_flags(payload, base, repo_root)
        rows[name]["flags"] = {
            level: sum(1 for f in payload["flags"] if f["level"] == level) for level in ("warn", "info")
        }

    queue_payload = build_queue_payload(repo_root, list(rows.values()), entries, base, points)
    write("queue", queue_payload)

    for name in sorted(payloads):
        if name in fresh or payloads[name] != original[name]:
            write(f"batch/{name}", payloads[name])

    for e in entry_fulls:
        write(f"entry/{e['id']}", e)

    expected = {f"batch/{name}.js" for name in rows} | {f"entry/{e['id']}.js" for e in entry_fulls}
    removed += cleanup_stale(out_dir, expected)

    result = {
        "status": "OK",
        "written": sorted(written),
        "unchanged": unchanged,
        "removed": sorted(removed),
    }

    report_dir = report_dir_setting(repo_root)
    if report_dir:
        try:
            result["mirror"] = mirror_sync(report_dir, repo_root, queue_payload, docs)
        except Exception as e:  # noqa: BLE001 -- a mirror failure must never fail the repo-local sync
            result["mirror"] = {"status": "ERROR", "detail": str(e)}
    else:
        result["mirror"] = None

    return result


# ---- migrate: removing the old per-batch HTML report (batch 040 phase 05) ----------------------

# Matches a legacy per-batch HTML file's name (older cfq versions wrote it), whichever
# batch-naming era it's from: a numbered batch (`038-2026-09-23-topic.html`) or the
# pre-numbering shape (`2026-09-23-topic.html`) -- never `index.html` itself (neither pattern matches a bare
# `index.html`), and this is only ever glob-matched against a directory's own top level, so it
# never reaches into `assets/`/`data/` either.
LEGACY_BATCH_HTML_RE = re.compile(r"^(\d{3}-.*|\d{4}-\d{2}-\d{2}-.*)\.html$")


def remove_legacy_html(base_dir):
    """Deletes every file directly under `base_dir` (a `reports/` directory, repo-local or a
    `reportDir` mirror) whose name matches `LEGACY_BATCH_HTML_RE` -- the flat `<batch>.html` files
    older cfq versions wrote there. Non-recursive on purpose: `assets/` and `data/`
    are subdirectories, never touched. Returns the removed paths, sorted; `[]` for a directory that
    doesn't exist."""
    if not base_dir.is_dir():
        return []
    removed = []
    for f in sorted(base_dir.glob("*.html")):
        if LEGACY_BATCH_HTML_RE.match(f.name):
            f.unlink()
            removed.append(str(f))
    return removed


def migrate(repo_root, result):
    """The `--migrate` half of `rebuild`: `result` is a just-completed full `sync()`'s own JSON --
    mutated in place, folding every legacy file this removes into that same `removed` list, so the
    caller prints one JSON object either way. Removes this repo's own stale `reports/*.html`, and,
    when `reportDir` is set, the same repo's own mirror directory's stale `*.html` -- resolved via
    `repos.js`, the one place a repo's mirror directory name is recorded, rather than assumed to be
    its basename (a collision suffixes it -- `resolve_mirror_name()`)."""
    removed = set(result["removed"])
    removed.update(remove_legacy_html(reports_dir(repo_root)))

    report_dir = report_dir_setting(repo_root)
    if report_dir:
        existing_repos = read_data_payload(repos_js_path(report_dir))
        mirror_name = None
        if isinstance(existing_repos, list):
            for r in existing_repos:
                if isinstance(r, dict) and r.get("source") == repo_root:
                    mirror_name = r.get("mirror")
                    break
        if mirror_name:
            removed.update(remove_legacy_html(pathlib.Path(report_dir) / mirror_name))

    result["removed"] = sorted(removed)


def cmd_sync(args):
    print(render.dump_json(sync(args.repo_root, args.batch or None)))


def cmd_rebuild(args):
    repo_root = str(pathlib.Path(args.repo_root).resolve())
    result = sync(repo_root, None)
    if args.migrate and result["status"] == "OK":
        migrate(repo_root, result)
    print(render.dump_json(result))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("sync")
    p.add_argument("repo_root")
    p.add_argument("--batch", action="append", default=[])
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("rebuild")
    p.add_argument("repo_root")
    p.add_argument("--migrate", action="store_true")
    p.set_defaults(func=cmd_rebuild)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        print(
            f"usage: {PROG} sync <repo-root> [--batch <name>]... | rebuild <repo-root> [--migrate]",
            file=sys.stderr,
        )
        sys.exit(1)
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
