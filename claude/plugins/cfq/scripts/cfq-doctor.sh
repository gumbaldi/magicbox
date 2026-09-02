#!/usr/bin/env bash
# Host dependency doctor. Deliberately jq-free (and free of every other non-shell-builtin
# dependency) so it still works when jq itself is missing — the one check every other cfq
# script cannot perform on its own behalf. Never installs anything, never invokes a package
# manager; it only reports and, for required gaps, offers an installer hint.
# Usage: cfq-doctor.sh check | cfq-doctor.sh check --json | cfq-doctor.sh hook
set -eu

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
inventory="$script_dir/config/dependencies.txt"

missing_required=""
missing_alt_groups=""
missing_optional=""

while IFS='|' read -r names kind desc; do
  case "$names" in ''|'#'*) continue ;; esac
  case "$kind" in
    required)
      command -v "$names" >/dev/null 2>&1 || missing_required="$missing_required $names"
      ;;
    optional)
      command -v "$names" >/dev/null 2>&1 || missing_optional="$missing_optional $names"
      ;;
    alternative)
      found=0
      old_ifs="$IFS"; IFS=','
      for a in $names; do
        command -v "$a" >/dev/null 2>&1 && { found=1; break; }
      done
      IFS="$old_ifs"
      [ "$found" -eq 1 ] || missing_alt_groups="$missing_alt_groups [$names]"
      ;;
  esac
done < "$inventory"

missing_required="${missing_required# }"
missing_alt_groups="${missing_alt_groups# }"
missing_optional="${missing_optional# }"

# Ponytail advisory: cfq only ever uses ponytail for one thing (the optional maintenance-run
# audit, a one-shot skill invocation) and expects it dormant otherwise. jq-free by design, same
# as the rest of this script — a grep for the key is enough for an advisory. Mirrors, at grep
# precision, the tier order ponytail/hooks/ponytail-config.js:76 getDefaultMode() itself uses:
# env var, then config file, then "full".
ponytail_advisory=""
if find "$HOME/.claude/plugins/cache" -mindepth 2 -maxdepth 2 -type d -name ponytail \
     2>/dev/null | grep -q .; then
  pony_mode=$(printf '%s' "${PONYTAIL_DEFAULT_MODE:-}" | tr 'A-Z' 'a-z')
  case "$pony_mode" in off|lite|full|ultra) ;; *) pony_mode="" ;; esac
  if [ -z "$pony_mode" ]; then
    pony_cfg="${XDG_CONFIG_HOME:-$HOME/.config}/ponytail/config.json"
    if [ -f "$pony_cfg" ]; then
      pony_mode=$(grep -o '"defaultMode"[[:space:]]*:[[:space:]]*"[A-Za-z]*"' "$pony_cfg" 2>/dev/null \
        | head -1 | sed -E 's/.*"([A-Za-z]+)"[[:space:]]*$/\1/' | tr 'A-Z' 'a-z')
      case "$pony_mode" in off|lite|full|ultra) ;; *) pony_mode="" ;; esac
    fi
  fi
  [ -z "$pony_mode" ] && pony_mode="full"
  if [ "$pony_mode" != "off" ]; then
    ponytail_advisory="ponytail mode: $pony_mode (cfq expects off) -- fix: /ponytail default off"
  fi
fi

install_hint() {
  # $1: command name. Best-effort, environment-owner action only — never executed here.
  if command -v apt-get >/dev/null 2>&1; then echo "apt-get install -y $1"
  elif command -v brew >/dev/null 2>&1; then echo "brew install $1"
  elif command -v dnf >/dev/null 2>&1; then echo "dnf install -y $1"
  elif command -v apk >/dev/null 2>&1; then echo "apk add $1"
  else echo "install $1 via your platform's package manager"
  fi
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

json_array() {
  # $1: space-separated words -> ["a","b"] (or [] if empty)
  local out="" w first=1
  for w in $1; do
    [ "$first" -eq 1 ] || out="$out,"
    out="$out\"$(json_escape "$w")\""
    first=0
  done
  printf '[%s]' "$out"
}

mode="${1:-}"

case "$mode" in
  check)
    fmt="${2:-}"
    if [ "$fmt" = "--json" ]; then
      ok="true"
      [ -z "$missing_required" ] && [ -z "$missing_alt_groups" ] || ok="false"
      pony_json="null"
      [ -n "$ponytail_advisory" ] && pony_json="\"$(json_escape "$ponytail_advisory")\""
      printf '{"ok":%s,"missingRequired":%s,"missingAlternativeGroups":%s,"missingOptional":%s,"ponytailAdvisory":%s}\n' \
        "$ok" "$(json_array "$missing_required")" "$(json_array "$missing_alt_groups")" "$(json_array "$missing_optional")" "$pony_json"
    else
      echo "cfq dependency check"
      if [ -z "$missing_required" ] && [ -z "$missing_alt_groups" ]; then
        echo "  required: ok"
      else
        [ -n "$missing_required" ] && echo "  missing required: $missing_required"
        [ -n "$missing_alt_groups" ] && echo "  missing alternative group(s): $missing_alt_groups"
        for c in $missing_required; do
          echo "    hint: $(install_hint "$c")"
        done
      fi
      if [ -n "$missing_optional" ]; then
        echo "  optional (degraded, not blocking): $missing_optional"
      else
        echo "  optional: ok"
      fi
      if [ -n "$ponytail_advisory" ]; then
        echo "  optional advisory: $ponytail_advisory"
      fi
    fi
    ;;
  hook)
    if [ -z "$missing_required" ] && [ -z "$missing_alt_groups" ]; then
      exit 0
    fi
    gap=$(printf '%s %s' "$missing_required" "$missing_alt_groups" | tr -s ' ')
    gap="${gap# }"; gap="${gap% }"
    msg="cfq: missing required host command(s): $gap — cfq scripts will fail until this is installed."
    ctx="cfq dependency check found missing required command(s): $gap. Avoid running any cfq (/pfq, /ifq, /cfq, /rfq) command until this is resolved; the environment owner needs to install it."
    printf '{"systemMessage":"%s","hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
      "$(json_escape "$msg")" "$(json_escape "$ctx")"
    ;;
  *)
    echo "usage: cfq-doctor.sh check | check --json | hook" >&2
    exit 1
    ;;
esac
