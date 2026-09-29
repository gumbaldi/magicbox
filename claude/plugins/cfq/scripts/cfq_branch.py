#!/usr/bin/env python3
# Usage: cfq_branch.py plan <repo-root> <batch-dir-name>
#        cfq_branch.py check <repo-root> <branch-name>
"""Computes the branch/batch-identity decision for a batch go-ahead as one JSON object. Read-only
-- never creates or checks out a branch itself; the caller acts on `mode`. New branches use the
batch's own stable directory name directly (`cfq/<batch-directory-name>`) -- no version scanning,
no pseudo-version increment, no identity derived from Git branch history.
`check` resolves and judges one named branch (for a free-text base-branch answer) -- also
read-only, no dispatcher entry of its own since `branch` is already the noun.

On `new`, `base`/`baseRef` are always the chain decision (`_chain_base()`) -- `.dependsOn` never
picks the base. It only gates *when* a batch is selectable (a batch whose dependency is not in
`impl/done/` is already never offered by `ifq`); by the time a branch is cut for a batch, every
dependency is implemented and its work is either in the newest unmerged batch branch or already in
`main`. `baseSource` is `"highestBatch"` (chains onto the highest-numbered unmerged
`cfq/<NNN>-...` branch among `candidates`, so repos that keep `main` frozen and accumulate batches
as a chain don't reset to a stale `main`), `"newerCandidate"` (same base as `"highestBatch"`, but
another unmerged cfq branch not contained in it has a newer commit -- the caller asks which to
use), or `"main"` (bootstrap only: no unmerged numbered `cfq/` branch exists at all). `uncontained`
(`new`-mode only) lists every other unmerged cfq branch not contained in the chosen base,
`{"name", "lastCommit", "newer", "dependency"}` -- `"newerCandidate"` fires when at least one entry
has `newer: true`; older entries are still listed, but only ever surfaced as a warning. `dependency`
is the safety net for the rare case where an unmerged `.dependsOn` branch is missing from the
chosen base (e.g. a non-numbered branch the chain logic never considers, or one abandoned in favor
of a parallel branch): `true` on that entry, appended if the branch wasn't already an `uncontained`
entry on its own -- appending never changes `baseSource`. `uncontained` is `[]` in every mode other
than `new`.

Ported from cfq-branch.sh -- a port, not a redesign: the CLI contract (verbs, argument order, JSON
shapes, exit codes) is the invariant this file preserves. The remote-is-source-of-truth rule
(candidates ranked from `origin`, never local refs) is load-bearing -- see commits
85f424a/d2fec8a/1753599 from batch 015: local-ahead-of-remote is a stop-and-ask, never
auto-resolved.
"""

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors, paths, queue, render  # noqa: E402
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

    # Same "newest commit wins" rule the `new`-mode candidate list applies.
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

    print(render.dump_json({
        "status": "OK", "name": branch_name, "ref": ref, "localOnly": local_only,
        "ahead": ahead, "behind": behind, "lastCommit": last_commit,
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
            "base": None, "candidates": [], "uncontained": [], "remoteChecked": False,
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
        "base": None, "candidates": [], "uncontained": [],
        "remoteChecked": rchecked, "remoteWarning": continue_warning,
        "remoteState": remote_state, "pushable": pushable, "unpushed": unpushed,
        "dirty": dirty, "changelogDirty": changelog_dirty,
    }))


def _collect_candidates(repo, rchecked):
    """(candidate_names, cand_ref, cand_local_only, main_ref) -- `origin/*` is the source of truth
    once remote-checked; local-only branches (no remote counterpart) are still offered, explicitly
    marked. Offline falls back to local branches only, every one implicitly local-only."""
    candidate_names = []
    cand_ref = {}
    cand_local_only = {}

    if rchecked:
        for rb in list_remote_branch_names(repo):
            candidate_names.append(rb)
            cand_ref[rb] = f"refs/remotes/origin/{rb}"
            cand_local_only[rb] = False

        proc = git(repo, "branch", "--format=%(refname:short)", check=False)
        for lb in proc.stdout.splitlines():
            if not lb or lb == "main":
                continue
            if lb not in cand_ref:
                candidate_names.append(lb)
                cand_ref[lb] = f"refs/heads/{lb}"
                cand_local_only[lb] = True

        main_ref = "refs/remotes/origin/main"
    else:
        proc = git(repo, "branch", "--format=%(refname:short)", check=False)
        for lb in proc.stdout.splitlines():
            if not lb or lb == "main":
                continue
            candidate_names.append(lb)
            cand_ref[lb] = f"refs/heads/{lb}"
            cand_local_only[lb] = True

        main_ref = "refs/heads/main"

    return candidate_names, cand_ref, cand_local_only, main_ref


