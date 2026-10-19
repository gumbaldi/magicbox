#!/usr/bin/env python3
# Usage: cfq_branch.py plan <repo-root> <batch-dir-name>
#        cfq_branch.py check <repo-root> <branch-name> [--batch <batch-dir-name>]
#        cfq_branch.py list <repo-root> [--limit <n>]
"""Computes the branch/batch-identity decision for a batch go-ahead as one JSON object. Read-only
-- never creates or checks out a branch itself; the caller acts on `mode`. New branches use the
batch's own stable directory name directly (`cfq/<batch-directory-name>`) -- no version scanning,
no pseudo-version increment, no identity derived from Git branch history.
`check` resolves and judges one named branch (for a free-text base-branch answer; `--batch` adds
that batch's unmerged `.dependsOn` branches to its `uncontained` list) -- also read-only, no
dispatcher entry of its own since `branch` is already the noun.
`list` renders the `--limit` (default 10) newest branches by commit date, the default branch
appended when it is not among them, as one aligned `listText` for the "pick from list" answer --
also read-only.

On `new`, `base`/`baseRef` are the recommendation (`_recommend()`) -- `.dependsOn` never picks the
base. It only gates *when* a batch is selectable (a batch whose dependency is not in `impl/done/` is
already never offered by `ifq`). The recommended base is always the newest branch. "Newest" among
`cfq/<NNN>-...` batch branches is decided by the batch number, never the commit date: `H` is the
batch branch with the highest number (merged or not). `N` is the non-batch branch with the newest
tip commit (ties: the default branch, then name). `N` is recommended only when its commit is
strictly newer than `H`'s (`baseSource: "newestBranch"`, also when no batch branch exists); in every
other case `H` is (`"highestBatch"`). `options` carries the recommendation and at most two more,
each tagged with a `role`: `"recommended"`; `"highestBatch"` (`H`, offered when `N` is recommended,
even when `N` already contains it); `"newestCommit"` (a lower-numbered batch branch with a newer
commit than `H`'s that neither `H` nor the recommendation contains). Nothing else is ever offered.

The default branch (`defaultBranch`) is `origin/HEAD`, else `main`, else `master`. "Unmerged" means
a batch branch whose tip is not an ancestor of the default branch. `uncontained` (per option, and
top-level for the recommendation) lists the unmerged batch branches the option does not contain,
`{"name", "lastCommit", "dependency"}`, dependency entries first, then batch number descending;
`uncontainedCount` is the full length, the list is capped at `UNCONTAINED_CAP` (5). `dependency` is
the safety net for an unmerged `.dependsOn` branch missing from the option (e.g. a non-numbered
branch): `true` on that entry, appended when it was not an `uncontained` entry on its own. Both
fields are `[]`/`0` in every mode other than `new`, and `options` is `[]` there.

Ported from cfq-branch.sh -- a port, not a redesign: the CLI contract (verbs, argument order, JSON
shapes, exit codes) is the invariant this file preserves. The remote-is-source-of-truth rule
(branches taken from `origin`, never local refs) is load-bearing -- see commits
85f424a/d2fec8a/1753599 from batch 015: local-ahead-of-remote is a stop-and-ask, never
auto-resolved.
"""

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors, paths, queue, render, text  # noqa: E402
from cfq_lib import proc  # noqa: E402
from cfq_lib.proc import cfq_run  # noqa: E402

PROG = "cfq_branch.py"

# New-format batch directory names are <digits>-<YYYY-MM-DD>-<slug> (the number precedes the
# date); legacy names start directly with the date and never match.
NUMBER_RE = re.compile(r"^([0-9]+)-[0-9]{4}-[0-9]{2}-[0-9]{2}-")


def git(repo, *args, check=True):
    """check=True (the default) dies the whole process on a nonzero exit, mirroring what the
    ported shell's `set -eu` did for the same bare call -- several call sites deliberately
    swallow failures (`|| true`, `|| echo 0`, an `if`/`&&` test); those pass check=False and
    handle the result themselves, exactly where the shell version did and nowhere else. Local
    wrapper because this default (and the die-on-failure behaviour) differs from
    `cfq_lib.proc.git`'s own check semantics."""
    result = proc.git(repo, *args)
    if check and result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return result


