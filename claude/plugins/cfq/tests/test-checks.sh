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
qdir="$tmp/lintrepo/.claude/code-for-queue"
mkdir -p "$qdir"

# --- dirty batch: exactly one violation per content/structural rule, plus one correct file ---
dirty="$qdir/2026-01-01-dirty"
mkdir -p "$dirty/done"
target="$tmp/existing-target"; touch "$target"

# 01-a: correct — all headings, one existing absolute path, no issues
cat >"$dirty/01-a.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
- \`$target\` (ändern)
## Änderungen
x
## Verifikation
x
EOF

# 02-b: sections violation — missing the Verifikation/Verification heading
cat >"$dirty/02-b.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
## Änderungen
x
EOF

# 03-c: abspath violation — relative path (existence is not checked for a non-absolute path)
cat >"$dirty/03-c.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
- \`relative/path.sh\` (ändern)
## Änderungen
x
## Verifikation
x
EOF

# 04-d: missing violation — absolute path, marked "(ändern)", does not exist
cat >"$dirty/04-d.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
- \`$tmp/does-not-exist.sh\` (ändern)
## Änderungen
x
## Verifikation
x
EOF

# 05-e: stale-new violation — marked "(neu)" but the path already exists
cat >"$dirty/05-e.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
- \`$target\` (neu)
## Änderungen
x
## Verifikation
x
EOF

# 08-g: sections violation — missing the Größe/Size heading
cat >"$dirty/08-g.md" <<EOF
## Kontext
x
## Betroffene Dateien
- \`$target\` (ändern)
## Änderungen
x
## Verifikation
x
EOF

# done/07-f: numbering gap (06 is skipped). Deliberately full of content violations too, to prove
# done/ phases are excluded from sections/abspath/missing/stale-new — only numbering must fire.
cat >"$dirty/done/07-f.md" <<EOF
## Kontext
x
## Betroffene Dateien
- \`relative/also-bad.sh\` (ändern)
- \`$tmp/also-does-not-exist.sh\` (ändern)
## Änderungen
x
EOF

# no .priority file -> priority violation

if out=$(bash "$lint_sh" "$dirty" 2>&1); then
  echo "FAIL: dirty batch should exit non-zero"; exit 1
fi

assert_once() {
  local rule="$1" want="${2:-1}" n
  n=$(printf '%s\n' "$out" | grep -c ": $rule:") || true
  [ "$n" = "$want" ] || { printf 'FAIL: rule %s fired %s times, want %s. Output:\n%s\n' "$rule" "$n" "$want" "$out"; exit 1; }
}
assert_once sections 2
assert_once numbering
assert_once abspath
assert_once missing
assert_once stale-new
assert_once priority

printf '%s\n' "$out" | grep -q '^01-a\.md:' && { echo "FAIL: correct file 01-a.md appears in findings"; exit 1; }
printf '%s\n' "$out" | grep -q '07-f\.md:' && { echo "FAIL: done/ file content should never be linted, got: $out"; exit 1; }

# --- clean batch: valid content and priority, but a dangling .dependsOn entry ---
clean="$qdir/2026-01-02-clean"
mkdir -p "$clean"
echo high >"$clean/.priority"
echo gibtsnicht >"$clean/.dependsOn"
cat >"$clean/01-a.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
- \`$target\` (ändern)
## Änderungen
x
## Verifikation
x
EOF

out=$(bash "$lint_sh" "$clean") && rc=0 || rc=$?
[ "$rc" = "0" ] || { echo "FAIL: clean batch (dangling depends only) should exit 0, got $rc"; exit 1; }
printf '%s\n' "$out" | grep -q '^OK 1 phases$' || { echo "FAIL: clean batch summary line missing/wrong: $out"; exit 1; }
printf '%s\n' "$out" | grep -q '^warn: .*: depends: gibtsnicht does not exist$' \
  || { echo "FAIL: clean batch missing depends warning: $out"; exit 1; }

# --- English "(new)" marker: same stale-new rule as the German "(neu)" alias ---
newmarker="$qdir/2026-01-03-newmarker"
mkdir -p "$newmarker"
cat >"$newmarker/01-a.md" <<EOF
## Größe
M
## Kontext
x
## Betroffene Dateien
- \`$target\` (new)
## Änderungen
x
## Verifikation
x
EOF
if out=$(bash "$lint_sh" "$newmarker" 2>&1); then
  echo "FAIL: English (new) marker on an existing path should fail lint"; exit 1
fi
printf '%s\n' "$out" | grep -q ': stale-new:' \
  || { echo "FAIL: English (new) marker did not fire stale-new: $out"; exit 1; }

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

printf '2020-01-01 0000000\n' >"$maintrepo/.claude/code-for-queue/.maintenance"
out=$(HOME="$mainthome" bash "$maint_sh" due "$maintrepo")
case "$out" in
  DUE*) : ;;
  *) echo "FAIL: garbage sha -> '$out', want DUE*"; exit 1 ;;
esac

printf '2020-01-01\n' >"$maintrepo/.claude/code-for-queue/.maintenance"
out=$(HOME="$mainthome" bash "$maint_sh" due "$maintrepo")
case "$out" in
  DUE*) : ;;
  *) echo "FAIL: empty sha -> '$out', want DUE*"; exit 1 ;;
esac

HOME="$mainthome" bash "$maint_sh" stamp "$maintrepo" >/dev/null
before=$(cat "$maintrepo/.claude/code-for-queue/.maintenance")
out=$(HOME="$mainthome" CFQ_MAINTENANCE_EVERY=0 bash "$maint_sh" due "$maintrepo")
[ "$out" = "OFF" ] || { echo "FAIL: maintenanceEvery=0 -> '$out', want 'OFF'"; exit 1; }
after=$(cat "$maintrepo/.claude/code-for-queue/.maintenance")
[ "$before" = "$after" ] || { echo "FAIL: OFF must not touch the marker"; exit 1; }

rm -rf "$mainthome"

echo PASS
