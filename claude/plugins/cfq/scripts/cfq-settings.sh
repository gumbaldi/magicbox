#!/usr/bin/env bash
# Manages ~/.claude/code-for-queue/settings.json — user-configurable cfq parameters.
# Usage: cfq-settings.sh list | get <key> | set <key> <value>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-settings.sh: jq is required" >&2; exit 1; }

dir="$HOME/.claude/code-for-queue"
settings="$dir/settings.json"

# Single source of truth for every key: type, default, scope, env mapping, plus
# type-specific validation data (min/max for int, values for enum, pattern for
# string, shape for object). list/get/set and env overrides all walk this generically
# — a new key is one entry here, never a second hand-written case arm.
schema='{
  "grillMode": {"type":"enum","default":"stepwise","values":["stepwise","classic"],"scope":["global","repo"],"env":"CFQ_GRILL_MODE"},
  "planModels": {"type":"array","default":["opus","fable"],"scope":["global","repo"],"env":"CFQ_PLAN_MODELS"},
  "implModels": {"type":"array","default":["sonnet"],"scope":["global","repo"],"env":"CFQ_IMPL_MODELS"},
  "planExploreModel": {"type":"string","default":"haiku","scope":["global","repo"],"env":"CFQ_PLAN_EXPLORE_MODEL"},
  "allowAnyModel": {"type":"bool","default":false,"scope":["global","repo"],"env":"CFQ_ALLOW_ANY_MODEL"},
  "scanRoots": {"type":"array","default":["~/git"],"scope":["global","repo"],"env":"CFQ_SCAN_ROOTS"},
  "useMattpocockGrilling": {"type":"bool","default":false,"scope":["global","repo"],"env":"CFQ_USE_MATTPOCOCK"},
  "usePonytailAudit": {"type":"bool","default":false,"scope":["global","repo"],"env":"CFQ_USE_PONYTAIL"},
  "codeLanguage": {"type":"string","default":"en","pattern":"^[A-Za-z][A-Za-z-]*$","scope":["global","repo"],"env":"CFQ_CODE_LANGUAGE"},
  "docLanguages": {"type":"array","default":[],"scope":["global","repo"],"env":"CFQ_DOC_LANGUAGES"},
  "docLevel": {"type":"enum","default":"minimal","values":["minimal","standard","full"],"scope":["global","repo"],"env":"CFQ_DOC_LEVEL"},
  "maintenanceEvery": {"type":"int","default":50,"min":0,"scope":["global","repo"],"env":"CFQ_MAINTENANCE_EVERY"},
  "branchPerBatch": {"type":"bool","default":true,"scope":["global","repo"],"env":null},
  "changelogFile": {"type":"string","default":"cfq.changelog.yml","scope":["global","repo"],"env":null},
  "htmlReport": {"type":"bool","default":false,"scope":["global","repo"],"env":null},
  "planBlockedPlugins": {"type":"array","default":["superpowers"],"scope":["global","repo"],"env":null},
  "implBlockedPlugins": {"type":"array","default":["superpowers"],"scope":["global","repo"],"env":null},
  "telemetrySyncRepo": {"type":"string","default":"","pattern":"^($|/.*)$","scope":["global","repo"],"env":"CFQ_TELEMETRY_SYNC_REPO"},
  "setupDone": {"type":"bool","default":false,"scope":["global"],"env":null},
  "stopPct": {"type":"int","default":60,"min":0,"max":100,"scope":["global","repo"],"env":"CFQ_STOP_PCT"},
  "phaseContextGrowth": {"type":"object","shape":{"S":"int","M":"int","L":"int"},"default":{"S":7,"M":15,"L":25},"scope":["global","repo"],"env":null},
  "sessionStaleSeconds": {"type":"int","default":1800,"min":1,"scope":["global","repo"],"env":"CFQ_SESSION_STALE_SECONDS"},
  "ctxWindowLimits": {"type":"object","shape":{"default":"int","large":"object"},"default":{"default":200000,"large":{"models":["claude-opus-5","claude-sonnet-5","claude-opus-4-8"],"limit":1000000}},"scope":["global","repo"],"env":null},
  "securityTimeoutSeconds": {"type":"int","default":30,"min":1,"scope":["global"],"env":null},
  "securityFindingsCap": {"type":"int","default":20,"min":1,"scope":["global"],"env":null},
  "gitStatePolicy": {"type":"enum","default":"local","values":["local","trackable"],"scope":["global","repo"],"env":null}
}'

