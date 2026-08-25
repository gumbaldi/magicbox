#!/usr/bin/env bash
# Self-test for scripts/cfq-branch.sh. No framework, no fixtures beyond what's built here — just
# `bash tests/test-branch.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
branch_sh="$repo_root/scripts/cfq-branch.sh"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

repo="$tmp/repo"
mkdir -p "$repo"
git init -q -b main "$repo"
git -C "$repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init

run() { HOME="$home" bash "$branch_sh" plan "$repo" "$1"; }

# --- no existing branch, legacy-style batch dir -> new, branch is cfq/<batch-dir>, base main ---
out=$(run "2026-01-01-mytopic")
printf '%s' "$out" | jq -e . >/dev/null || { echo "FAIL: not valid JSON: $out"; exit 1; }
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "cfq/2026-01-01-mytopic" ] || { echo "FAIL: branch -> $out"; exit 1; }
[ "$(jq -r '.batch' <<<"$out")" = "2026-01-01-mytopic" ] || { echo "FAIL: batch -> $out"; exit 1; }
[ "$(jq -r '.batchNumber' <<<"$out")" = "null" ] || { echo "FAIL: legacy batchNumber should be null -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "main" ] || { echo "FAIL: base -> $out"; exit 1; }
[ "$(jq -c '.candidates' <<<"$out")" = "[]" ] || { echo "FAIL: candidates -> $out"; exit 1; }

# --- numbered batch dir -> new, branch is cfq/<numbered-dir>, batchNumber extracted ---
out=$(run "001-2026-01-01-numbered")
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: numbered mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "cfq/001-2026-01-01-numbered" ] || { echo "FAIL: numbered branch -> $out"; exit 1; }
[ "$(jq -r '.batchNumber' <<<"$out")" = "1" ] || { echo "FAIL: numbered batchNumber -> $out"; exit 1; }

# --- stray vX.Y branches in the repo never influence the new branch name (no version scanning) ---
git -C "$repo" branch v0.9-a
git -C "$repo" branch v0.10-b
git -C "$repo" branch v0.48-x
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.branch' <<<"$out")" = "cfq/2026-01-01-mytopic" ] || { echo "FAIL: stray vX.Y branches affected the new branch -> $out"; exit 1; }
jq -e '.candidates | index("v0.9-a") == null and index("v0.10-b") == null and index("v0.48-x") == null' <<<"$out" >/dev/null \
  || { echo "FAIL: stray non-ahead vX.Y branches leaked into candidates -> $out"; exit 1; }

# --- existing legacy vX.Y-<slug> branch -> continue, resumable without special-casing ---
git -C "$repo" branch v0.3-mytopic
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: continue mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "v0.3-mytopic" ] || { echo "FAIL: continue branch -> $out"; exit 1; }
git -C "$repo" branch -q -D v0.3-mytopic

# --- remote-only branch for the slug -> same continue result ---
remote="$tmp/remote.git"
git init -q --bare "$remote"
git -C "$repo" remote add origin "$remote"
git -C "$repo" push -q origin v0.48-x:v0.3-mytopic
git -C "$repo" fetch -q origin
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: remote continue mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "v0.3-mytopic" ] || { echo "FAIL: remote continue branch -> $out"; exit 1; }

# --- a branch persisted in the changelog for this batch wins over the suffix-match fallback ---
changelog_repo="$tmp/changelog-repo"
mkdir -p "$changelog_repo"
git init -q -b main "$changelog_repo"
git -C "$changelog_repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init
HOME="$home" bash "$repo_root/scripts/cfq-changelog.sh" init "$changelog_repo" "cfq/2026-02-01-persisted" main "2026-02-01-persisted"
git -C "$changelog_repo" branch "cfq/2026-02-01-persisted"
git -C "$changelog_repo" branch "some-other-branch-ending-persisted"
out=$(HOME="$home" bash "$branch_sh" plan "$changelog_repo" "2026-02-01-persisted")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: persisted-branch continue mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "cfq/2026-02-01-persisted" ] || { echo "FAIL: persisted branch not preferred -> $out"; exit 1; }

