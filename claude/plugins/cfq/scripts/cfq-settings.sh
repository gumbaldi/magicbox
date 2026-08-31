#!/usr/bin/env bash
# Manages cfq settings: $HOME/.claude/code-for-queue/settings.json (global) and, per repo,
# <repo>/.claude/cfq/settings.json (repo-scoped overrides).
# Usage: cfq-settings.sh list [--repo <path>] [--sources]
#        cfq-settings.sh get [--repo <path>] [--source] <key>
#        cfq-settings.sh set [--repo <path>] <key> <value>
#        cfq-settings.sh unset [--repo <path>] <key>
#        cfq-settings.sh describe [<key>]
#        cfq-settings.sh migrate <repo-root>
#        cfq-settings.sh state get <key> | state set <key> <value>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-settings.sh: jq is required" >&2; exit 1; }

dir="$HOME/.claude/code-for-queue"
settings="$dir/settings.json"
state_file="$dir/state.json"

# Single source of truth for every key: type, default, scope, env mapping, description, plus
# type-specific validation data (min/max for int, values for enum, pattern for string, shape
# for object). list/get/set/unset/describe and env overrides all walk this generically — a new
# key is one entry here, never a second hand-written case arm.
schema='{
  "grillMode": {"type":"enum","default":"stepwise","values":["stepwise","classic"],"scope":["global","repo"],"env":"CFQ_GRILL_MODE","description":"Interview style for /pfq: stepwise (one question at a time) or classic."},
  "planModels": {"type":"array","default":["opus","fable"],"scope":["global","repo"],"env":"CFQ_PLAN_MODELS","description":"Models /pfq is allowed to run under."},
  "implModels": {"type":"array","default":["sonnet"],"scope":["global","repo"],"env":"CFQ_IMPL_MODELS","description":"Models /ifq is allowed to run under."},
  "planExploreModel": {"type":"string","default":"haiku","scope":["global","repo"],"env":"CFQ_PLAN_EXPLORE_MODEL","description":"Model used for /pfq exploratory sub-agent research."},
  "implExploreModel": {"type":"string","default":"haiku","scope":["global","repo"],"env":"CFQ_IMPL_EXPLORE_MODEL","description":"Model used for /ifq exploratory sub-agent research and mechanical test-run delegation."},
  "allowAnyModel": {"type":"bool","default":false,"scope":["global","repo"],"env":"CFQ_ALLOW_ANY_MODEL","description":"Skip the implModels/planModels gate entirely."},
  "scanRoots": {"type":"array","default":["~/git"],"scope":["global"],"env":"CFQ_SCAN_ROOTS","description":"Root directories cfq-scan.sh searches for repos with a queue."},
  "useMattpocockGrilling": {"type":"bool","default":true,"scope":["global","repo"],"env":"CFQ_USE_MATTPOCOCK","description":"Use the mattpocock-skills grilling skill instead of the built-in one, when installed."},
  "usePonytailAudit": {"type":"bool","default":true,"scope":["global","repo"],"env":"CFQ_USE_PONYTAIL","description":"Run the optional ponytail-audit cleanup task during maintenance."},
  "codeLanguage": {"type":"string","default":"en","pattern":"^[A-Za-z][A-Za-z-]*$","scope":["global","repo"],"env":"CFQ_CODE_LANGUAGE","description":"Language of everything executed or read as an instruction: code, comments, commit messages, README, CLAUDE.md, SKILL.md."},
  "docLanguages": {"type":"array","default":[],"scope":["global","repo"],"env":"CFQ_DOC_LANGUAGES","description":"Additional languages kept under docs/<lang>/; empty means documentation follows codeLanguage alone."},
  "docLevel": {"type":"enum","default":"minimal","values":["minimal","standard","full"],"scope":["global","repo"],"env":"CFQ_DOC_LEVEL","description":"How much documentation a repo keeps: minimal (README only), standard, or full."},
  "maintenanceEvery": {"type":"int","default":50,"min":0,"scope":["global","repo"],"env":"CFQ_MAINTENANCE_EVERY","description":"Commits since the last maintenance run before the next one is due; 0 disables maintenance entirely."},
  "branchPerBatch": {"type":"bool","default":true,"scope":["global","repo"],"env":null,"description":"Create a dedicated branch per implementation batch instead of committing to the checked-out branch."},
  "changelogFile": {"type":"string","default":".claude/cfq/changelog.yml","scope":["global","repo"],"env":null,"description":"Filename of the per-repo changelog cfq-changelog.sh writes to."},
  "htmlReport": {"type":"bool","default":false,"scope":["global","repo"],"env":null,"description":"Render an HTML report at batch completion in addition to the terminal summary."},
  "planBlockedPlugins": {"type":"array","default":["superpowers"],"scope":["global","repo"],"env":null,"description":"Plugins /pfq must never call, even indirectly."},
  "implBlockedPlugins": {"type":"array","default":["superpowers"],"scope":["global","repo"],"env":null,"description":"Plugins /ifq must never call, even indirectly."},
  "telemetrySyncRepo": {"type":"string","default":"","pattern":"^($|/.*)$","scope":["global","repo"],"env":"CFQ_TELEMETRY_SYNC_REPO","description":"Absolute path of a repo telemetry is additionally synced to; empty disables sync."},
  "stopUsed": {"type":"int","default":100000,"min":-1,"scope":["global","repo"],"env":"CFQ_STOP_USED","description":"Absolute context tokens (input+cache_read+cache_creation) at which /ifq hands off instead of starting another phase; 0 means hand off after every phase, -1 means never stop for this reason."},
  "onePhasePerSession": {"type":"bool","default":true,"scope":["global","repo"],"env":"CFQ_ONE_PHASE_PER_SESSION","description":"When true, /ifq always hands off after one phase instead of continuing automatically while the context gate allows it."},
  "sessionStaleSeconds": {"type":"int","default":1800,"min":1,"scope":["global","repo"],"env":"CFQ_SESSION_STALE_SECONDS","description":"Seconds since a session transcript was last touched before it is considered stale (lock takeover, resume staleness)."},
  "ctxWindowLimits": {"type":"object","shape":{"default":"int","large":"object"},"default":{"default":200000,"large":{"models":["claude-opus-5","claude-sonnet-5","claude-opus-4-8"],"limit":1000000}},"scope":["global","repo"],"env":null,"description":"Context-window size in tokens per model, keyed by whether the model gets the large window."},
  "securityTimeoutSeconds": {"type":"int","default":30,"min":1,"scope":["global"],"env":null,"description":"Timeout in seconds for the batch-completion security scan."},
  "securityFindingsCap": {"type":"int","default":20,"min":1,"scope":["global"],"env":null,"description":"Maximum number of security findings surfaced per batch-completion scan."},
  "gitStatePolicy": {"type":"enum","default":"local","values":["local","trackable"],"scope":["global","repo"],"env":null,"description":"Whether repo-local cfq workflow state is Git-excluded locally (local) or left to normal repository tracking (trackable)."},
  "i18nExcludePatterns": {"type":"array","default":["*/locales/*","*/locale/*","*/i18n/*","*/lang/*","*/translations/*"],"scope":["global","repo"],"env":null,"description":"Git pathspec exclusions applied to the /ifq language-prose sample — directories that intentionally hold multiple languages (i18n/locale resource files), never judged as a codeLanguage violation."},
  "reportDir": {"type":"string","default":"","pattern":"^($|/.*)$","scope":["global","repo"],"env":"CFQ_REPORT_DIR","description":"Absolute path of the directory HTML reports are collected in; empty writes report.html into the batch directory instead."},
  "planExploreModelComplex": {"type":"string","default":"sonnet","scope":["global","repo"],"env":"CFQ_PLAN_EXPLORE_MODEL_COMPLEX","description":"Model for /pfq Explore agents whose task is to judge rather than to locate."},
  "implExploreModelComplex": {"type":"string","default":"sonnet","scope":["global","repo"],"env":"CFQ_IMPL_EXPLORE_MODEL_COMPLEX","description":"Model for /ifq Explore agents whose task is to judge rather than to locate."}
}'