def ref_exists(repo, ref):
    return git(repo, "rev-parse", "--verify", "-q", ref, check=False).returncode == 0


def is_remote_checked(repo):
    """Best-effort remote check: no origin, or fetch fails (offline/sandboxed) -> False, and every
    path below behaves exactly as before this was added."""
    if git(repo, "remote", "get-url", "origin", check=False).returncode != 0:
        return False
    return git(repo, "fetch", "-q", "origin", check=False).returncode == 0


def list_remote_branch_names(repo):
    """Short names of every `origin/*` branch, `origin/HEAD` dropped, `origin/` prefix stripped."""
    proc = git(repo, "branch", "-r", "--format=%(refname:short)", check=False)
    names = []
    for line in proc.stdout.splitlines():
        if line.startswith("origin/"):
            name = line[len("origin/"):]
            if name != "HEAD":
                names.append(name)
    return names


def classify_remote_state(ahead, behind):
    """Classifies a bidirectional ahead/behind count pair into the shared remoteState vocabulary --
    used by both `continue` mode and `new` mode so a caller never has to branch on `mode` to read
    it."""
    if ahead > 0 and behind > 0:
        return "diverged"
    if ahead > 0:
        return "ahead"
    if behind > 0:
        return "behind"
    return "synced"


def left_right_counts(repo, left_ref, right_ref):
    """(behind, ahead) via `rev-list --left-right --count <left>...<right>`."""
    out = git(repo, "rev-list", "--left-right", "--count", f"{left_ref}...{right_ref}").stdout
    behind_s, ahead_s = out.split()
    return int(behind_s), int(ahead_s)


def list_unpushed_commits(repo, from_ref, to_ref):
    """"<hash> <subject>" lines for commits reachable from to_ref but not from_ref."""
    proc = git(repo, "log", "--format=%h %s", f"{from_ref}..{to_ref}", check=False)
    return [line for line in proc.stdout.splitlines() if line]


def parse_batch_number(name):
    m = NUMBER_RE.match(name)
    return int(m.group(1)) if m else None


def compute_dirty(repo):
    """(dirty, changelogDirty) from `git status --porcelain`: the changelogFile path (if set) and
    anything under `.claude/cfq/` never count as `dirty` -- the queue's own untracked/reservation
    state is expected, not something that should block a checkout. `changelogDirty` is true only
    when the changelog path itself is the (or a) modified entry. `--no-optional-locks` keeps this
    call from refreshing/rewriting `.git/index` as a side effect -- `branch plan` is read-only and
    `cfq_ifq_preflight.py`'s determinism test asserts nothing under the repo is ever touched.
    `--untracked-files=all` keeps git from collapsing an entirely-untracked `.claude/` subtree to
    one `?? .claude/` line, which would not match the `.claude/cfq/` prefix check below and would
    misreport a fresh queue as `dirty`."""
    changelog_rel = proc.settings_get(repo, "changelogFile")
    dirty = False
    changelog_dirty = False
    for line in git(
        repo, "--no-optional-locks", "status", "--porcelain", "--untracked-files=all"
    ).stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if changelog_rel and path == changelog_rel:
            changelog_dirty = True
            continue
        if path.startswith(".claude/cfq/"):
            continue
        dirty = True
    return dirty, changelog_dirty


def find_suffix_match(repo, slug):
    """Highest-priority (alphabetically first) local-or-remote branch whose name ends in
    `-<slug>` -- the fallback used when the changelog doesn't (yet, or any more) know a branch for
    this batch."""
    proc = git(repo, "branch", "-a", "--format=%(refname:short)", check=False)
    names = set()
    for line in proc.stdout.splitlines():
        if not line:
            continue
        names.add(line[len("origin/"):] if line.startswith("origin/") else line)
    pattern = re.compile("-" + re.escape(slug) + "$")
    matches = sorted(n for n in names if pattern.search(n))
    return matches[0] if matches else ""



# ---- branch universe ---------------------------------------------------------------------------

UNCONTAINED_CAP = 5
REF_FORMAT = "%(refname) %(committerdate:unix) %(committerdate:iso-strict)"
ORIGIN_PREFIX = "refs/remotes/origin/"
HEADS_PREFIX = "refs/heads/"