# --- persisted branch since deleted -> falls through to the suffix-match fallback, not a dangling continue ---
git -C "$changelog_repo" branch -q -D "cfq/2026-02-01-persisted"
out=$(HOME="$home" bash "$branch_sh" plan "$changelog_repo" "2026-02-01-persisted")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: deleted-persisted-branch fallback mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "some-other-branch-ending-persisted" ] || { echo "FAIL: deleted-persisted-branch fallback did not use suffix match -> $out"; exit 1; }

# --- branchPerBatch=false -> off (no env var for this key, set it via settings.json) ---
mkdir -p "$home/.claude/code-for-queue"
echo '{"branchPerBatch": false}' > "$home/.claude/code-for-queue/settings.json"
out=$(run "2026-01-01-mytopic")
[ "$(jq -r '.mode' <<<"$out")" = "off" ] || { echo "FAIL: off mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "null" ] || { echo "FAIL: off branch should be null -> $out"; exit 1; }
rm "$home/.claude/code-for-queue/settings.json"

# --- a branch ahead of main appears in candidates, base is null ---
git -C "$repo" checkout -q -b v0.50-ahead
git -C "$repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m ahead
git -C "$repo" checkout -q main
out=$(run "2026-01-02-newtopic")
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: candidates-case mode -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "null" ] || { echo "FAIL: base should be null with candidates -> $out"; exit 1; }
jq -e '.candidates | index("v0.50-ahead") != null' <<<"$out" >/dev/null \
  || { echo "FAIL: v0.50-ahead should be in candidates -> $out"; exit 1; }

# --- (a) local main purely behind origin/main -> fast-forwarded, base still "main" ---
ff_repo="$tmp/ff-repo"
mkdir -p "$ff_repo"
git init -q -b main "$ff_repo"
git -C "$ff_repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init
ff_remote="$tmp/ff-remote.git"
git init -q --bare -b main "$ff_remote"
git -C "$ff_repo" remote add origin "$ff_remote"
git -C "$ff_repo" push -q origin main
git -C "$ff_repo" checkout -q -b topic
ff_clone="$tmp/ff-clone"
git clone -q "$ff_remote" "$ff_clone"
git -C "$ff_clone" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m remote-ahead
git -C "$ff_clone" push -q origin main
out=$(HOME="$home" bash "$branch_sh" plan "$ff_repo" "2026-03-01-fftopic")
[ "$(jq -r '.remoteChecked' <<<"$out")" = "true" ] || { echo "FAIL: ff remoteChecked -> $out"; exit 1; }
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: ff mode -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "main" ] || { echo "FAIL: ff base -> $out"; exit 1; }
[ "$(jq -r '.remoteWarning' <<<"$out")" = "null" ] || { echo "FAIL: ff remoteWarning -> $out"; exit 1; }
[ "$(git -C "$ff_repo" rev-parse refs/heads/main)" = "$(git -C "$ff_repo" rev-parse refs/remotes/origin/main)" ] \
  || { echo "FAIL: local main was not fast-forwarded"; exit 1; }

# --- (b) no origin configured at all -> behaves exactly as before (remoteChecked false) ---
noorigin_repo="$tmp/no-origin-repo"
mkdir -p "$noorigin_repo"
git init -q -b main "$noorigin_repo"
git -C "$noorigin_repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init
out=$(HOME="$home" bash "$branch_sh" plan "$noorigin_repo" "2026-03-02-nooriginit")
[ "$(jq -r '.remoteChecked' <<<"$out")" = "false" ] || { echo "FAIL: no-origin remoteChecked -> $out"; exit 1; }
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: no-origin mode -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "main" ] || { echo "FAIL: no-origin base -> $out"; exit 1; }
[ "$(jq -r '.remoteWarning' <<<"$out")" = "null" ] || { echo "FAIL: no-origin remoteWarning -> $out"; exit 1; }

