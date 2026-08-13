#!/usr/bin/env bash
# Manages ~/.claude/code-for-queue/settings.json — user-configurable cfq parameters.
# Usage: cfq-settings.sh list | get <key> | set <key> <value>
set -eu

command -v jq >/dev/null 2>&1 || { echo "cfq-settings.sh: jq is required" >&2; exit 1; }

dir="$HOME/.claude/code-for-queue"
settings="$dir/settings.json"

defaults='{
  "grillMode": "stepwise",
  "planModels": ["opus", "fable"],
  "implModels": ["sonnet"],
  "allowAnyModel": false,
  "stopPct": 50,
  "scanRoots": ["~/git"],
  "useMattpocockGrilling": false,
  "usePonytailAudit": false,
  "planPreferredPlugins": [],
  "planBlockedPlugins": ["superpowers"],
  "implPreferredPlugins": [],
  "implBlockedPlugins": ["superpowers"],
  "setupDone": false
}'

ensure() {
  mkdir -p "$dir"
  [ -f "$settings" ] || printf '%s\n' "$defaults" > "$settings"
}

write() {
  local tmp="$settings.tmp"
  cat > "$tmp"
  mv "$tmp" "$settings"
}

# Applies env-var overrides on top of the settings file. Precedence: env > file > default.
with_overrides() {
  jq \
    --arg planModels "${CFQ_PLAN_MODELS:-}" \
    --arg implModels "${CFQ_IMPL_MODELS:-}" \
    --arg allowAnyModel "${CFQ_ALLOW_ANY_MODEL:-}" \
    --arg stopPct "${CFQ_STOP_PCT:-}" \
    --arg scanRoots "${CFQ_SCAN_ROOTS:-}" \
    --arg grillMode "${CFQ_GRILL_MODE:-}" \
    --arg useMattpocockGrilling "${CFQ_USE_MATTPOCOCK:-}" \
    --arg usePonytailAudit "${CFQ_USE_PONYTAIL:-}" \
    '
    if $planModels != "" then .planModels = ($planModels | split(",")) else . end
    | if $implModels != "" then .implModels = ($implModels | split(",")) else . end
    | if $allowAnyModel != "" then .allowAnyModel = ($allowAnyModel == "1") else . end
    | if $stopPct != "" then .stopPct = ($stopPct | tonumber) else . end
    | if $scanRoots != "" then .scanRoots = ($scanRoots | split(":")) else . end
    | if $grillMode != "" then .grillMode = $grillMode else . end
    | if $useMattpocockGrilling != "" then .useMattpocockGrilling = ($useMattpocockGrilling == "1") else . end
    | if $usePonytailAudit != "" then .usePonytailAudit = ($usePonytailAudit == "1") else . end
    '
}

cmd="${1:-}"
case "$cmd" in
  list)
    ensure
    with_overrides < "$settings"
    ;;
  get)
    key="${2:?usage: cfq-settings.sh get <key>}"
    ensure
    with_overrides < "$settings" | jq -r --arg k "$key" '
      .[$k] | if type == "array" then join(",") else tostring end
    '
    ;;
  set)
    key="${2:?usage: cfq-settings.sh set <key> <value>}"
    val="${3:?usage: cfq-settings.sh set <key> <value>}"
    ensure
    if ! jq -e --arg k "$key" 'has($k)' "$settings" >/dev/null; then
      echo "cfq-settings.sh: unknown key '$key'" >&2
      exit 1
    fi
    case "$key" in
      allowAnyModel|useMattpocockGrilling|usePonytailAudit|setupDone)
        case "$val" in
          true|false) jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: '$key' must be true or false" >&2; exit 1 ;;
        esac
        ;;
      stopPct)
        case "$val" in
          ''|*[!0-9]*) echo "cfq-settings.sh: 'stopPct' must be 1-99" >&2; exit 1 ;;
        esac
        if [ "$val" -lt 1 ] || [ "$val" -gt 99 ]; then
          echo "cfq-settings.sh: 'stopPct' must be 1-99" >&2
          exit 1
        fi
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write
        ;;
      grillMode)
        case "$val" in
          stepwise|classic) jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: 'grillMode' must be stepwise or classic" >&2; exit 1 ;;
        esac
        ;;
      planModels|implModels|scanRoots|planPreferredPlugins|planBlockedPlugins|implPreferredPlugins|implBlockedPlugins)
        jq --arg k "$key" --arg v "$val" '.[$k] = ($v | split(","))' "$settings" | write
        ;;
      *)
        jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write
        ;;
    esac
    ;;
  *)
    echo "usage: cfq-settings.sh list | get <key> | set <key> <value>" >&2
    exit 1
    ;;
esac