defaults=$(jq -c 'map_values(.default)' <<<"$schema")

ensure() {
  mkdir -p "$dir"
  [ -f "$settings" ] || printf '%s\n' "$defaults" > "$settings"
}

write() {
  local tmp="$settings.tmp"
  cat > "$tmp"
  mv "$tmp" "$settings"
}

# Defaults as the base, the file layered on top, unknown keys dropped. This way newly
# introduced keys reach existing installations too, and removed ones simply disappear.
merged() {
  jq -n --argjson d "$defaults" --slurpfile f "$settings" '
    ($d + ($f[0] // {})) | with_entries(select(.key | in($d)))
  '
}

# Applies env-var overrides on top of the settings file, walking $schema generically.
# Precedence: env > file > default.
with_overrides() {
  local json val env_name type
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
        case "$val" in
          ''|*[!0-9]*) ;; # malformed — skip, leaves file/default value in place
          *) json=$(jq --arg k "$key" --argjson v "$val" '.[$k] = $v' <<<"$json") ;;
        esac
        ;;
      array)
        json=$(jq --arg k "$key" --arg v "$val" '.[$k] = ($v | split(","))' <<<"$json")
        ;;
      object)
        # No key currently maps an env var to an object type; recursive merge is here
        # so a future one is handled without touching this loop again.
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

cmd="${1:-}"
case "$cmd" in
  list)
    ensure
    merged | with_overrides
    ;;
  get)
    key="${2:?usage: cfq-settings.sh get <key>}"
    ensure
    type=$(jq -r --arg k "$key" '.[$k].type // empty' <<<"$schema")
    merged | with_overrides | jq -r --arg k "$key" --arg t "$type" '
      .[$k] as $v
      | if $t == "array" then ($v | join(","))
        elif $t == "object" then ($v | tojson)
        else ($v | tostring)
        end
    '
    ;;
  set)
    key="${2:?usage: cfq-settings.sh set <key> <value>}"
    val="${3?usage: cfq-settings.sh set <key> <value>}"
    ensure
    merged > "$settings.tmp" && mv "$settings.tmp" "$settings"
    if ! jq -e --arg k "$key" 'has($k)' <<<"$schema" >/dev/null; then
      echo "cfq-settings.sh: unknown key '$key'" >&2
      exit 1
    fi
    type=$(jq -r --arg k "$key" '.[$k].type' <<<"$schema")
    case "$type" in
      bool)
        case "$val" in
          true|false) jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: '$key' must be true or false" >&2; exit 1 ;;
        esac
        ;;
      int)
        case "$val" in
          ''|*[!0-9]*) echo "cfq-settings.sh: '$key' must be a non-negative integer" >&2; exit 1 ;;
        esac
        min=$(jq -r --arg k "$key" '.[$k].min // empty' <<<"$schema")
        max=$(jq -r --arg k "$key" '.[$k].max // empty' <<<"$schema")
        if [ -n "$min" ] && [ "$val" -lt "$min" ]; then
          echo "cfq-settings.sh: '$key' must be >= $min" >&2; exit 1
        fi
        if [ -n "$max" ] && [ "$val" -gt "$max" ]; then
          echo "cfq-settings.sh: '$key' must be <= $max" >&2; exit 1
        fi
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write
        ;;
      enum)
        if jq -e --arg k "$key" --arg v "$val" '.[$k].values | index($v) != null' <<<"$schema" >/dev/null; then
          jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write
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
        jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write
        ;;
      array)
        jq --arg k "$key" --arg v "$val" '.[$k] = ($v | split(","))' "$settings" | write
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
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write
        ;;
    esac
    ;;
  *)
    echo "usage: cfq-settings.sh list | get <key> | set <key> <value>" >&2
    exit 1
    ;;
esac