defaults=$(jq -c 'map_values(.default)' <<<"$schema")

ensure() {
  mkdir -p "$dir"
  [ -f "$settings" ] || printf '%s\n' "$defaults" > "$settings"
}

ensure_state() {
  mkdir -p "$dir"
  [ -f "$state_file" ] || printf '{}\n' > "$state_file"
}

write() {
  local target="$1" tmp="$1.tmp"
  cat > "$tmp"
  mv "$tmp" "$target"
}

# Overlays one JSON file's known keys onto a base JSON object. Object-typed keys merge
# recursively (a partial override must not erase sibling fields); everything else replaces
# fully. Missing file -> base unchanged.
merge_tier_file() {
  local base="$1" file="$2"
  [ -f "$file" ] || { printf '%s' "$base"; return; }
  jq -n --argjson b "$base" --argjson s "$schema" --slurpfile f "$file" '
    def merge_tier(base; overlay; schema):
      reduce (overlay | keys[]) as $k (base;
        if (schema[$k].type // "") == "object" then .[$k] = ((.[$k] // {}) * overlay[$k])
        else .[$k] = overlay[$k] end);
    merge_tier($b; ($f[0] // {}) | with_entries(select(.key | in($b))); $s)
  '
}

# Three tiers below env, highest wins: <repo>/.claude/cfq/settings.json (if repo_path given) >
# $HOME/.claude/code-for-queue/settings.json > schema default. Assumes ensure() already ran.
merged_tiers() {
  local repo_path="${1:-}" base="$defaults"
  base=$(merge_tier_file "$base" "$settings")
  if [ -n "$repo_path" ]; then
    base=$(merge_tier_file "$base" "$repo_path/.claude/cfq/settings.json")
  fi
  printf '%s' "$base"
}

# Applies env-var overrides on top of whatever tiered JSON is piped in, walking $schema
# generically. Precedence: env > everything piped in.
with_overrides() {
  local json val env_name type digits
  json="$(cat)"
  while IFS= read -r key; do
    env_name=$(jq -r --arg k "$key" '.[$k].env // empty' <<<"$schema")
    [ -n "$env_name" ] || continue
    val="${!env_name:-}"
    [ -n "$val" ] || continue
    type=$(jq -r --arg k "$key" '.[$k].type' <<<"$schema")
    case "$type" in
      bool)
        case "$val" in
          1) json=$(jq --arg k "$key" '.[$k] = true' <<<"$json") ;;
          *) json=$(jq --arg k "$key" '.[$k] = false' <<<"$json") ;;
        esac
        ;;
      int)
        digits="$val"; [ "${digits#-}" = "$digits" ] || digits="${digits#-}"
        case "$digits" in
          ''|*[!0-9]*) ;; # malformed — skip, leaves tiered value in place
          *) json=$(jq --arg k "$key" --argjson v "$val" '.[$k] = $v' <<<"$json") ;;
        esac
        ;;
      array)
        json=$(jq --arg k "$key" --arg v "$val" '.[$k] = ($v | split(","))' <<<"$json")
        ;;
      object)
        # No key currently maps an env var to an object type; recursive merge is here so a
        # future one is handled without touching this loop again.
        if jq -e . >/dev/null 2>&1 <<<"$val"; then
          json=$(jq --arg k "$key" --argjson v "$val" '.[$k] = (.[$k] * $v)' <<<"$json")
        fi
        ;;
      enum|string)
        json=$(jq --arg k "$key" --arg v "$val" '.[$k] = $v' <<<"$json")
        ;;
    esac
  done < <(jq -r 'keys[]' <<<"$schema")
  printf '%s' "$json"
}

