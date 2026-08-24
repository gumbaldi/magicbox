#!/usr/bin/env bash
# Regression guard for config-runtime-refactor's motivating bug shape: a script reading a setting
# through cfq-settings.sh, but falling back on failure to a hardcoded literal that happens to copy
# that key's schema default. The default then only lives in cfq-settings.sh's schema in the common
# case — but a later change to the schema default silently stops reaching that script, which keeps
# using the frozen old value forever (cfq-lang.sh's pre-phase-6 `|| echo en`, and pre-phase-5
# cfq-scan.sh's `$HOME/git`, both this exact shape). Scope is deliberately narrow: only a fallback
# attached to an actual `cfq-settings.sh ... get` call is this bug shape — an unrelated `|| echo
# false`/`:-0` elsewhere in a script (an mtime fallback, a JSON boolean literal, ...) is not, and is
# not linted. Not a general linter; see cfq/CLAUDE.md's "adding a setting" convention.
#
# ctx-usage.sh is excluded alongside cfq-settings.sh itself: unlike every other script it uses
# `set -u`, not `set -e` (see its own header comment) specifically so the phase-start size gate
# always emits a decision even if the settings subsystem itself is unavailable -- its two
# `|| echo <default>` fallbacks are that crash-safety net, not forgotten duplication.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scripts_dir="$repo_root/scripts"
settings_sh="$scripts_dir/cfq-settings.sh"

# One rendered literal per line, in the same spelling a shell fallback would use for that schema
# default: int/string/enum bare, array CSV-joined, object as compact JSON.
default_reprs() {
  jq -r '
    to_entries[] | .value.default |
    if type == "array" then (map(tostring) | join(","))
    elif type == "object" then tojson
    else tostring
    end
  ' <<<"$1"
}

# Extracts the fallback literal from one candidate line, stripping one layer of matching quotes and
# a trailing `)`/`;`. Empty output means the line didn't actually carry a recognizable literal.
extract_literal() {
  local content="$1" literal=""
  case "$content" in
    *'|| echo '*)
      literal="${content##*'|| echo '}"
      literal="${literal%%;*}"
      literal="${literal%)*}"
      ;;
    *':-'*'}'*)
      literal="${content##*':-'}"
      literal="${literal%%\}*}"
      ;;
  esac
  [ -n "$literal" ] || return 0
  case "$literal" in
    \"*\") literal="${literal#\"}"; literal="${literal%\"}" ;;
    \'*\') literal="${literal#\'}"; literal="${literal%\'}" ;;
  esac
  printf '%s' "$literal"
}

# Scans every *.sh directly under $1 (non-recursive) except $2.. for a settings-read fallback
# literal that duplicates a schema default; FAIL lines go to stdout, exit status is the count found.
check_dir() {
  local dir="$1" reprs="$2"; shift 2
  local -a exempt=("$@")
  local fails=0 f base lineno content literal skip e
  for f in "$dir"/*.sh; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    skip=0
    for e in "${exempt[@]:-}"; do [ "$base" = "$e" ] && skip=1; done
    [ "$skip" -eq 1 ] && continue
    while IFS=: read -r lineno content; do
      case "$content" in
        *cfq-settings.sh*|*'$settings_sh'*) ;;
        *) continue ;;
      esac
      literal=$(extract_literal "$content")
      [ -n "$literal" ] || continue
      if grep -qxF "$literal" <<<"$reprs"; then
        echo "FAIL: $base:$lineno duplicates a schema default in its settings-read fallback: '$literal'"
        fails=$((fails + 1))
      fi
    done < <(grep -nE '\|\| echo |:-[^}]*\}' "$f" || true)
  done
  return "$fails"
}

schema_json=$("$settings_sh" describe)
reprs=$(default_reprs "$schema_json")

total_fails=0
check_dir "$scripts_dir" "$reprs" cfq-settings.sh ctx-usage.sh || total_fails=$?

# Self-check: the detector must actually catch the bug shape it exists for, and must not flag a
# fallback literal that legitimately differs from every schema default.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/bad.sh" <<'EOF'
#!/usr/bin/env bash
stop_pct=$("$script_dir/cfq-settings.sh" get stopPct 2>/dev/null || echo 60)
EOF
cat > "$tmp/good.sh" <<'EOF'
#!/usr/bin/env bash
marker=$("$script_dir/cfq-settings.sh" get someKey 2>/dev/null || echo not-a-schema-default)
EOF
selfcheck_out="$tmp/selfcheck.out"
: > "$selfcheck_out"
check_dir "$tmp" "$reprs" >"$selfcheck_out" || true
grep -q 'bad\.sh' "$selfcheck_out" \
  || { echo "FAIL: self-check did not catch the synthetic stopPct-duplicate fixture"; exit 1; }
grep -q 'good\.sh' "$selfcheck_out" \
  && { echo "FAIL: self-check false-flagged a fallback literal that isn't a schema default"; exit 1; }

[ "$total_fails" -eq 0 ] && echo PASS || exit 1
