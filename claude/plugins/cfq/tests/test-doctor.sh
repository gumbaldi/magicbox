#!/usr/bin/env bash
# Self-test for scripts/cfq-doctor.sh. No framework, no fixtures — just `bash tests/test-doctor.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
doctor_sh="$repo_root/scripts/cfq-doctor.sh"
inventory="$repo_root/config/dependencies.txt"
hooks_json="$repo_root/hooks/hooks.json"

full_path="$PATH"

minimal_path() {
  # Builds a throwaway PATH with only the given commands symlinked in, so absence of anything
  # else (e.g. jq) is real, not accidental.
  local dir; dir=$(mktemp -d)
  local b
  for b in "$@"; do
    p=$(command -v "$b" 2>/dev/null) && ln -sf "$p" "$dir/"
  done
  printf '%s' "$dir"
}

core_bins="bash git timeout head ls date stat printf mkdir tr pwd sed grep cat dirname mv rm find"

# 1. Healthy PATH: hook mode is silent, exit 0
healthy_dir=$(minimal_path $core_bins jq gh tea npm)
out=$(PATH="$healthy_dir" "$doctor_sh" hook)
rc=$?
[ -z "$out" ] || { echo "FAIL: healthy hook mode produced output: $out"; exit 1; }
[ "$rc" -eq 0 ] || { echo "FAIL: healthy hook mode exit = $rc"; exit 1; }

# 2. Missing jq: hook mode names jq in both systemMessage and additionalContext
nojq_dir=$(minimal_path $core_bins gh tea npm)
out=$(PATH="$nojq_dir" "$doctor_sh" hook)
echo "$out" | grep -q '"systemMessage"' || { echo "FAIL: no systemMessage when jq missing"; exit 1; }
sysmsg=$(printf '%s' "$out" | jq -r '.systemMessage')
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')
[[ "$sysmsg" == *jq* ]] || { echo "FAIL: systemMessage does not name jq: $sysmsg"; exit 1; }
[[ "$ctx" == *jq* ]] || { echo "FAIL: additionalContext does not name jq: $ctx"; exit 1; }

# 3. --json works even with jq missing from PATH (cfq-doctor.sh must not depend on jq)
json=$(PATH="$nojq_dir" "$doctor_sh" check --json)
echo "$json" | jq -e '.missingRequired | index("jq") != null' >/dev/null \
  || { echo "FAIL: check --json (no jq in PATH) does not list jq missing: $json"; exit 1; }
[ "$(jq -r '.ok' <<<"$json")" = "false" ] || { echo "FAIL: check --json ok should be false when jq missing"; exit 1; }

# 4. Optional gh/tea/npm absence does not make core health fail
nooptional_dir=$(minimal_path $core_bins jq)
json=$(PATH="$nooptional_dir" "$doctor_sh" check --json)
[ "$(jq -r '.ok' <<<"$json")" = "true" ] \
  || { echo "FAIL: missing only optional providers should still be ok=true: $json"; exit 1; }
[ "$(jq -r '.missingOptional | sort | join(",")' <<<"$json")" = "gh,npm,tea" ] \
  || { echo "FAIL: missingOptional should list gh,npm,tea: $json"; exit 1; }
out=$(PATH="$nooptional_dir" "$doctor_sh" hook)
[ -z "$out" ] || { echo "FAIL: missing-optional-only PATH should still be hook-silent: $out"; exit 1; }

# 5. Required-command inventory matches what mandatory scripts actually use (focused regression
# check — not full static analysis, just the tokens this batch audited).
for must in bash git jq; do
  grep -qE "^${must}\|required\|" "$inventory" \
    || { echo "FAIL: dependencies.txt missing required entry for $must"; exit 1; }
done
grep -qE '^timeout,gtimeout\|alternative\|' "$inventory" \
  || { echo "FAIL: dependencies.txt missing timeout/gtimeout alternative group"; exit 1; }