def _highest_cfq_branch(candidate_names):
    """Highest-numbered cfq/<NNN>-... branch among all candidates, found before the aheadOfMain
    filter below so a fully-merged batch branch is never silently dropped -- it's always offered
    as an alternative, per the batch context's "last batch is always offered" rule."""
    highest_name, highest_num = "", -1
    for name in candidate_names:
        if not name.startswith("cfq/"):
            continue
        num = parse_batch_number(name[len("cfq/"):])
        if num is None:
            continue
        if num > highest_num:
            highest_num, highest_name = num, name
    return highest_name


def _unmerged_dependency_branches(repo, batch_name, rchecked, main_ref):
    """Every `.dependsOn` entry whose branch exists (persisted `changelog branch-for`, else
    `cfq/<dep>`; origin first, local when offline) and is not already an ancestor of `main_ref` --
    merged deps contribute nothing, same as no dep at all. Returns `(name, ref)` pairs. `.dependsOn`
    no longer picks a base (see the module docstring) -- this is only the input to the safety net in
    `_emit_new()` that flags an unmerged dependency branch missing from the chosen base."""
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

        if ref_exists(repo, main_ref) and git(
            repo, "merge-base", "--is-ancestor", ref, main_ref, check=False
        ).returncode == 0:
            continue  # dep already merged into main -- contributes nothing

        unmerged.append((name, ref))

    return unmerged


def _chain_base(repo, cand_objs):
    """The only base decision `new` mode makes -- `.dependsOn` never picks the base (see the
    module docstring), it only gates selection. Chains onto the highest-numbered unmerged
    `cfq/<NNN>-...` branch among `cand_objs` instead of resetting to `main`, so repos that keep
    `main` frozen and accumulate cfq batches as a chain don't get a stale base. `cand_objs` is
    already filtered/ranked (descending `lastCommit`, `_lastEpoch` still present -- the caller
    deletes it only after this decision is made, and after the `.dependsOn` safety net that runs
    on top of it). Chain candidates are `cfq/`-prefixed entries whose remainder parses as a batch
    number and whose `aheadOfMain > 0`; a non-`cfq/` branch or a fully-merged cfq branch
    (`aheadOfMain == 0`) is never chosen silently. No chain candidate -> `None` (bootstrap case,
    caller keeps `baseSource: "main"`). Otherwise the highest-numbered chain candidate is the base
    (`baseSource: "highestBatch"`); every other chain candidate not contained in it (`merge-base
    --is-ancestor`) becomes one `uncontained` entry, `dependency: False` (the caller's own
    `.dependsOn` safety net is the only thing that ever sets this `True`), in the same
    (descending-`lastCommit`) order as `cand_objs` -- `newer: true` when its commit epoch is
    strictly greater than the base's, which also flips `baseSource` to `"newerCandidate"` (the
    base itself is unchanged -- it stays the recommendation, the caller asks). An older
    uncontained entry never changes `baseSource`, only adds to the warning list."""
    chain_candidates = [
        c for c in cand_objs
        if c["name"].startswith("cfq/")
        and parse_batch_number(c["name"][len("cfq/"):]) is not None
        and c["aheadOfMain"] > 0
    ]
    if not chain_candidates:
        return None

    base = max(chain_candidates, key=lambda c: parse_batch_number(c["name"][len("cfq/"):]))
    base_source = "highestBatch"

    uncontained = []
    for c in chain_candidates:
        if c is base:
            continue
        contained = git(
            repo, "merge-base", "--is-ancestor", c["ref"], base["ref"], check=False
        ).returncode == 0
        if contained:
            continue
        newer = c["_lastEpoch"] > base["_lastEpoch"]
        uncontained.append({
            "name": c["name"], "lastCommit": c["lastCommit"], "newer": newer, "dependency": False,
        })
        if newer:
            base_source = "newerCandidate"

    return base["name"], base["ref"], base["localOnly"], base_source, uncontained


