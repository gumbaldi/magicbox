#!/usr/bin/env bash
# Self-test for scripts/cfq-ifq-preflight.sh. No framework, no fixtures beyond what's built here —
# just `bash tests/test-ifq-preflight.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tmp=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$tmp" "$home"' EXIT

# ------------------------------------------------------------ call-counting copy ------
# Copies the whole scripts/ dir so cfq-ifq-preflight.sh's own script_dir resolution (and every
# sibling script it shells out to, e.g. cfq-resume.sh -> cfq-branch.sh) resolves inside the copy,
# then swaps cfq-branch.sh for a wrapper that logs every invocation before delegating to the real
# binary.
scripts_copy="$tmp/scripts"
cp -r "$repo_root/scripts" "$scripts_copy"
mv "$scripts_copy/cfq-branch.sh" "$scripts_copy/cfq-branch-real.sh"
count_log="$tmp/branch-calls.log"
: > "$count_log"
cat > "$scripts_copy/cfq-branch.sh" <<EOF
#!/usr/bin/env bash
set -eu
d="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
echo call >> "$count_log"
exec "\$d/cfq-branch-real.sh" "\$@"
EOF
chmod +x "$scripts_copy/cfq-branch.sh"
pf="$scripts_copy/cfq-ifq-preflight.sh"

setup_repo() {
  local repo="$1"
  mkdir -p "$repo"
  git init -q -b main "$repo"
  git -C "$repo" -c user.email=a@b.c -c user.name=a commit -q --allow-empty -m init
  HOME="$home" bash "$scripts_copy/cfq-registry.sh" add "$repo" >/dev/null
}

# ------------------------------------------------------------ NO_REPO ------------------
out=$(HOME="$home" bash "$pf" "$tmp/does-not-exist")
[ "$(jq -r .status <<<"$out")" = "NO_REPO" ] || { echo "FAIL: non-git status = $out"; exit 1; }

# ------------------------------------------------------------ continue mode: call count = 1
repo1="$tmp/continue-repo"; setup_repo "$repo1"
mkdir -p "$repo1/.claude/cfq/impl/2026-01-01-solo"
printf '# T\n\n## Size\n\nS\n' > "$repo1/.claude/cfq/impl/2026-01-01-solo/01-a.md"
git -C "$repo1" branch "cfq/2026-01-01-solo"

: > "$count_log"
out=$(HOME="$home" bash "$pf" "$repo1")
[ "$(jq -r .status <<<"$out")" = "OK" ] || { echo "FAIL: continue-mode status = $out"; exit 1; }
[ "$(jq -r .branch.mode <<<"$out")" = "continue" ] || { echo "FAIL: expected continue mode = $out"; exit 1; }
calls=$(wc -l < "$count_log")
[ "$calls" = "1" ] || { echo "FAIL: continue-mode cfq-branch.sh calls = $calls, want 1"; exit 1; }

# ------------------------------------------------------------ new mode: preflight (1) + mutation's
# post-checkout confirm (1) = 2, combined across the sequence.
repo2="$tmp/new-repo"; setup_repo "$repo2"
mkdir -p "$repo2/.claude/cfq/impl/2026-01-01-fresh"
printf '# T\n\n## Size\n\nL\n' > "$repo2/.claude/cfq/impl/2026-01-01-fresh/01-a.md"

: > "$count_log"
out=$(HOME="$home" bash "$pf" "$repo2")
[ "$(jq -r .branch.mode <<<"$out")" = "new" ] || { echo "FAIL: expected new mode = $out"; exit 1; }
branch=$(jq -r .branch.branch <<<"$out")
git -C "$repo2" checkout -q -b "$branch"
HOME="$home" bash "$scripts_copy/cfq-branch.sh" plan "$repo2" "2026-01-01-fresh" >/dev/null
calls=$(wc -l < "$count_log")
[ "$calls" = "2" ] || { echo "FAIL: new-mode cfq-branch.sh calls = $calls, want 2"; exit 1; }

# ------------------------------------------------------------ selection filters --------
repo3="$tmp/multi-repo"; setup_repo "$repo3"
qdir="$repo3/.claude/cfq/impl"
mkdir -p "$qdir/2026-01-01-alpha" "$qdir/2026-01-02-beta" "$qdir/2026-01-03-blocked" "$qdir/2026-01-04-planning"
touch "$qdir/2026-01-01-alpha/01-a.md" "$qdir/2026-01-02-beta/01-b.md" \
      "$qdir/2026-01-03-blocked/01-c.md" "$qdir/2026-01-04-planning/01-d.md"
echo 2026-01-01-alpha > "$qdir/2026-01-03-blocked/.dependsOn"
touch "$qdir/2026-01-04-planning/.planning"