# --- (c) local main ahead of origin/main with an unpushed commit -> stop, never auto-resolve ---
ahead_repo="$tmp/ahead-repo"
mkdir -p "$ahead_repo"
git init -q -b main "$ahead_repo"
git -C "$ahead_repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init
ahead_remote="$tmp/ahead-remote.git"
git init -q --bare "$ahead_remote"
git -C "$ahead_repo" remote add origin "$ahead_remote"
git -C "$ahead_repo" push -q origin main
git -C "$ahead_repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m unpushed
out=$(HOME="$home" bash "$branch_sh" plan "$ahead_repo" "2026-03-03-aheadtopic")
[ "$(jq -r '.remoteChecked' <<<"$out")" = "true" ] || { echo "FAIL: ahead remoteChecked -> $out"; exit 1; }
[ "$(jq -r '.mode' <<<"$out")" = "new" ] || { echo "FAIL: ahead mode -> $out"; exit 1; }
[ "$(jq -r '.base' <<<"$out")" = "null" ] || { echo "FAIL: ahead base should be null -> $out"; exit 1; }
jq -e '.candidates | index("main") != null' <<<"$out" >/dev/null \
  || { echo "FAIL: main should be in candidates when ahead of origin -> $out"; exit 1; }
[ "$(jq -r '.remoteWarning' <<<"$out")" != "null" ] || { echo "FAIL: ahead remoteWarning should be set -> $out"; exit 1; }
[ "$(git -C "$ahead_repo" rev-parse refs/heads/main)" != "$(git -C "$ahead_repo" rev-parse refs/remotes/origin/main)" ] \
  || { echo "FAIL: ahead local main must not be auto-resolved"; exit 1; }

# --- (d) a persisted continue branch purely behind its own origin/<branch> -> fast-forwarded ---
cont_repo="$tmp/cont-repo"
mkdir -p "$cont_repo"
git init -q -b main "$cont_repo"
git -C "$cont_repo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init
cont_remote="$tmp/cont-remote.git"
git init -q --bare -b main "$cont_remote"
git -C "$cont_repo" remote add origin "$cont_remote"
HOME="$home" bash "$repo_root/scripts/cfq-changelog.sh" init "$cont_repo" "cfq/2026-03-04-conttopic" main "2026-03-04-conttopic"
git -C "$cont_repo" branch "cfq/2026-03-04-conttopic"
git -C "$cont_repo" push -q origin main "cfq/2026-03-04-conttopic"
cont_clone="$tmp/cont-clone"
git clone -q "$cont_remote" "$cont_clone"
git -C "$cont_clone" checkout -q "cfq/2026-03-04-conttopic"
git -C "$cont_clone" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m remote-ahead-branch
git -C "$cont_clone" push -q origin "cfq/2026-03-04-conttopic"
out=$(HOME="$home" bash "$branch_sh" plan "$cont_repo" "2026-03-04-conttopic")
[ "$(jq -r '.mode' <<<"$out")" = "continue" ] || { echo "FAIL: cont mode -> $out"; exit 1; }
[ "$(jq -r '.branch' <<<"$out")" = "cfq/2026-03-04-conttopic" ] || { echo "FAIL: cont branch -> $out"; exit 1; }
[ "$(jq -r '.remoteChecked' <<<"$out")" = "true" ] || { echo "FAIL: cont remoteChecked -> $out"; exit 1; }
[ "$(jq -r '.remoteWarning' <<<"$out")" = "null" ] || { echo "FAIL: cont remoteWarning -> $out"; exit 1; }
[ "$(git -C "$cont_repo" rev-parse "refs/heads/cfq/2026-03-04-conttopic")" = \
  "$(git -C "$cont_repo" rev-parse "refs/remotes/origin/cfq/2026-03-04-conttopic")" ] \
  || { echo "FAIL: local continue branch was not fast-forwarded"; exit 1; }

echo PASS