# Determines which tier actually supplied $key's final value: env:process / env:repo-legacy /
# repo / global / default. $global_existed reflects whether the global file existed *before*
# this invocation's ensure() ran (a fresh file, just materialized with defaults, still counts
# as "default").
key_source() {
  local key="$1" repo_path="$2" global_existed="$3" base_json="$4" final_json="$5"
  local env_name same legacy_settings legacy_val
  env_name=$(jq -r --arg k "$key" '.[$k].env // empty' <<<"$schema")
  if [ -n "$env_name" ]; then
    same=$(jq -nr --argjson a "$base_json" --argjson b "$final_json" --arg k "$key" '($a[$k] == $b[$k])')
    if [ "$same" = "false" ]; then
      legacy_settings="$repo_path/.claude/settings.json"
      if [ -n "$repo_path" ] && [ -f "$legacy_settings" ]; then
        legacy_val=$(jq -r --arg e "$env_name" '.env[$e] // empty' "$legacy_settings" 2>/dev/null || true)
        if [ -n "$legacy_val" ] && [ "$legacy_val" = "${!env_name:-}" ]; then
          echo "env:repo-legacy"; return
        fi
      fi
      echo "env:process"; return
    fi
  fi
  if [ -n "$repo_path" ] && [ -f "$repo_path/.claude/cfq/settings.json" ] \
     && jq -e --arg k "$key" 'has($k)' "$repo_path/.claude/cfq/settings.json" >/dev/null 2>&1; then
    echo "repo"; return
  fi
  if [ "$global_existed" = "1" ]; then
    echo "global"
  else
    echo "default"
  fi
}