out=$(HOME="$home" bash "$pf" "$repo3")
[ "$(jq -r .status <<<"$out")" = "OK" ] || { echo "FAIL: multi status = $out"; exit 1; }
[ "$(jq -c '.batch' <<<"$out")" = "null" ] || { echo "FAIL: 2+ selectable should leave batch null: $out"; exit 1; }
[ "$(jq -c '.nextPhase' <<<"$out")" = "null" ] || { echo "FAIL: 2+ selectable should leave nextPhase null: $out"; exit 1; }
got=$(jq -S -c '.selection.selectable | map(.name) | sort' <<<"$out")
[ "$got" = '["2026-01-01-alpha","2026-01-02-beta"]' ] || { echo "FAIL: selectable = $got"; exit 1; }
[ "$(jq -c '.selection.blocked | map(.name)' <<<"$out")" = '["2026-01-03-blocked"]' ] \
  || { echo "FAIL: blocked = $out"; exit 1; }
[ "$(jq -c '.selection.planning' <<<"$out")" = '["2026-01-04-planning"]' ] \
  || { echo "FAIL: planning = $out"; exit 1; }

# --select round-trip resolves one of the ambiguous batches
out=$(HOME="$home" bash "$pf" "$repo3" --select 2026-01-02-beta)
[ "$(jq -r '.batch.name' <<<"$out")" = "2026-01-02-beta" ] || { echo "FAIL: --select did not resolve batch: $out"; exit 1; }
[ "$(jq -r '.nextPhase.slug' <<<"$out")" = "01-b" ] || { echo "FAIL: --select nextPhase: $out"; exit 1; }

# only blocked batches left -> BLOCKED (a real, unfinished dependency actually blocks)
repo4="$tmp/blocked-only"; setup_repo "$repo4"
mkdir -p "$repo4/.claude/cfq/impl/2026-01-01-dep" "$repo4/.claude/cfq/impl/2026-01-02-b"
touch "$repo4/.claude/cfq/impl/2026-01-01-dep/01-x.md" "$repo4/.claude/cfq/impl/2026-01-02-b/01-x.md"
echo 2026-01-01-dep > "$repo4/.claude/cfq/impl/2026-01-02-b/.dependsOn"
out=$(HOME="$home" bash "$pf" "$repo4")
[ "$(jq -r .status <<<"$out")" = "OK" ] || { echo "FAIL: blocked-only status = $out"; exit 1; }
[ "$(jq -r '.batch.name' <<<"$out")" = "2026-01-01-dep" ] || { echo "FAIL: should auto-select the unblocked dep batch: $out"; exit 1; }
got=$(jq -c '.selection.blocked | map(.name)' <<<"$out")
[ "$got" = '["2026-01-02-b"]' ] || { echo "FAIL: blocked list = $got"; exit 1; }

# an unresolvable dependency name is surfaced but never blocks
repo4b="$tmp/unknown-dep"; setup_repo "$repo4b"
mkdir -p "$repo4b/.claude/cfq/impl/2026-01-01-b"
touch "$repo4b/.claude/cfq/impl/2026-01-01-b/01-x.md"
echo does-not-exist > "$repo4b/.claude/cfq/impl/2026-01-01-b/.dependsOn"
out=$(HOME="$home" bash "$pf" "$repo4b")
[ "$(jq -r .status <<<"$out")" = "OK" ] || { echo "FAIL: unknown-dep should not block: $out"; exit 1; }
[ "$(jq -r '.batch.name' <<<"$out")" = "2026-01-01-b" ] || { echo "FAIL: unknown-dep batch should be selectable: $out"; exit 1; }

# nothing at all -> NO_BATCH
repo5="$tmp/empty-repo"; setup_repo "$repo5"
out=$(HOME="$home" bash "$pf" "$repo5")
[ "$(jq -r .status <<<"$out")" = "NO_BATCH" ] || { echo "FAIL: empty-repo status = $out"; exit 1; }

# ------------------------------------------------------------ MULTIPLE_IN_PROGRESS -----
repo6="$tmp/multi-inprogress"; setup_repo "$repo6"
qdir6="$repo6/.claude/cfq/impl"
mkdir -p "$qdir6/2026-01-01-a/done" "$qdir6/2026-01-02-b/done"
touch "$qdir6/2026-01-01-a/01-x.md" "$qdir6/2026-01-01-a/done/00-y.md" \
      "$qdir6/2026-01-02-b/01-x.md" "$qdir6/2026-01-02-b/done/00-y.md"