def is_ancestor(repo, ancestor_ref, descendant_ref):
    return git(
        repo, "merge-base", "--is-ancestor", ancestor_ref, descendant_ref, check=False
    ).returncode == 0


def _is_batch(name):
    return name.startswith("cfq/") and parse_batch_number(name[len("cfq/"):]) is not None


def _batch_number(name):
    return parse_batch_number(name[len("cfq/"):]) if name.startswith("cfq/") else None


def default_branch(repo, rchecked):
    """(name, ref) of the default branch: `origin/HEAD`, else `main`, else `master` -- looked up on
    `origin` once remote-checked, then (and when offline) among the local branches, falling back to
    `main`. `ref` is the `origin` ref when remote-checked and present, else the local ref."""
    if rchecked:
        proc = git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False)
        name = proc.stdout.strip() if proc.returncode == 0 else ""
        if name.startswith("origin/"):
            name = name[len("origin/"):]
        if not name:
            name = next(
                (n for n in ("main", "master") if ref_exists(repo, ORIGIN_PREFIX + n)), ""
            )
        if name:
            origin_ref = ORIGIN_PREFIX + name
            return name, origin_ref if ref_exists(repo, origin_ref) else HEADS_PREFIX + name
    for name in ("main", "master"):
        if ref_exists(repo, HEADS_PREFIX + name):
            return name, HEADS_PREFIX + name
    return "main", HEADS_PREFIX + "main"


def _collect_branches(repo, rchecked):
    """Every branch of the universe as `{"name", "ref", "localOnly", "epoch", "lastCommit"}`, the
    default branch included. `origin/*` is the source of truth once remote-checked (`origin/HEAD`
    dropped); local branches without an `origin` counterpart are still listed, `localOnly: True`.
    Offline: every local branch, all `localOnly: True`. One `for-each-ref` call supplies all."""
    out = git(
        repo, "for-each-ref", f"--format={REF_FORMAT}", "refs/remotes/origin", "refs/heads",
        check=False,
    ).stdout
    remote, local = {}, {}
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        ref, epoch, iso = parts
        if ref.startswith(ORIGIN_PREFIX):
            name = ref[len(ORIGIN_PREFIX):]
            if name != "HEAD":
                remote[name] = (ref, int(epoch), iso)
        elif ref.startswith(HEADS_PREFIX):
            local[ref[len(HEADS_PREFIX):]] = (ref, int(epoch), iso)

    branches = []
    if rchecked:
        for name, (ref, epoch, iso) in remote.items():
            branches.append({"name": name, "ref": ref, "localOnly": False,
                             "epoch": epoch, "lastCommit": iso})
        for name, (ref, epoch, iso) in local.items():
            if name not in remote:
                branches.append({"name": name, "ref": ref, "localOnly": True,
                                 "epoch": epoch, "lastCommit": iso})
    else:
        for name, (ref, epoch, iso) in local.items():
            branches.append({"name": name, "ref": ref, "localOnly": True,
                             "epoch": epoch, "lastCommit": iso})
    branches.sort(key=lambda b: b["name"])
    return branches


def _not_merged_refs(repo, ref):
    """Full ref names of every branch that is not an ancestor of `ref`, in one `for-each-ref` call;
    `None` when `ref` itself does not exist."""
    if not ref_exists(repo, ref):
        return None
    out = git(
        repo, "for-each-ref", f"--no-merged={ref}", "--format=%(refname)",
        "refs/remotes/origin", "refs/heads", check=False,
    ).stdout
    return set(out.split())


def _unmerged_cfq(repo, branches, default_ref):
    """Names of the batch branches whose own ref is not an ancestor of `default_ref`; a missing
    `default_ref` makes every batch branch unmerged."""
    batch = [b for b in branches if _is_batch(b["name"])]
    not_merged = _not_merged_refs(repo, default_ref)
    if not_merged is None:
        return [b["name"] for b in batch]
    return [b["name"] for b in batch if b["ref"] in not_merged]


