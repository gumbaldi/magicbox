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
  "stopPct": 40,
  "scanRoots": ["~/git"],
  "useMattpocockGrilling": false,
  "usePonytailAudit": false,
  "codeLanguage": "en",
  "docLanguages": [],
  "docLevel": "minimal",
  "maintenanceEvery": 50,
  "branchPerBatch": true,
  "changelogFile": "cfq.changelog.yml",
  "htmlReport": false,
  "planBlockedPlugins": ["superpowers"],
  "implBlockedPlugins": ["superpowers"],
  "telemetrySyncRepo": "",
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

# Defaults as the base, the file layered on top, unknown keys dropped. This way newly
# introduced keys reach existing installations too, and removed ones simply disappear.
merged() {
  jq -n --argjson d "$defaults" --slurpfile f "$settings" '
    ($d + ($f[0] // {})) | with_entries(select(.key | in($d)))
  '
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
    --arg codeLanguage "${CFQ_CODE_LANGUAGE:-}" \
    --arg docLanguages "${CFQ_DOC_LANGUAGES:-}" \
    --arg docLevel "${CFQ_DOC_LEVEL:-}" \
    --arg maintenanceEvery "${CFQ_MAINTENANCE_EVERY:-}" \
    --arg telemetrySyncRepo "${CFQ_TELEMETRY_SYNC_REPO:-}" \
    '
    if $planModels != "" then .planModels = ($planModels | split(",")) else . end
    | if $implModels != "" then .implModels = ($implModels | split(",")) else . end
    | if $allowAnyModel != "" then .allowAnyModel = ($allowAnyModel == "1") else . end
    | if $stopPct != "" then .stopPct = ($stopPct | tonumber) else . end
    | if $scanRoots != "" then .scanRoots = ($scanRoots | split(":")) else . end
    | if $grillMode != "" then .grillMode = $grillMode else . end
    | if $useMattpocockGrilling != "" then .useMattpocockGrilling = ($useMattpocockGrilling == "1") else . end
    | if $usePonytailAudit != "" then .usePonytailAudit = ($usePonytailAudit == "1") else . end
    | if $codeLanguage != "" then .codeLanguage = $codeLanguage else . end
    | if $docLanguages != "" then .docLanguages = ($docLanguages | split(",")) else . end
    | if $docLevel != "" then .docLevel = $docLevel else . end
    | if $maintenanceEvery != "" then .maintenanceEvery = ($maintenanceEvery | tonumber) else . end
    | if $telemetrySyncRepo != "" then .telemetrySyncRepo = $telemetrySyncRepo else . end
    '
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
    merged | with_overrides | jq -r --arg k "$key" '
      .[$k] | if type == "array" then join(",") else tostring end
    '
    ;;
  set)
    key="${2:?usage: cfq-settings.sh set <key> <value>}"
    val="${3?usage: cfq-settings.sh set <key> <value>}"
    ensure
    merged > "$settings.tmp" && mv "$settings.tmp" "$settings"
    if ! jq -n --argjson d "$defaults" --arg k "$key" -e '$d | has($k)' >/dev/null; then
      echo "cfq-settings.sh: unknown key '$key'" >&2
      exit 1
    fi
    case "$key" in
      allowAnyModel|useMattpocockGrilling|usePonytailAudit|setupDone|branchPerBatch|htmlReport)
        case "$val" in
          true|false) jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: '$key' must be true or false" >&2; exit 1 ;;
        esac
        ;;
      stopPct)
        case "$val" in
          ''|*[!0-9]*) echo "cfq-settings.sh: 'stopPct' must be 0-99" >&2; exit 1 ;;
        esac
        if [ "$val" -gt 99 ]; then
          echo "cfq-settings.sh: 'stopPct' must be 0-99" >&2
          exit 1
        fi
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write
        ;;
      maintenanceEvery)
        case "$val" in
          ''|*[!0-9]*) echo "cfq-settings.sh: 'maintenanceEvery' must be a non-negative integer" >&2; exit 1 ;;
        esac
        jq --arg k "$key" --argjson v "$val" '.[$k] = $v' "$settings" | write
        ;;
      grillMode)
        case "$val" in
          stepwise|classic) jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: 'grillMode' must be stepwise or classic" >&2; exit 1 ;;
        esac
        ;;
      docLevel)
        case "$val" in
          minimal|standard|full) jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: 'docLevel' must be minimal, standard or full" >&2; exit 1 ;;
        esac
        ;;
      codeLanguage)
        if [[ ! "$val" =~ ^[A-Za-z][A-Za-z-]*$ ]]; then
          echo "cfq-settings.sh: 'codeLanguage' must match [A-Za-z][A-Za-z-]*" >&2
          exit 1
        fi
        jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write
        ;;
      planModels|implModels|scanRoots|planBlockedPlugins|implBlockedPlugins|docLanguages)
        jq --arg k "$key" --arg v "$val" '.[$k] = ($v | split(","))' "$settings" | write
        ;;
      telemetrySyncRepo)
        case "$val" in
          ''|/*) jq --arg k "$key" --arg v "$val" '.[$k] = $v' "$settings" | write ;;
          *) echo "cfq-settings.sh: 'telemetrySyncRepo' must be an absolute path or empty" >&2; exit 1 ;;
        esac
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