out=$(HOME="$home" bash "$pf" "$repo6")
[ "$(jq -r .status <<<"$out")" = "MULTIPLE_IN_PROGRESS" ] || { echo "FAIL: multi-inprogress status = $out"; exit 1; }
got=$(jq -S -c '.selection.multipleInProgress | sort' <<<"$out")
[ "$got" = '["2026-01-01-a","2026-01-02-b"]' ] || { echo "FAIL: multipleInProgress = $got"; exit 1; }

# ------------------------------------------------------------ single in-progress auto-selects --
repo7="$tmp/single-inprogress"; setup_repo "$repo7"
qdir7="$repo7/.claude/cfq/impl"
mkdir -p "$qdir7/2026-01-01-inprog/done" "$qdir7/2026-01-02-other"
touch "$qdir7/2026-01-01-inprog/01-a.md" "$qdir7/2026-01-01-inprog/done/00-x.md" "$qdir7/2026-01-02-other/01-b.md"
out=$(HOME="$home" bash "$pf" "$repo7")
[ "$(jq -r .status <<<"$out")" = "OK" ] || { echo "FAIL: single-inprogress status = $out"; exit 1; }
[ "$(jq -r '.selection.inProgress' <<<"$out")" = "2026-01-01-inprog" ] || { echo "FAIL: inProgress field = $out"; exit 1; }
[ "$(jq -r '.batch.name' <<<"$out")" = "2026-01-01-inprog" ] || { echo "FAIL: auto-selected batch = $out"; exit 1; }

# ------------------------------------------------------------ failedAttempt ------------
repo8="$tmp/failed-attempt"; setup_repo "$repo8"
mkdir -p "$repo8/.claude/cfq/impl/2026-01-01-solo"
printf '# T\n\n## Size\n\nM\n' > "$repo8/.claude/cfq/impl/2026-01-01-solo/01-a.md"
out=$(HOME="$home" bash "$pf" "$repo8")
[ "$(jq -r '.nextPhase.failedAttempt.found' <<<"$out")" = "false" ] || { echo "FAIL: no red entry yet: $out"; exit 1; }

HOME="$home" bash "$scripts_copy/cfq-report.sh" append "$repo8/.claude/cfq/impl/2026-01-01-solo" \
  '{"phase":"01-a","status":"red","finished":"2026-01-01T00:00:00+00:00","summary":"boom","deviations":[],"errors":["x"],"verification":"x","commit":""}' >/dev/null 2>&1
out=$(HOME="$home" bash "$pf" "$repo8")
[ "$(jq -r '.nextPhase.failedAttempt.found' <<<"$out")" = "true" ] || { echo "FAIL: red entry not found: $out"; exit 1; }
[ "$(jq -r '.nextPhase.failedAttempt.note' <<<"$out")" = "boom" ] || { echo "FAIL: failedAttempt note: $out"; exit 1; }

# no report.json at all anywhere -> {"found": false}, no crash (asserted above for repo1/continue fixture too)
[ "$(HOME="$home" bash "$scripts_copy/cfq-report.sh" last-failure "$repo1/.claude/cfq/impl/2026-01-01-solo" "01-a" | jq -r .found)" = "false" ] \
  || { echo "FAIL: last-failure on batch with no report.json should be found=false"; exit 1; }

# ------------------------------------------------------------ contextGate defaults to M --------
repo9="$tmp/no-size"; setup_repo "$repo9"
mkdir -p "$repo9/.claude/cfq/impl/2026-01-01-nosize"
printf '# T\n' > "$repo9/.claude/cfq/impl/2026-01-01-nosize/01-a.md"
out=$(HOME="$home" bash "$pf" "$repo9")
[ "$(jq -r '.contextGate.size' <<<"$out")" = "M" ] || { echo "FAIL: missing ## Size should default to M: $out"; exit 1; }
direct_gate=$(HOME="$home" bash "$scripts_copy/ctx-usage.sh" gate M)
direct_verdict=$(awk '{for(i=1;i<=NF;i++) if ($i=="START"||$i=="HANDOFF") print $i}' <<<"$direct_gate")
[ "$(jq -r '.contextGate.verdict' <<<"$out")" = "$direct_verdict" ] \
  || { echo "FAIL: contextGate.verdict != ctx-usage.sh gate's own verdict"; exit 1; }

# ------------------------------------------------------------ deterministic + read-only --------
out1=$(HOME="$home" bash "$pf" "$repo8")
out2=$(HOME="$home" bash "$pf" "$repo8")
[ "$out1" = "$out2" ] || { echo "FAIL: two runs on the same fixture produced different output"; exit 1; }

marker="$tmp/marker"; touch "$marker"; sleep 1
HOME="$home" bash "$pf" "$repo8" >/dev/null
changed=$(find "$repo8" -newer "$marker")
[ -z "$changed" ] || { echo "FAIL: run modified files under the fixture repo: $changed"; exit 1; }

echo PASS
