#!/usr/bin/env bash
# Single read-only aggregator for the /cfq dashboard: bundles plugin status (installed + the two
# switches), the cross-repo scan rolled up per repo, and this repo's (or, outside a repo, the
# global) settings-with-sources — the four separate calls the skill used to make — into one JSON
# object. Usage: cfq-dash.sh [<cwd>]
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-dash.sh: jq is required" >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cwd="${1:-$(pwd)}"

runtime_json=$("$script_dir/cfq-runtime.sh" plugins)
if [ "$(jq -r '.status' <<<"$runtime_json")" != "OK" ]; then
  jq -n --argjson rt "$runtime_json" \
    '{status: "RUNTIME_DEGRADED", runtimeDiagnostic: $rt, plugins: null, repos: [], thisRepo: null, settings: []}'
  exit 0
fi
plugins_list=$(jq -c '.plugins' <<<"$runtime_json")

repo=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || true)
repo_args=(); [ -n "$repo" ] && repo_args=(--repo "$repo")

settings_src=$("$script_dir/cfq-settings.sh" list "${repo_args[@]}" --sources)

# One env-stripped re-read of the same tiers, only when at least one key is actually
# env-overridden — gives every masked file value in one call, never one per key.
masked_src="{}"
if [ "$(jq '[.[] | select(.source | startswith("env"))] | length' <<<"$settings_src")" -gt 0 ]; then
  masked_src=$(env -i HOME="$HOME" PATH="$PATH" "$script_dir/cfq-settings.sh" list "${repo_args[@]}" --sources)
fi

settings_json=$(jq -c --argjson masked "$masked_src" '
  def marker:
    if . == "default" then "D" elif . == "global" then "G" elif . == "repo" then "R" else "E" end;
  [ to_entries[] | . as $e | {
      key: $e.key, value: $e.value.value, source: $e.value.source, marker: ($e.value.source | marker)
    } + (if ($e.value.source | startswith("env")) then
           {maskedValue: $masked[$e.key].value, maskedSource: $masked[$e.key].source}
         else {} end)
  ]
' <<<"$settings_src")

use_grill=$(jq -r '.useMattpocockGrilling.value' <<<"$settings_src")
use_pony=$(jq -r '.usePonytailAudit.value' <<<"$settings_src")
has_mp=$(jq -c 'index("mattpocock-skills") != null' <<<"$plugins_list")
has_pt=$(jq -c 'index("ponytail") != null' <<<"$plugins_list")
plugins_obj=$(jq -n --argjson mp "$has_mp" --argjson pt "$has_pt" --argjson g "$use_grill" --argjson p "$use_pony" \
  '{mattpocock: $mp, ponytail: $pt, useMattpocockGrilling: $g, usePonytailAudit: $p}')

scan_json=$("$script_dir/cfq-scan.sh")

# Repo-level rollup: batch counts (open = not yet archived, done = moved to impl/done/) plus the
# most severe status among the repo's batches — aggregated from counters the scan already
# computed, never recounted from disk.
repos_json=$(jq -c '
  def rst($b):
    if ([$b[] | .blocked] | any) then "BLOCKED"
    elif ([$b[] | .planning] | any) then "PLANNING"
    elif ([$b[] | .inProgress] | any) then "IN_PROGRESS"
    else "OK" end;
  [ .repos[] | {
      path, name: (.path | split("/") | last), plan, todo,
      open: ([.batches[] | select(.archived == false)] | length),
      done: ([.batches[] | select(.archived == true)] | length),
      status: rst(.batches)
    } ]
' <<<"$scan_json")

this_repo_json="null"
if [ -n "$repo" ]; then
  this_repo_json=$(jq -c --arg p "$repo" '
    def bst:
      if .blocked then "BLOCKED" elif .planning then "PLANNING"
      elif .inProgress then "IN_PROGRESS" else "OK" end;
    ([.repos[] | select(.path == $p)][0]) as $r
    | if $r == null then null
      else { path: $r.path, name: ($r.path | split("/") | last),
             batches: [ $r.batches[] | {name, priority, open, done, status: bst} ] }
      end
  ' <<<"$scan_json")
fi

status="OK"
if [ "$this_repo_json" != "null" ] \
   && [ "$(jq '[.batches[] | select(.status == "IN_PROGRESS")] | length' <<<"$this_repo_json")" -gt 1 ]; then
  status="MULTIPLE_IN_PROGRESS"
elif [ "$(jq 'length' <<<"$repos_json")" -eq 0 ]; then
  status="NO_REPO"
fi

jq -n --arg status "$status" --argjson plugins "$plugins_obj" --argjson repos "$repos_json" \
  --argjson thisRepo "$this_repo_json" --argjson settings "$settings_json" \
  '{status: $status, plugins: $plugins, repos: $repos, thisRepo: $thisRepo, settings: $settings}'
