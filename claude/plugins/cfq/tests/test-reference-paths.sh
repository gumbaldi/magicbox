#!/usr/bin/env bash
# Guards the reference-file layout described in CLAUDE.md: one flat references/ directory, every
# link ${CLAUDE_PLUGIN_ROOT}-qualified, no unexpanded token inside a reference file (the loader
# never expands it there), every named script real. Four checks, grep-sweep style like
# test-layout.sh check 8. Each check gets a synthetic minimal fixture (test-no-duplicate-defaults.sh's
# style) rather than a full tree copy, so the self-test stays cheap.
set -eu

plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1. Every ${CLAUDE_PLUGIN_ROOT}/references/<file>.md or <plugin-root>/references/<file>.md link
#    resolves under <root>/references/ — SKILL.md uses the expanded env var, a reference file (never
#    itself expanded at runtime) uses the literal <plugin-root> token instead.
check_links_resolve() {
  local root="$1" fails=0 file lineno match name
  while IFS=: read -r file lineno match; do
    name="${match#*/references/}"
    [ -f "$root/references/$name" ] && continue
    echo "FAIL: $file:$lineno dangling reference link: $match"
    fails=$((fails + 1))
  done < <(grep -rnoE '(\$\{CLAUDE_PLUGIN_ROOT\}|<plugin-root>)/references/[A-Za-z0-9_-]+\.md' "$root" --include='*.md' 2>/dev/null || true)
  return "$fails"
}

# 2. No bare `references/…\.md` link survives outside CLAUDE.md/docs/ (repo-root-relative there).
check_no_bare_relative() {
  local root="$1" fails=0 file lineno match rel
  while IFS=: read -r file lineno match; do
    rel="${file#"$root"/}"
    case "$rel" in
      CLAUDE.md | docs/*) continue ;;
    esac
    case "$match" in
      '${CLAUDE_PLUGIN_ROOT}/'* | '<plugin-root>/'*) continue ;;
    esac
    echo "FAIL: $file:$lineno bare relative reference link: $match"
    fails=$((fails + 1))
  done < <(grep -rnoE '(\$\{CLAUDE_PLUGIN_ROOT\}/|<plugin-root>/)?references/[A-Za-z0-9_-]+\.md' "$root" --include='*.md' 2>/dev/null || true)
  return "$fails"
}

# 3. No literal ${CLAUDE_PLUGIN_ROOT} token inside a reference file — the loader never expands it there.
check_no_token_in_references() {
  local root="$1" fails=0 file lineno
  [ -d "$root/references" ] || return 0
  while IFS=: read -r file lineno _; do
    echo "FAIL: $file:$lineno unexpanded \${CLAUDE_PLUGIN_ROOT} inside a reference file"
    fails=$((fails + 1))
  done < <(grep -rnoE 'CLAUDE_PLUGIN_ROOT' "$root/references" --include='*.md' 2>/dev/null || true)
  return "$fails"
}

# 4. Every cfq-<name>.sh mentioned anywhere exists under <root>/scripts/.
check_scripts_exist() {
  local root="$1" fails=0 file lineno match
  while IFS=: read -r file lineno match; do
    [ -f "$root/scripts/$match" ] && continue
    echo "FAIL: $file:$lineno names missing script: $match"
    fails=$((fails + 1))
  done < <(grep -rnoE 'cfq-[a-z-]+\.sh' "$root" --include='*.md' 2>/dev/null || true)
  return "$fails"
}

run_all() {
  local root="$1" fails=0
  check_links_resolve "$root" || fails=$((fails + $?))
  check_no_bare_relative "$root" || fails=$((fails + $?))
  check_no_token_in_references "$root" || fails=$((fails + $?))
  check_scripts_exist "$root" || fails=$((fails + $?))
  return "$fails"
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# --- fixture 1: dangling link must fail, a resolving one must not ---
mkdir -p "$tmp/f1-bad/references" "$tmp/f1-good/references"
touch "$tmp/f1-bad/references/real.md" "$tmp/f1-good/references/real.md"
echo 'read `${CLAUDE_PLUGIN_ROOT}/references/nope.md`' >"$tmp/f1-bad/skill.md"
printf 'read `${CLAUDE_PLUGIN_ROOT}/references/real.md`\nread `<plugin-root>/references/real.md`\n' >"$tmp/f1-good/skill.md"
out=$(check_links_resolve "$tmp/f1-bad" 2>&1) || true
echo "$out" | grep -q 'nope.md' || { echo "FAIL: check 1 self-test did not catch a dangling link"; exit 1; }
out=$(check_links_resolve "$tmp/f1-good" 2>&1) || true
[ -z "$out" ] || { echo "FAIL: check 1 self-test false-flagged a resolving link: $out"; exit 1; }

# --- fixture 2: bare relative link must fail outside CLAUDE.md/docs/, survive inside them ---
mkdir -p "$tmp/f2/docs"
echo 'read `references/maintenance.md`' >"$tmp/f2/skill.md"
echo 'see `references/queues.md`' >"$tmp/f2/CLAUDE.md"
echo 'see `references/doc-style.md`' >"$tmp/f2/docs/configuration.md"
echo 'read `<plugin-root>/references/queues.md`' >"$tmp/f2/reference.md"
out=$(check_no_bare_relative "$tmp/f2" 2>&1) || true
echo "$out" | grep -q 'skill.md' || { echo "FAIL: check 2 self-test did not catch a bare relative link"; exit 1; }
echo "$out" | grep -q 'CLAUDE.md\|configuration.md\|reference.md' && { echo "FAIL: check 2 self-test flagged an excluded doc file or a <plugin-root>-qualified link"; exit 1; }

# --- fixture 3: literal token inside a reference file must fail, the bound token must not ---
mkdir -p "$tmp/f3-bad/references" "$tmp/f3-good/references"
echo 'run `${CLAUDE_PLUGIN_ROOT}/scripts/x.sh`' >"$tmp/f3-bad/references/r.md"
echo 'run `<plugin-root>/scripts/x.sh`' >"$tmp/f3-good/references/r.md"
out=$(check_no_token_in_references "$tmp/f3-bad" 2>&1) || true
[ -n "$out" ] || { echo "FAIL: check 3 self-test did not catch a literal token in a reference file"; exit 1; }
out=$(check_no_token_in_references "$tmp/f3-good" 2>&1) || true
[ -z "$out" ] || { echo "FAIL: check 3 self-test false-flagged the bound <plugin-root> token: $out"; exit 1; }

# --- fixture 4: a named-but-missing script must fail, a real one must not ---
mkdir -p "$tmp/f4-bad/scripts" "$tmp/f4-good/scripts"
touch "$tmp/f4-good/scripts/cfq-real.sh"
echo 'run `cfq-ghost.sh`' >"$tmp/f4-bad/skill.md"
echo 'run `cfq-real.sh`' >"$tmp/f4-good/skill.md"
out=$(check_scripts_exist "$tmp/f4-bad" 2>&1) || true
echo "$out" | grep -q 'cfq-ghost.sh' || { echo "FAIL: check 4 self-test did not catch a ghost script"; exit 1; }
out=$(check_scripts_exist "$tmp/f4-good" 2>&1) || true
[ -z "$out" ] || { echo "FAIL: check 4 self-test false-flagged a real script: $out"; exit 1; }

# --- the real plugin tree must pass every check ---
run_all "$plugin_root" || { echo "FAIL: $? issue(s) found in $plugin_root"; exit 1; }

echo PASS