def _uncontained(repo, target, branches, unmerged, dependency_branches):
    """`(entries, count)`: every unmerged batch branch other than `target` that `target["ref"]`
    does not contain, plus the `.dependsOn` safety net -- an unmerged dependency branch missing
    from `target` sets `dependency: True` on its entry or appends one. Order: dependency entries
    first, then batch number descending, then name. `count` is the full length, `entries` the
    first `UNCONTAINED_CAP`."""
    by_name = {b["name"]: b for b in branches}
    not_merged = _not_merged_refs(repo, target["ref"])
    entries = {}
    for name in unmerged:
        b = by_name.get(name)
        if b is None or name == target["name"]:
            continue
        if not_merged is None or b["ref"] in not_merged:
            entries[name] = {"name": name, "lastCommit": b["lastCommit"], "dependency": False}
    for dep_name, dep_ref in dependency_branches:
        if dep_name == target["name"] or is_ancestor(repo, dep_ref, target["ref"]):
            continue
        if dep_name in entries:
            entries[dep_name]["dependency"] = True
        else:
            last_commit = git(repo, "log", "-1", "--format=%cI", dep_ref).stdout.strip()
            entries[dep_name] = {"name": dep_name, "lastCommit": last_commit, "dependency": True}

    def order(e):
        number = _batch_number(e["name"])
        return (not e["dependency"], -(number if number is not None else -1), e["name"])

    ordered = sorted(entries.values(), key=order)
    return ordered[:UNCONTAINED_CAP], len(ordered)


def _recommend(repo, branches, default_name=None):
    """`([(branch, role), ...], baseSource)` -- the ordered option list, at most three entries (see
    the module docstring for the rule). Empty list when there is no branch at all."""
    if default_name is None:
        default_name, _ = default_branch(repo, any(not b["localOnly"] for b in branches))
    batch = [b for b in branches if _is_batch(b["name"])]
    other = [b for b in branches if not _is_batch(b["name"])]
    highest = max(batch, key=lambda b: (_batch_number(b["name"]), b["epoch"])) if batch else None
    newest = min(
        other, key=lambda b: (-b["epoch"], b["name"] != default_name, b["name"])
    ) if other else None

    if newest is not None and (highest is None or newest["epoch"] > highest["epoch"]):
        recommended, source = newest, "newestBranch"
    elif highest is not None:
        recommended, source = highest, "highestBatch"
    else:
        return [], "newestBranch"

    options = [(recommended, "recommended")]
    if recommended is newest and highest is not None:
        options.append((highest, "highestBatch"))
    if highest is not None:
        newer = [
            b for b in batch
            if b is not highest and b["epoch"] > highest["epoch"]
            and not is_ancestor(repo, b["ref"], highest["ref"])
            and not is_ancestor(repo, b["ref"], recommended["ref"])
        ]
        if newer:
            options.append((max(newer, key=lambda b: (b["epoch"], b["name"])), "newestCommit"))
    return options, source


# ---- list ---------------------------------------------------------------------------------------

def cmd_list(args):
    repo = args.repo
    if git(repo, "rev-parse", "--show-toplevel", check=False).returncode != 0:
        print(render.dump_json({"status": "NO_REPO", "repo": {"root": repo}}))
        return

    rchecked = is_remote_checked(repo)
    default_name, default_ref = default_branch(repo, rchecked)
    branches = _collect_branches(repo, rchecked)
    unmerged = _unmerged_cfq(repo, branches, default_ref)
    picked, _ = _recommend(repo, branches, default_name)
    recommended = picked[0][0]["name"] if picked else default_name

    def newest_first(b):
        number = _batch_number(b["name"]) if _is_batch(b["name"]) else None
        return (-b["epoch"], -(number if number is not None else -1), b["name"])

    kept = sorted(branches, key=newest_first)[:max(args.limit, 0)]
    shown = len(kept)
    if default_name not in (b["name"] for b in kept):
        kept += [b for b in branches if b["name"] == default_name]

    rows = []
    for i, b in enumerate(kept, 1):
        notes = []
        if b["name"] == recommended:
            notes.append("recommended")
        if b["name"] == default_name:
            notes.append("default")
        if b["localOnly"]:
            notes.append("local only")
        _, missing = _uncontained(repo, b, branches, unmerged, [])
        if missing:
            notes.append(f"missing {missing} cfq branch" + ("es" if missing > 1 else ""))
        rows.append([str(i), b["name"], b["lastCommit"][:10], " · ".join(notes)])

    header = f"BRANCHES · newest {shown} of {len(branches)}"
    lines = [header] + text.table(rows, aligns=["r"])
    print(render.dump_json({
        "status": "OK", "defaultBranch": default_name, "recommended": recommended,
        "total": len(branches), "names": [b["name"] for b in kept],
        "listText": "\n".join(lines),
    }))


