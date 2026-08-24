#!/usr/bin/env bash
# Self-test for scripts/cfq-paths.sh and scripts/cfq-layout.sh. No framework, no fixtures.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
paths_sh="$repo_root/scripts/cfq-paths.sh"
layout_sh="$repo_root/scripts/cfq-layout.sh"
settings_sh="$repo_root/scripts/cfq-settings.sh"

repo=$(mktemp -d)
home=$(mktemp -d)
trap 'rm -rf "$repo" "$home"' EXIT
(cd "$repo" && git init -q)

# 1. Canonical path functions
. "$paths_sh"
[ "$(cfq_repo_dir "$repo")" = "$repo/.claude/cfq" ] || { echo "FAIL: cfq_repo_dir"; exit 1; }
[ "$(queue_dir "$repo")" = "$repo/.claude/cfq" ] || { echo "FAIL: queue_dir alias"; exit 1; }
[ "$(plan_dir "$repo")" = "$repo/.claude/cfq/plan" ] || { echo "FAIL: plan_dir"; exit 1; }
[ "$(impl_dir "$repo")" = "$repo/.claude/cfq/impl" ] || { echo "FAIL: impl_dir"; exit 1; }
[ "$(impl_done_dir "$repo")" = "$repo/.claude/cfq/impl/done" ] || { echo "FAIL: impl_done_dir"; exit 1; }
[ "$(todo_dir "$repo")" = "$repo/.claude/cfq/todo" ] || { echo "FAIL: todo_dir"; exit 1; }
[ "$(repo_settings_file "$repo")" = "$repo/.claude/cfq/settings.json" ] || { echo "FAIL: repo_settings_file"; exit 1; }
[ "$(lockfile "$repo")" = "$repo/.claude/cfq/.lock" ] || { echo "FAIL: lockfile"; exit 1; }
[ "$(maintenance_marker "$repo")" = "$repo/.claude/cfq/.maintenance" ] || { echo "FAIL: maintenance_marker"; exit 1; }
[ "$(telemetry_log "$repo")" = "$repo/.claude/cfq/telemetry.jsonl" ] || { echo "FAIL: telemetry_log"; exit 1; }

# 2. ensure creates the canonical dirs and adds exactly one exclude block (gitStatePolicy=local default)
HOME="$home" bash "$layout_sh" ensure "$repo" >/dev/null
[ -d "$repo/.claude/cfq/plan" ] && [ -d "$repo/.claude/cfq/impl/done" ] && [ -d "$repo/.claude/cfq/todo" ] \
  || { echo "FAIL: ensure did not create canonical dirs"; exit 1; }
ef="$(git -C "$repo" rev-parse --absolute-git-dir)/info/exclude"
n=$(grep -c '^# BEGIN cfq-managed' "$ef")
[ "$n" = "1" ] || { echo "FAIL: expected exactly one cfq-managed block, got $n"; exit 1; }
grep -qxF '.claude/cfq/settings.json' "$ef" && { echo "FAIL: settings.json must not be excluded"; exit 1; }
grep -qxF '.claude/cfq/plan/' "$ef" || { echo "FAIL: plan/ missing from exclude block"; exit 1; }

# 3. Idempotent: ensure again -> still exactly one block, byte-identical exclude file
before=$(cat "$ef")
HOME="$home" bash "$layout_sh" ensure "$repo" >/dev/null
after=$(cat "$ef")
[ "$before" = "$after" ] || { echo "FAIL: second ensure changed the exclude file"; exit 1; }

# 4. status reports the block as present and policy as local
out=$(HOME="$home" bash "$layout_sh" status "$repo")
[ "$(jq -r .excludeBlock <<<"$out")" = "present" ] || { echo "FAIL: status excludeBlock"; exit 1; }
[ "$(jq -r .gitStatePolicy <<<"$out")" = "local" ] || { echo "FAIL: status gitStatePolicy"; exit 1; }

# 5. Pre-existing unrelated exclude lines survive both a local sync and a switch to trackable
printf '*.log\n' >>"$ef"
HOME="$home" bash "$settings_sh" set --repo "$repo" gitStatePolicy trackable >/dev/null
HOME="$home" bash "$layout_sh" sync-git-policy "$repo" >/dev/null
grep -qxF '*.log' "$ef" || { echo "FAIL: unrelated exclude line lost on trackable switch"; exit 1; }
grep -q '^# BEGIN cfq-managed' "$ef" && { echo "FAIL: cfq-managed block still present under trackable"; exit 1; }

# 6. Switching back to local re-adds exactly one block, still keeps the unrelated line
HOME="$home" bash "$settings_sh" set --repo "$repo" gitStatePolicy local >/dev/null
HOME="$home" bash "$layout_sh" sync-git-policy "$repo" >/dev/null
grep -qxF '*.log' "$ef" || { echo "FAIL: unrelated exclude line lost on local switch-back"; exit 1; }
n=$(grep -c '^# BEGIN cfq-managed' "$ef")
[ "$n" = "1" ] || { echo "FAIL: expected exactly one block after switch-back, got $n"; exit 1; }

# 7. .gitignore is never touched, nothing gets staged or modified in the index
printf 'node_modules/\n' >"$repo/.gitignore"
git -C "$repo" add .gitignore
git -C "$repo" -c user.email=a@b.c -c user.name=a commit -q -m gitignore
gi_before=$(cat "$repo/.gitignore")
status_before=$(git -C "$repo" status --porcelain)
HOME="$home" bash "$layout_sh" ensure "$repo" >/dev/null
[ "$(cat "$repo/.gitignore")" = "$gi_before" ] || { echo "FAIL: .gitignore was modified"; exit 1; }
[ "$(git -C "$repo" status --porcelain)" = "$status_before" ] || { echo "FAIL: ensure staged/modified tracked files"; exit 1; }

# 8. Repo-local `.claude/code-for-queue` literal must not reappear in normal scripts or SKILL.md
#    files — permitted only in the isolated migration utility, its focused test fixture, and the
#    two phase-5 guard comments (cfq-paths.sh/cfq-layout.sh) and README.md's historical migration
#    note that explicitly document the retired layout rather than using it. The global
#    `$HOME/.claude/code-for-queue/` store is a different, still-current path — any line naming
#    HOME/home/~ is that, not this.
allowed_layout_files=(
  "scripts/migrations/cfq-layout-v1.sh"
  "tests/test-layout-migration.sh"
  "tests/test-layout.sh"
  "scripts/cfq-paths.sh"
  "scripts/cfq-layout.sh"
  "README.md"
)
fail8=0
while IFS=: read -r file lineno content; do
  rel="${file#"$repo_root"/}"
  allowed=0
  for a in "${allowed_layout_files[@]}"; do [ "$rel" = "$a" ] && allowed=1; done
  [ "$allowed" -eq 1 ] && continue
  case "$content" in *HOME*|*home*|*'~'*) continue ;; esac
  echo "FAIL: repo-local .claude/code-for-queue literal reappeared: $rel:$lineno"
  fail8=1
done < <(grep -rnE '\.claude/code-for-queue' "$repo_root" \
           --include='*.sh' --include='*.md' --include='*.toml' 2>/dev/null || true)
[ "$fail8" -eq 0 ] || exit 1

# `.claude/cfq/settings.json` must never end up in cfq's managed local-state exclude block — the
# settings file is meant to be trackable even under gitStatePolicy=local. Already asserted at check
# 2 above (grep -qxF '.claude/cfq/settings.json' "$ef" must never match); not re-asserted here.

echo PASS