def _emit_new(repo, batch_name, number, rchecked, dirty, changelog_dirty):
    branch = f"cfq/{batch_name}"

    candidate_names, cand_ref, cand_local_only, main_ref = _collect_candidates(repo, rchecked)
    highest_name = _highest_cfq_branch(candidate_names)

    cand_objs = []
    for name in candidate_names:
        ref = cand_ref[name]
        local_only = cand_local_only[name]

        ahead_of_main = 0
        if ref_exists(repo, ref) and ref_exists(repo, main_ref):
            proc = git(repo, "rev-list", "--count", f"{main_ref}..{ref}", check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                ahead_of_main = int(proc.stdout.strip())

        is_highest = name == highest_name
        if not (ahead_of_main > 0 or is_highest):
            continue

        merged = False
        if ahead_of_main == 0 and ref_exists(repo, main_ref) \
                and git(repo, "merge-base", "--is-ancestor", ref, main_ref, check=False).returncode == 0:
            merged = True

        behind_remote, ahead_remote = 0, 0
        if not local_only and ref_exists(repo, f"refs/heads/{name}"):
            behind_remote, ahead_remote = left_right_counts(repo, ref, f"refs/heads/{name}")

        last_commit = git(repo, "log", "-1", "--format=%cI", ref).stdout.strip()
        last_epoch = int(git(repo, "log", "-1", "--format=%ct", ref).stdout.strip())

        cand_objs.append({
            "name": name, "ref": ref, "aheadOfMain": ahead_of_main,
            "behindRemote": behind_remote, "aheadRemote": ahead_remote,
            "localOnly": local_only, "highestBatch": is_highest,
            "mergedIntoOriginMain": merged, "lastCommit": last_commit, "_lastEpoch": last_epoch,
        })

    # jq's `sort_by(.lastEpoch) | reverse`: stable ascending sort, then the whole list reversed --
    # not a descending sort, ties among equal lastEpoch also flip order. Replicated as two steps
    # rather than one `sort(reverse=True)`, which would leave ties in their original order.
    cand_objs.sort(key=lambda c: c["_lastEpoch"])
    cand_objs.reverse()

    base_name, base_ref, base_local_only, base_source = "main", main_ref, False, "main"
    uncontained = []
    chained = _chain_base(repo, cand_objs)
    if chained is not None:
        base_name, base_ref, base_local_only, base_source, uncontained = chained

    # Safety net: `.dependsOn` never picks the base above, but an unmerged dependency branch
    # missing from the chosen base is still worth flagging explicitly (the rare case where it
    # never became a chain candidate at all -- a non-numbered branch, or one abandoned in favor of
    # a parallel branch). Runs after the base is fixed and before `_lastEpoch` is stripped below,
    # since it still needs `git log` on the base ref for the same "newer" comparison `_chain_base`
    # makes. Appending an entry here never changes `base_source`.
    dependency_branches = _unmerged_dependency_branches(repo, batch_name, rchecked, main_ref)
    if dependency_branches:
        base_epoch = int(git(repo, "log", "-1", "--format=%ct", base_ref).stdout.strip())
    for dep_name, dep_ref in dependency_branches:
        if git(
            repo, "merge-base", "--is-ancestor", dep_ref, base_ref, check=False
        ).returncode == 0:
            continue  # already contained in the chosen base -- nothing to flag
        existing_entry = next((u for u in uncontained if u["name"] == dep_name), None)
        if existing_entry is not None:
            existing_entry["dependency"] = True
        else:
            dep_last_commit = git(repo, "log", "-1", "--format=%cI", dep_ref).stdout.strip()
            dep_epoch = int(git(repo, "log", "-1", "--format=%ct", dep_ref).stdout.strip())
            uncontained.append({
                "name": dep_name, "lastCommit": dep_last_commit,
                "newer": dep_epoch > base_epoch, "dependency": True,
            })

    for c in cand_objs:
        del c["_lastEpoch"]

    base_local_ref = f"refs/heads/{base_name}"
    base_origin_ref = f"refs/remotes/origin/{base_name}"

    # remoteState/pushable/unpushed for the *chosen* base -- same vocabulary and helpers as
    # `continue` mode. Local main ahead of/diverged from origin/main (or a candidate ahead
    # of/diverged from its own origin counterpart) no longer influences candidate selection --
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
        "base": base_name, "baseRef": base_ref, "baseSource": base_source, "candidates": cand_objs,
        "uncontained": uncontained,
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
    p.set_defaults(func=cmd_check)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        errors.die(f"usage: {PROG} plan <repo-root> <batch-dir-name> | check <repo-root> <branch-name>")
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