# ---- check --------------------------------------------------------------------------------------

def cmd_check(args):
    repo = args.repo
    branch_name = args.branch_name
    rchecked = is_remote_checked(repo)

    origin_ref = f"refs/remotes/origin/{branch_name}"
    local_ref = f"refs/heads/{branch_name}"
    origin_exists = ref_exists(repo, origin_ref)
    local_exists = ref_exists(repo, local_ref)

    if not origin_exists and not local_exists:
        print(render.dump_json({
            "status": "UNRESOLVED", "name": branch_name, "ref": None, "remoteChecked": rchecked,
        }))
        return

    if origin_exists:
        ref, local_only = origin_ref, False
    else:
        ref, local_only = local_ref, True

    ahead, behind = 0, 0
    if origin_exists and local_exists:
        behind, ahead = left_right_counts(repo, origin_ref, local_ref)

    last_commit = git(repo, "log", "-1", "--format=%cI", ref).stdout.strip()
    ref_epoch = int(git(repo, "log", "-1", "--format=%ct", ref).stdout.strip())

    # The newest branch on `origin` that has a newer commit than the checked one.
    newer_name, newer_epoch = "", 0
    for rb in list_remote_branch_names(repo):
        proc = git(repo, "log", "-1", "--format=%ct", f"refs/remotes/origin/{rb}", check=False)
        if proc.returncode != 0:
            continue
        epoch = int(proc.stdout.strip())
        if epoch > ref_epoch and epoch > newer_epoch:
            newer_epoch, newer_name = epoch, rb

    newer_candidate = None
    if newer_name:
        newer_iso = git(repo, "log", "-1", "--format=%cI", f"refs/remotes/origin/{newer_name}").stdout.strip()
        newer_candidate = {"name": newer_name, "lastCommit": newer_iso}

    default_name, default_ref = default_branch(repo, rchecked)
    branches = _collect_branches(repo, rchecked)
    unmerged = _unmerged_cfq(repo, branches, default_ref)
    dependency_branches = []
    if args.batch:
        dependency_branches = _unmerged_dependency_branches(repo, args.batch, rchecked, default_ref)
    uncontained, uncontained_count = _uncontained(
        repo, {"name": branch_name, "ref": ref}, branches, unmerged, dependency_branches
    )

    print(render.dump_json({
        "status": "OK", "name": branch_name, "ref": ref, "localOnly": local_only,
        "ahead": ahead, "behind": behind, "lastCommit": last_commit,
        "isCfq": _is_batch(branch_name), "isDefault": branch_name == default_name,
        "uncontained": uncontained, "uncontainedCount": uncontained_count,
        "newerCandidate": newer_candidate, "remoteChecked": rchecked,
    }))




# ---- plan ---------------------------------------------------------------------------------------

