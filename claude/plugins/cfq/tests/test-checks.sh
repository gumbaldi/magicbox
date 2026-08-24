#!/usr/bin/env bash
# Self-test for scripts/cfq-lint.sh and scripts/cfq-security.sh. No framework, no fixtures beyond
# what's built here — just `bash tests/test-checks.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lint_sh="$repo_root/scripts/cfq-lint.sh"
security_sh="$repo_root/scripts/cfq-security.sh"
lang_sh="$repo_root/scripts/cfq-lang.sh"
maint_sh="$repo_root/scripts/cfq-maintenance.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# ============================================================ cfq-lint.sh ============
qdir="$tmp/lintrepo/.claude/cfq"
mkdir -p "$qdir"

# --- dirty batch: exactly one violation per content/structural rule, plus one correct file ---
dirty="$qdir/2026-01-01-dirty"
mkdir -p "$dirty/done"
target="$tmp/existing-target"; touch "$target"

# 01-a: correct — all headings, one existing absolute path, no issues
cat >"$dirty/01-a.md" <<EOF
## Size
M
## Context
x
## Affected Files
- \`$target\` (ändern)
## Changes
x
## Verification
x
EOF

# 02-b: sections violation — missing the Verification heading
cat >"$dirty/02-b.md" <<EOF
## Size
M
## Context
x
## Affected Files
## Changes
x
EOF

# 03-c: abspath violation — relative path (existence is not checked for a non-absolute path)
cat >"$dirty/03-c.md" <<EOF
## Size
M
## Context
x
## Affected Files
- \`relative/path.sh\` (ändern)
## Changes
x
## Verification
x
EOF

# 04-d: missing violation — absolute path, marked "(ändern)", does not exist
cat >"$dirty/04-d.md" <<EOF
## Size
M
## Context
x
## Affected Files
- \`$tmp/does-not-exist.sh\` (ändern)
## Changes
x
## Verification
x
EOF

# 05-e: stale-new violation — marked "(new)" but the path already exists
cat >"$dirty/05-e.md" <<EOF
## Size
M
## Context
x
## Affected Files
- \`$target\` (new)
## Changes
x
## Verification
x
EOF

# 08-g: sections violation — missing the Size heading
cat >"$dirty/08-g.md" <<EOF
## Context
x
## Affected Files
- \`$target\` (ändern)
## Changes
x
## Verification
x
EOF

# 09-h: sections violation — the old German "Größe" heading no longer counts as Size
cat >"$dirty/09-h.md" <<EOF
## Größe
M
## Context
x
## Affected Files
- \`$target\` (ändern)
## Changes
x
## Verification
x
EOF

# done/07-f: numbering gap (06 is skipped). Deliberately full of content violations too, to prove
# done/ phases are excluded from sections/abspath/missing/stale-new — only numbering must fire.
cat >"$dirty/done/07-f.md" <<EOF
## Context
x
## Affected Files
- \`relative/also-bad.sh\` (ändern)
- \`$tmp/also-does-not-exist.sh\` (ändern)
## Changes
x
EOF

# invalid .priority value -> priority violation (a missing file is now the normal, unflagged case)
echo medium >"$dirty/.priority"

if out=$(bash "$lint_sh" "$dirty" 2>&1); then
  echo "FAIL: dirty batch should exit non-zero"; exit 1
fi

assert_once() {
  local rule="$1" want="${2:-1}" n
  n=$(printf '%s\n' "$out" | grep -c ": $rule:") || true
  [ "$n" = "$want" ] || { printf 'FAIL: rule %s fired %s times, want %s. Output:\n%s\n' "$rule" "$n" "$want" "$out"; exit 1; }
}
assert_once sections 3
assert_once numbering
assert_once abspath
assert_once missing
assert_once stale-new
assert_once priority
assert_once batch-context 1

printf '%s\n' "$out" | grep -q '^01-a\.md:' && { echo "FAIL: correct file 01-a.md appears in findings"; exit 1; }
printf '%s\n' "$out" | grep -q '07-f\.md:' && { echo "FAIL: done/ file content should never be linted, got: $out"; exit 1; }

# --- clean batch: valid content and priority, but a dangling .dependsOn entry ---
clean="$qdir/2026-01-02-clean"
mkdir -p "$clean"
echo high >"$clean/.priority"
echo gibtsnicht >"$clean/.dependsOn"
printf '# Batch Context\n\n## Goal\nDoes a thing.\n' >"$clean/.batch-context.md"
cat >"$clean/01-a.md" <<EOF
## Size
M
## Context
x
## Affected Files
- \`$target\` (ändern)
## Changes
x
## Verification
x
EOF

out=$(bash "$lint_sh" "$clean") && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: clean batch (dangling depends only) should exit 0, got $rc"; exit 1; }
printf '%s\n' "$out" | grep -q '^OK 1 phases$' || { echo "FAIL: clean batch summary line missing/wrong: $out"; exit 1; }
printf '%s\n' "$out" | grep -q '^warn: .*: depends: gibtsnicht does not exist$' \
  || { echo "FAIL: clean batch missing depends warning: $out"; exit 1; }

# --- "(new)" marker on an existing path fires stale-new ---
newmarker="$qdir/2026-01-03-newmarker"
mkdir -p "$newmarker"
cat >"$newmarker/01-a.md" <<EOF
## Size
M
## Context
x
## Affected Files
- \`$target\` (new)
## Changes
x
## Verification
x
EOF
if out=$(bash "$lint_sh" "$newmarker" 2>&1); then
  echo "FAIL: English (new) marker on an existing path should fail lint"; exit 1
fi
printf '%s\n' "$out" | grep -q ': stale-new:' \
  || { echo "FAIL: English (new) marker did not fire stale-new: $out"; exit 1; }
printf '%s\n' "$out" | grep -q ': priority:' \
  && { echo "FAIL: batch without .priority should not fire priority: $out"; exit 1; }

# --- batch-context: missing file, missing heading, empty section, good file ---
phase_body='## Size

S

## Context
x

## Affected Files

## Changes
x

## Verification
x
'

noctx="$qdir/2026-01-04-noctx"; mkdir -p "$noctx"
printf '%s' "$phase_body" >"$noctx/01-a.md"
out=$(bash "$lint_sh" "$noctx" 2>&1) && rc=0 || rc=$?
[ "$rc" != "0" ] || { echo "FAIL: missing .batch-context.md should fail lint"; exit 1; }
printf '%s\n' "$out" | grep -q ': batch-context: missing .batch-context.md' \
  || { echo "FAIL: missing .batch-context.md not reported: $out"; exit 1; }

nogoal="$qdir/2026-01-05-nogoal"; mkdir -p "$nogoal"
printf '%s' "$phase_body" >"$nogoal/01-a.md"
printf '# Batch Context\n\n## Decisions\nsomething\n' >"$nogoal/.batch-context.md"
out=$(bash "$lint_sh" "$nogoal" 2>&1) && rc=0 || rc=$?
[ "$rc" != "0" ] || { echo "FAIL: .batch-context.md without ## Goal should fail lint"; exit 1; }
printf '%s\n' "$out" | grep -q ': batch-context: .batch-context.md missing ## Goal heading' \
  || { echo "FAIL: missing ## Goal heading not reported: $out"; exit 1; }

emptygoal="$qdir/2026-01-06-emptygoal"; mkdir -p "$emptygoal"
printf '%s' "$phase_body" >"$emptygoal/01-a.md"
printf '# Batch Context\n\n## Goal\n\n## Decisions\nx\n' >"$emptygoal/.batch-context.md"
out=$(bash "$lint_sh" "$emptygoal" 2>&1) && rc=0 || rc=$?
[ "$rc" != "0" ] || { echo "FAIL: empty ## Goal section should fail lint"; exit 1; }
printf '%s\n' "$out" | grep -q ': batch-context: ## Goal section is empty' \
  || { echo "FAIL: empty ## Goal section not reported: $out"; exit 1; }

goodctx="$qdir/2026-01-07-goodctx"; mkdir -p "$goodctx"
printf '%s' "$phase_body" >"$goodctx/01-a.md"
printf '# Batch Context\n\n## Goal\nDoes a thing.\n' >"$goodctx/.batch-context.md"
out=$(bash "$lint_sh" "$goodctx") && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: valid .batch-context.md should pass lint, got $rc: $out"; exit 1; }
printf '%s\n' "$out" | grep -q '^OK 1 phases$' || { echo "FAIL: goodctx summary line missing/wrong: $out"; exit 1; }

# ============================================================ cfq-security.sh ========

# Forge detection: pure string parsing, no network, no credentials.
secrepo="$tmp/secrepo"; mkdir -p "$secrepo"; git init -q "$secrepo"

git -C "$secrepo" remote add origin git@github.com:acme/widget.git
out=$(CFQ_SECURITY_DETECT_ONLY=1 bash "$security_sh" "$secrepo")
[ "$out" = "github github.com acme/widget" ] || { echo "FAIL: git@ form -> $out"; exit 1; }

git -C "$secrepo" remote set-url origin https://github.com/acme/widget.git
out=$(CFQ_SECURITY_DETECT_ONLY=1 bash "$security_sh" "$secrepo")
[ "$out" = "github github.com acme/widget" ] || { echo "FAIL: https form -> $out"; exit 1; }

git -C "$secrepo" remote set-url origin ssh://git@forge.example:10022/team/widget.git
out=$(CFQ_SECURITY_DETECT_ONLY=1 bash "$security_sh" "$secrepo")
[ "$out" = "unknown forge.example team/widget" ] || { echo "FAIL: ssh form (no login) -> $out"; exit 1; }
out=$(CFQ_SECURITY_DETECT_ONLY=1 CFQ_TEA_LOGIN_HOSTS=forge.example bash "$security_sh" "$secrepo")
[ "$out" = "gitea forge.example team/widget" ] || { echo "FAIL: ssh form (with login) -> $out"; exit 1; }

git -C "$secrepo" remote set-url origin http://forge.example/team/widget.git
out=$(CFQ_SECURITY_DETECT_ONLY=1 bash "$security_sh" "$secrepo")
[ "$out" = "unknown forge.example team/widget" ] || { echo "FAIL: http form -> $out"; exit 1; }

git -C "$secrepo" remote remove origin
out=$(CFQ_SECURITY_DETECT_ONLY=1 bash "$security_sh" "$secrepo")
[ "$out" = "none - -" ] || { echo "FAIL: no remote -> $out"; exit 1; }

# Full run, no network-dependent branches reachable (no remote, no manifest): valid JSON, exit 0.
out=$(bash "$security_sh" "$secrepo") && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: security exit code = $rc, want 0"; exit 1; }
printf '%s' "$out" | jq -e '.available == false and (.sources | length) == 0 and (.hint | length) > 0' >/dev/null \
  || { echo "FAIL: no-source security output = $out"; exit 1; }

# Full run with a package.json but no lockfile: still valid JSON, still exit 0, whatever npm says.
mfrepo="$tmp/mfrepo"; mkdir -p "$mfrepo"; git init -q "$mfrepo"
echo '{"name":"x","version":"1.0.0"}' >"$mfrepo/package.json"
out=$(bash "$security_sh" "$mfrepo") && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: manifest-only security exit code = $rc, want 0"; exit 1; }
printf '%s' "$out" | jq -e 'type == "object"' >/dev/null \
  || { echo "FAIL: manifest-only security output is not valid JSON: $out"; exit 1; }

# ============================================================ cfq-lang.sh ============

langhome=$(mktemp -d)
langrepo="$tmp/langrepo"; mkdir -p "$langrepo/docs/en"
echo "# a" >"$langrepo/docs/en/a.md"

out=$(HOME="$langhome" CFQ_DOC_LANGUAGES=de bash "$lang_sh" "$langrepo")
[ "$(jq -c '.missing' <<<"$out")" = '["docs/de/a.md"]' ] \
  || { echo "FAIL: missing translation not reported: $out"; exit 1; }

mkdir -p "$langrepo/docs/de"
echo "# a" >"$langrepo/docs/de/a.md"
out=$(HOME="$langhome" CFQ_DOC_LANGUAGES=de bash "$lang_sh" "$langrepo")
[ "$(jq -c '.missing' <<<"$out")" = '[]' ] \
  || { echo "FAIL: missing should be empty once translated: $out"; exit 1; }

echo "# nur hier" >"$langrepo/docs/de/nur-hier.md"
out=$(HOME="$langhome" CFQ_DOC_LANGUAGES=de bash "$lang_sh" "$langrepo")
[ "$(jq -c '.stray' <<<"$out")" = '["docs/de/nur-hier.md"]' ] \
  || { echo "FAIL: stray file not reported: $out"; exit 1; }

echo "# intro" >"$langrepo/docs/intro.md"
out=$(HOME="$langhome" CFQ_DOC_LANGUAGES=de bash "$lang_sh" "$langrepo")
[ "$(jq -c '.unfiled' <<<"$out")" = '["docs/intro.md"]' ] \
  || { echo "FAIL: unfiled file not reported: $out"; exit 1; }

minimalrepo="$tmp/minimalrepo"; mkdir -p "$minimalrepo"
out=$(HOME="$langhome" CFQ_DOC_LEVEL=minimal bash "$lang_sh" "$minimalrepo") && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: minimal/no-docs should exit 0, got $rc"; exit 1; }
jq -e '.missing == [] and .stray == [] and .unfiled == [] and (.note | length) > 0' <<<"$out" >/dev/null \
  || { echo "FAIL: minimal/no-docs output wrong: $out"; exit 1; }

out=$(HOME="$langhome" bash "$lang_sh" "$minimalrepo" --changed HEAD) && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: --changed in a non-git dir should exit 0, got $rc"; exit 1; }
[ "$(jq -r '.scope' <<<"$out")" = "repo" ] \
  || { echo "FAIL: --changed in a non-git dir should fall back to scope repo: $out"; exit 1; }

rm -rf "$langhome"

# ============================================================ cfq-maintenance.sh =====

mainthome=$(mktemp -d)
maintrepo="$tmp/maintrepo"; mkdir -p "$maintrepo"; git init -q "$maintrepo"
git -C "$maintrepo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m init

out=$(HOME="$mainthome" bash "$maint_sh" due "$maintrepo")
[ "$out" = "DUE 0" ] || { echo "FAIL: no marker -> '$out', want 'DUE 0'"; exit 1; }

HOME="$mainthome" bash "$maint_sh" stamp "$maintrepo" >/dev/null
out=$(HOME="$mainthome" bash "$maint_sh" due "$maintrepo")
[ "$out" = "NOT_DUE 0" ] || { echo "FAIL: stamp then due -> '$out', want 'NOT_DUE 0'"; exit 1; }

git -C "$maintrepo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m c1
git -C "$maintrepo" -c user.email=a@b.c -c user.name=a commit --allow-empty -q -m c2
out=$(HOME="$mainthome" CFQ_MAINTENANCE_EVERY=2 bash "$maint_sh" due "$maintrepo")
[ "$out" = "DUE 2" ] || { echo "FAIL: 2 commits, every=2 -> '$out', want 'DUE 2'"; exit 1; }

out=$(HOME="$mainthome" CFQ_MAINTENANCE_EVERY=50 bash "$maint_sh" due "$maintrepo")
[ "$out" = "NOT_DUE 2" ] || { echo "FAIL: 2 commits, every=50 -> '$out', want 'NOT_DUE 2'"; exit 1; }

printf '2020-01-01 0000000\n' >"$maintrepo/.claude/cfq/.maintenance"
out=$(HOME="$mainthome" bash "$maint_sh" due "$maintrepo")
case "$out" in
  DUE*) : ;;
  *) echo "FAIL: garbage sha -> '$out', want DUE*"; exit 1 ;;
esac

printf '2020-01-01\n' >"$maintrepo/.claude/cfq/.maintenance"
out=$(HOME="$mainthome" bash "$maint_sh" due "$maintrepo")
case "$out" in
  DUE*) : ;;
  *) echo "FAIL: empty sha -> '$out', want DUE*"; exit 1 ;;
esac

HOME="$mainthome" bash "$maint_sh" stamp "$maintrepo" >/dev/null
before=$(cat "$maintrepo/.claude/cfq/.maintenance")
out=$(HOME="$mainthome" CFQ_MAINTENANCE_EVERY=0 bash "$maint_sh" due "$maintrepo")
[ "$out" = "OFF" ] || { echo "FAIL: maintenanceEvery=0 -> '$out', want 'OFF'"; exit 1; }
after=$(cat "$maintrepo/.claude/cfq/.maintenance")
[ "$before" = "$after" ] || { echo "FAIL: OFF must not touch the marker"; exit 1; }

rm -rf "$mainthome"

# ============================================================ cfq-lang.sh prose mode =

prosehome=$(mktemp -d)
proserepo="$tmp/proserepo"; mkdir -p "$proserepo"; git init -q "$proserepo"
printf 'line one\nline two\n' >"$proserepo/f.txt"
git -C "$proserepo" add f.txt
git -C "$proserepo" -c user.email=a@b.c -c user.name=a commit -q -m "base commit"
base_ref=$(git -C "$proserepo" rev-parse HEAD)

sed -i '1d' "$proserepo/f.txt"
echo "added line" >>"$proserepo/f.txt"
git -C "$proserepo" add f.txt
git -C "$proserepo" -c user.email=a@b.c -c user.name=a commit -q -m "small change with added line"

out=$(HOME="$prosehome" bash "$lang_sh" prose "$proserepo" "$base_ref")
printf '%s' "$out" | jq -e '.truncated == false' >/dev/null \
  || { echo "FAIL: small commit should not be truncated: $out"; exit 1; }
printf '%s' "$out" | jq -r '.sample' | grep -q "added line" \
  || { echo "FAIL: added line missing from sample: $out"; exit 1; }
printf '%s' "$out" | jq -r '.sample' | grep -q "line one" \
  && { echo "FAIL: removed line leaked into sample: $out"; exit 1; }
printf '%s' "$out" | jq -r '.sample' | grep -q "small change with added line" \
  || { echo "FAIL: commit message missing from sample: $out"; exit 1; }

small_ref=$(git -C "$proserepo" rev-parse HEAD)
for i in $(seq 1 400); do echo "padding line number $i to blow the cap with some extra filler text"; done >>"$proserepo/f.txt"
git -C "$proserepo" add f.txt
git -C "$proserepo" -c user.email=a@b.c -c user.name=a commit -q -m "big change"

out=$(HOME="$prosehome" bash "$lang_sh" prose "$proserepo" "$small_ref")
printf '%s' "$out" | jq -e '.truncated == true' >/dev/null \
  || { echo "FAIL: big commit should be truncated: $out"; exit 1; }
sample_bytes=$(printf '%s' "$(printf '%s' "$out" | jq -r '.sample')" | wc -c | tr -d ' ')
[ "$sample_bytes" -le 8192 ] || { echo "FAIL: sample exceeds byte cap: $sample_bytes"; exit 1; }

nogitdir="$tmp/nogitdir"; mkdir -p "$nogitdir"
out=$(HOME="$prosehome" bash "$lang_sh" prose "$nogitdir" HEAD) && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: prose on non-git dir should exit 0, got $rc"; exit 1; }
printf '%s' "$out" | jq -e '.sample == "" and (.note | length) > 0' >/dev/null \
  || { echo "FAIL: non-git prose output wrong: $out"; exit 1; }

out=$(HOME="$prosehome" bash "$lang_sh" "$proserepo")
printf '%s' "$out" | jq -e '(keys | sort) == (["codeLanguage","docLanguages","docLevel","missing","note","scope","stray","unfiled"] | sort)' >/dev/null \
  || { echo "FAIL: unchanged invocation key set changed: $out"; exit 1; }

rm -rf "$prosehome"

echo PASS