for opt in gh tea npm; do
  grep -qE "^${opt}\|optional\|" "$inventory" \
    || { echo "FAIL: dependencies.txt missing optional entry for $opt"; exit 1; }
done

# 6. No package-manager command is ever executed — only offered as a hint string.
marker=$(mktemp -d)
for pm in apt-get brew dnf apk; do
  cat > "$marker/$pm" <<EOF
#!/usr/bin/env bash
echo "INVOKED" >> "$marker/invoked.log"
EOF
  chmod +x "$marker/$pm"
done
pm_dir="$marker:$nojq_dir"
PATH="$pm_dir" "$doctor_sh" check >/dev/null
PATH="$pm_dir" "$doctor_sh" hook >/dev/null
[ ! -f "$marker/invoked.log" ] || { echo "FAIL: a package manager was actually invoked"; exit 1; }
rm -rf "$marker"

# 7. Plugin hook config validates and uses ${CLAUDE_PLUGIN_ROOT}, never an absolute path
PATH="$full_path" jq -e . "$hooks_json" >/dev/null \
  || { echo "FAIL: hooks/hooks.json is not valid JSON"; exit 1; }
cmd=$(PATH="$full_path" jq -r '.hooks.SessionStart[0].hooks[0].command' "$hooks_json")
[[ "$cmd" == '${CLAUDE_PLUGIN_ROOT}'* ]] || { echo "FAIL: hook command does not use \${CLAUDE_PLUGIN_ROOT}: $cmd"; exit 1; }
[[ "$cmd" != /* ]] || { echo "FAIL: hook command is an absolute path: $cmd"; exit 1; }

# 8. Ponytail advisory: installed, mode full (no config) -> appears in optional section, ok stays
# true, exit code unchanged (never a required-dependency failure).
pony_home=$(mktemp -d)
mkdir -p "$pony_home/.claude/plugins/cache/ponytail/ponytail/4.8.4"
json=$(HOME="$pony_home" PATH="$healthy_dir" "$doctor_sh" check --json)
rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL: check --json exit != 0 with ponytail advisory present: $rc"; exit 1; }
[ "$(jq -r '.ok' <<<"$json")" = "true" ] || { echo "FAIL: ponytail advisory should not affect ok: $json"; exit 1; }
[[ "$(jq -r '.ponytailAdvisory' <<<"$json")" == *"full"* ]] \
  || { echo "FAIL: ponytailAdvisory missing/wrong mode: $json"; exit 1; }
text=$(HOME="$pony_home" PATH="$healthy_dir" "$doctor_sh" check)
echo "$text" | grep -q "optional advisory:.*full" \
  || { echo "FAIL: text mode missing ponytail advisory: $text"; exit 1; }
rm -rf "$pony_home"

# 9. Ponytail advisory: installed, mode off -> no advisory at all
pony_home=$(mktemp -d)
mkdir -p "$pony_home/.claude/plugins/cache/ponytail/ponytail/4.8.4" "$pony_home/.config/ponytail"
printf '{"defaultMode":"off"}' > "$pony_home/.config/ponytail/config.json"
json=$(HOME="$pony_home" PATH="$healthy_dir" "$doctor_sh" check --json)
[ "$(jq -r '.ponytailAdvisory' <<<"$json")" = "null" ] \
  || { echo "FAIL: mode off should suppress the advisory: $json"; exit 1; }
text=$(HOME="$pony_home" PATH="$healthy_dir" "$doctor_sh" check)
if echo "$text" | grep -q "optional advisory:"; then
  echo "FAIL: mode off should not print an advisory line: $text"; exit 1
fi
rm -rf "$pony_home"

# 10. Ponytail not installed -> no advisory, even with no plugin cache dir at all
pony_home=$(mktemp -d)
json=$(HOME="$pony_home" PATH="$healthy_dir" "$doctor_sh" check --json)
[ "$(jq -r '.ponytailAdvisory' <<<"$json")" = "null" ] \
  || { echo "FAIL: not-installed should suppress the advisory: $json"; exit 1; }
rm -rf "$pony_home"

echo PASS