cmd="${1:-}"
shift || true

repo_path=""
want_source=0
positional=()
while [ $# -gt 0 ]; do
  case "$1" in
    --global) shift ;;
    --repo) repo_path="${2:?--repo requires a path}"; shift 2 ;;
    --source|--sources) want_source=1; shift ;;
    *) positional+=("$1"); shift ;;
  esac
done
set -- "${positional[@]}"

case "$cmd" in
  list)
    global_existed=$([ -f "$settings" ] && echo 1 || echo 0)
    ensure
    base_json=$(merged_tiers "$repo_path")
    final_json=$(printf '%s' "$base_json" | with_overrides)
    if [ "$want_source" = "1" ]; then
      out="{}"
      while IFS= read -r k; do
        src=$(key_source "$k" "$repo_path" "$global_existed" "$base_json" "$final_json")
        out=$(jq --arg k "$k" --arg s "$src" --argjson fj "$final_json" '.[$k] = {value: $fj[$k], source: $s}' <<<"$out")
      done < <(jq -r 'keys[]' <<<"$schema")
      printf '%s\n' "$out"
    else
      printf '%s\n' "$final_json"
    fi
    ;;
  get)
    key="${1:?usage: cfq-settings.sh get [--repo <path>] [--source] <key>}"
    global_existed=$([ -f "$settings" ] && echo 1 || echo 0)
    ensure
    base_json=$(merged_tiers "$repo_path")
    final_json=$(printf '%s' "$base_json" | with_overrides)
    if [ "$want_source" = "1" ]; then
      src=$(key_source "$key" "$repo_path" "$global_existed" "$base_json" "$final_json")
      jq -c --arg k "$key" --arg s "$src" '{value: .[$k], source: $s}' <<<"$final_json"
    else
      type=$(jq -r --arg k "$key" '.[$k].type // empty' <<<"$schema")
      jq -r --arg k "$key" --arg t "$type" '
        .[$k] as $v
        | if $t == "array" then ($v | join(","))
          elif $t == "object" then ($v | tojson)
          else ($v | tostring)
          end
      ' <<<"$final_json"
    fi
    ;;
  set)
    key="${1:?usage: cfq-settings.sh set [--repo <path>] <key> <value>}"
    val="${2?usage: cfq-settings.sh set [--repo <path>] <key> <value>}"
    if ! jq -e --arg k "$key" 'has($k)' <<<"$schema" >/dev/null; then
      echo "cfq-settings.sh: unknown key '$key'" >&2
      exit 1
    fi
    if [ -n "$repo_path" ]; then
      if ! jq -e --arg k "$key" '.[$k].scope | index("repo") != null' <<<"$schema" >/dev/null; then
        echo "cfq-settings.sh: '$key' cannot be set per repo (scope is global-only)" >&2
        exit 1
      fi
      mkdir -p "$repo_path/.claude/cfq"
      target="$repo_path/.claude/cfq/settings.json"
      [ -f "$target" ] || printf '{}\n' > "$target"
    else
      ensure
      merged_tiers "" > "$settings.tmp" && mv "$settings.tmp" "$settings"
      target="$settings"
    fi
    type=$(jq -r --arg k "$key" '.[$k].type' <<<"$schema")
    case "$type" in
      bool)
        case "$val" in
          true|false) jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$target" | write "$target" ;;
          *) echo "cfq-settings.sh: '$key' must be true or false" >&2; exit 1 ;;
        esac
        ;;
      int)
        digits="$val"; [ "${digits#-}" = "$digits" ] || digits="${digits#-}"
        case "$digits" in
          ''|*[!0-9]*) echo "cfq-settings.sh: '$key' must be an integer" >&2; exit 1 ;;
        esac
        min=$(jq -r --arg k "$key" '.[$k].min // empty' <<<"$schema")
        max=$(jq -r --arg k "$key" '.[$k].max // empty' <<<"$schema")
        if [ -n "$min" ] && [ "$val" -lt "$min" ]; then
          echo "cfq-settings.sh: '$key' must be >= $min" >&2; exit 1
        fi
        if [ -n "$max" ] && [ "$val" -gt "$max" ]; then
          echo "cfq-settings.sh: '$key' must be <= $max" >&2; exit 1
        fi
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$target" | write "$target"
        ;;
      enum)
        if jq -e --arg k "$key" --arg v "$val" '.[$k].values | index($v) != null' <<<"$schema" >/dev/null; then
          jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$target" | write "$target"
        else
          allowed=$(jq -r --arg k "$key" '.[$k].values | join(", ")' <<<"$schema")
          echo "cfq-settings.sh: '$key' must be one of $allowed" >&2
          exit 1
        fi
        ;;
      string)
        pattern=$(jq -r --arg k "$key" '.[$k].pattern // empty' <<<"$schema")
        if [ -n "$pattern" ] && ! [[ "$val" =~ $pattern ]]; then
          echo "cfq-settings.sh: '$key' does not match the required pattern" >&2
          exit 1
        fi
        jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$target" | write "$target"
        ;;
      array)
        jq --arg k "$key" --arg v "$val" '.[$k] = ($v | split(","))' "$target" | write "$target"
        ;;
      object)
        if ! jq -e . >/dev/null 2>&1 <<<"$val"; then
          echo "cfq-settings.sh: '$key' must be valid JSON" >&2
          exit 1
        fi
        shape=$(jq -c --arg k "$key" '.[$k].shape // {}' <<<"$schema")
        if ! jq -e --argjson v "$val" --argjson shape "$shape" '
          ($v | keys) as $vk | ($shape | keys) as $allowed | ($vk - $allowed) | length == 0
        ' >/dev/null 2>&1; then
          echo "cfq-settings.sh: '$key' has unknown fields" >&2
          exit 1
        fi
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$target" | write "$target"
        ;;
    esac
    ;;
  unset)
    key="${1:?usage: cfq-settings.sh unset [--repo <path>] <key>}"
    if ! jq -e --arg k "$key" 'has($k)' <<<"$schema" >/dev/null; then
      echo "cfq-settings.sh: unknown key '$key'" >&2
      exit 1
    fi
    if [ -n "$repo_path" ]; then
      target="$repo_path/.claude/cfq/settings.json"
      [ -f "$target" ] || exit 0
    else
      ensure
      target="$settings"
    fi
    jq --arg k "$key" 'del(.[$k])' "$target" | write "$target"
    ;;
  state)
    sub="${1:?usage: cfq-settings.sh state get <key> | state set <key> <value>}"
    shift || true
    ensure_state
    case "$sub" in
      get)
        key="${1:?usage: cfq-settings.sh state get <key>}"
        jq -r --arg k "$key" '(.[$k] // null) | tostring' "$state_file"
        ;;
      set)
        key="${1:?usage: cfq-settings.sh state set <key> <value>}"
        val="${2?usage: cfq-settings.sh state set <key> <value>}"
        if ! jq -e . >/dev/null 2>&1 <<<"$val"; then
          echo "cfq-settings.sh: state value must be valid JSON" >&2
          exit 1
        fi
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$state_file" | write "$state_file"
        ;;
      *)
        echo "usage: cfq-settings.sh state get <key> | state set <key> <value>" >&2
        exit 1
        ;;
    esac
    ;;
  describe)
    key="${1:-}"
    if [ -n "$key" ]; then
      jq --arg k "$key" '.[$k] | {type, default, scope, env, description}' <<<"$schema"
    else
      jq 'map_values({type, default, scope, env, description})' <<<"$schema"
    fi
    ;;
  migrate)
    repo_root="${1:?usage: cfq-settings.sh migrate <repo-root>}"
    legacy="$repo_root/.claude/settings.json"
    if [ ! -f "$legacy" ]; then
      echo "cfq-settings.sh: no $legacy found, nothing to migrate"
      exit 0
    fi
    migrated=0
    while IFS=$'\t' read -r schema_key env_name; do
      val=$(jq -r --arg e "$env_name" '.env[$e] // empty' "$legacy")
      [ -n "$val" ] || continue
      bash "$0" set --repo "$repo_root" "$schema_key" "$val"
      echo "migrated $schema_key = $val"
      migrated=$((migrated + 1))
    done < <(jq -r 'to_entries[] | select(.value.env != null) | [.key, .value.env] | @tsv' <<<"$schema")
    echo "done — $migrated key(s) migrated into $repo_root/.claude/cfq/settings.json; original $legacy left untouched"
    ;;
  *)
    echo "usage: cfq-settings.sh list [--repo <path>] [--sources] | get [--repo <path>] [--source] <key> | set [--repo <path>] <key> <value> | unset [--repo <path>] <key> | describe [<key>] | migrate <repo-root> | state get <key> | state set <key> <value>" >&2
    exit 1
    ;;
esac