def cmd_plan(args):
    repo = args.repo
    batch_name = args.batch

    if git(repo, "rev-parse", "--show-toplevel", check=False).returncode != 0:
        print(render.dump_json({"status": "NO_REPO", "repo": {"root": repo}}))
        return

    rchecked = is_remote_checked(repo)

    number = parse_batch_number(batch_name)
    slug = re.sub(r"^[0-9]+-[0-9]{4}-[0-9]{2}-[0-9]{2}-", "", batch_name)
    slug = re.sub(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-", "", slug)

    branch_per_batch = cfq_run("settings", "get", "branchPerBatch").stdout.strip()
    if branch_per_batch == "false":
        print(render.dump_json({
            "mode": "off", "batch": batch_name, "batchNumber": number, "branch": None,
            "base": None, "options": [], "uncontained": [], "uncontainedCount": 0,
            "remoteChecked": False,
            "remoteWarning": None, "dirty": False, "changelogDirty": False,
        }))
        return

    dirty, changelog_dirty = compute_dirty(repo)

    # Prefer the branch already persisted in the CFQ changelog for this exact batch --
    # authoritative, since it is the branch that was actually checked out at init time -- but only
    # once it's confirmed to still exist; a deleted branch falls through to the suffix match below
    # rather than being handed to the caller as an unresolvable "continue".
    existing = cfq_run("changelog", "branch-for", repo, batch_name).stdout.strip()
    if existing and not ref_exists(repo, f"refs/heads/{existing}") \
            and not ref_exists(repo, f"refs/remotes/origin/{existing}"):
        existing = ""
    if not existing:
        existing = find_suffix_match(repo, slug)

    if existing:
        _emit_continue(repo, batch_name, number, existing, rchecked, dirty, changelog_dirty)
        return

    _emit_new(repo, batch_name, number, rchecked, dirty, changelog_dirty)



def _emit_continue(repo, batch_name, number, existing, rchecked, dirty, changelog_dirty):
    continue_warning = None
    remote_state = "unknown"
    pushable = False
    unpushed = []

    if rchecked and ref_exists(repo, f"refs/heads/{existing}") \
            and ref_exists(repo, f"refs/remotes/origin/{existing}"):
        behind, ahead = left_right_counts(
            repo, f"refs/remotes/origin/{existing}", f"refs/heads/{existing}"
        )
        remote_state = classify_remote_state(ahead, behind)

        if remote_state == "behind":
            # `update-ref` can't move the ref of the branch that is currently checked out --
            # fall back to a fast-forward merge there, and never mutate anything against a dirty
            # tree.
            checked_out = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip()
            if checked_out != existing:
                git(repo, "update-ref", f"refs/heads/{existing}", f"refs/remotes/origin/{existing}")
            elif not dirty:
                git(repo, "merge", "-q", "--ff-only", f"refs/remotes/origin/{existing}")
            else:
                continue_warning = (
                    f"local {existing} is behind origin/{existing} but the working tree is "
                    "dirty — resolve before continuing"
                )
        elif remote_state == "ahead":
            pushable = True
            unpushed = list_unpushed_commits(
                repo, f"refs/remotes/origin/{existing}", f"refs/heads/{existing}"
            )
        elif remote_state == "diverged":
            continue_warning = (
                f"local {existing} is {ahead} commit(s) ahead of and {behind} commit(s) behind "
                f"origin/{existing} — a push would be rejected"
            )

    print(render.dump_json({
        "mode": "continue", "batch": batch_name, "batchNumber": number, "branch": existing,
        "base": None, "options": [], "uncontained": [], "uncontainedCount": 0,
        "remoteChecked": rchecked, "remoteWarning": continue_warning,
        "remoteState": remote_state, "pushable": pushable, "unpushed": unpushed,
        "dirty": dirty, "changelogDirty": changelog_dirty,
    }))

def _unmerged_dependency_branches(repo, batch_name, rchecked, default_ref):
    """Every `.dependsOn` entry whose branch exists (persisted `changelog branch-for`, else
    `cfq/<dep>`; origin first, local when offline) and is not already an ancestor of `default_ref` --
    merged deps contribute nothing, same as no dep at all. Returns `(name, ref)` pairs. `.dependsOn`
    no longer picks a base (see the module docstring) -- this is only the input to the safety net in
    `_uncontained()` that flags an unmerged dependency branch missing from an option."""
    batch_dir = pathlib.Path(paths.impl_dir(repo)) / batch_name
    deps = queue.read_depends(batch_dir)

    unmerged = []
    for dep in deps:
        name = cfq_run("changelog", "branch-for", repo, dep).stdout.strip()
        if not name:
            name = f"cfq/{dep}"
        origin_ref = f"refs/remotes/origin/{name}"
        local_ref = f"refs/heads/{name}"
        if rchecked and ref_exists(repo, origin_ref):
            ref = origin_ref
        elif ref_exists(repo, local_ref):
            ref = local_ref
        else:
            continue  # dep names no branch that exists anywhere -- ignored

        if ref_exists(repo, default_ref) and git(
            repo, "merge-base", "--is-ancestor", ref, default_ref, check=False
        ).returncode == 0:
            continue  # dep already merged into the default branch -- contributes nothing

        unmerged.append((name, ref))

    return unmerged


def _emit_new(repo, batch_name, number, rchecked, dirty, changelog_dirty):
    branch = f"cfq/{batch_name}"

    default_name, default_ref = default_branch(repo, rchecked)
    branches = _collect_branches(repo, rchecked)
    unmerged = _unmerged_cfq(repo, branches, default_ref)
    # `.dependsOn` never picks the base, but an unmerged dependency branch missing from an option
    # is still worth flagging explicitly -- `_uncontained()` folds it in as `dependency: true`.
    dependency_branches = _unmerged_dependency_branches(repo, batch_name, rchecked, default_ref)

    picked, base_source = _recommend(repo, branches, default_name)
    if not picked:  # no branch at all (e.g. a repo without a first commit) -- the default branch
        picked = [({
            "name": default_name, "ref": default_ref, "epoch": 0, "lastCommit": "",
            "localOnly": not default_ref.startswith(ORIGIN_PREFIX),
        }, "recommended")]
    base = picked[0][0]
    base_name, base_ref, base_local_only = base["name"], base["ref"], base["localOnly"]

    options = []
    for b, role in picked:
        behind_remote, ahead_remote = 0, 0
        if not b["localOnly"] and ref_exists(repo, HEADS_PREFIX + b["name"]):
            behind_remote, ahead_remote = left_right_counts(repo, b["ref"], HEADS_PREFIX + b["name"])
        entries, count = _uncontained(repo, b, branches, unmerged, dependency_branches)
        options.append({
            "name": b["name"], "ref": b["ref"], "role": role, "isCfq": _is_batch(b["name"]),
            "isDefault": b["name"] == default_name, "localOnly": b["localOnly"],
            "lastCommit": b["lastCommit"], "behindRemote": behind_remote,
            "aheadRemote": ahead_remote,
            "containedInBase": b is base or is_ancestor(repo, b["ref"], base_ref),
            "uncontained": entries, "uncontainedCount": count,
        })

    base_local_ref = f"refs/heads/{base_name}"
    base_origin_ref = f"refs/remotes/origin/{base_name}"

    # remoteState/pushable/unpushed for the *chosen* base -- same vocabulary and helpers as
    # `continue` mode. Local main ahead of/diverged from origin/main (or a branch ahead
    # of/diverged from its own origin counterpart) no longer influences branch selection --
    # `baseRef` already points into `refs/remotes/` -- but is still a real state worth a push
    # offer.
    remote_state = "unknown"
    pushable = False
    unpushed = []
    new_warning = None
    if rchecked:
        if base_local_only:
            if ref_exists(repo, base_local_ref):
                remote_state = "ahead"
                pushable = True
                proc = git(repo, "log", "--format=%h %s", base_local_ref, check=False)
                unpushed = [line for line in proc.stdout.splitlines() if line]
        elif ref_exists(repo, base_local_ref) and ref_exists(repo, base_origin_ref):
            behind, ahead = left_right_counts(repo, base_origin_ref, base_local_ref)
            remote_state = classify_remote_state(ahead, behind)
            if remote_state == "ahead":
                pushable = True
                unpushed = list_unpushed_commits(repo, base_origin_ref, base_local_ref)
                new_warning = (
                    f"local {base_name} is {ahead} commit(s) ahead of origin/{base_name} — a "
                    "push before continuing would include them"
                )
            elif remote_state == "diverged":
                new_warning = (
                    f"local {base_name} has diverged from origin/{base_name} — resolve before "
                    "basing new work on it"
                )

    print(render.dump_json({
        "mode": "new", "batch": batch_name, "batchNumber": number, "branch": branch,
        "defaultBranch": default_name, "base": base_name, "baseRef": base_ref,
        "baseSource": base_source, "options": options,
        "uncontained": options[0]["uncontained"], "uncontainedCount": options[0]["uncontainedCount"],
        "remoteChecked": rchecked, "remoteWarning": new_warning,
        "remoteState": remote_state, "pushable": pushable, "unpushed": unpushed,
        "dirty": dirty, "changelogDirty": changelog_dirty,
    }))



# ---- argument parsing -----------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("plan")
    p.add_argument("repo")
    p.add_argument("batch")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("check")
    p.add_argument("repo")
    p.add_argument("branch_name")
    p.add_argument("--batch")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("list")
    p.add_argument("repo")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_list)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(f"usage: {PROG} plan <repo-root> <batch-dir-name> | check <repo-root> <branch-name> [--batch <batch-dir-name>] | list <repo-root> [--limit <n>]")
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
