#!/usr/bin/env bash
# Owns everything specific to the Claude Code runtime: session id, transcript path resolution,
# context-window usage (statusline payload primary, transcript fallback), model, version. One
# file so a future Claude Code interface change only ever touches this one adapter. Concrete to
# Claude Code — not a multi-runtime plugin system.
# Usage: cfq-runtime.sh session-id
#        cfq-runtime.sh transcript-path [--repo <path>]
#        cfq-runtime.sh context
#        cfq-runtime.sh model
#        cfq-runtime.sh version
#        cfq-runtime.sh capabilities
#        cfq-runtime.sh diagnose [--repo <path>]
set -eu

command -v jq >/dev/null 2>&1 || {
  echo '{"code":"DEPENDENCY_MISSING","message":"jq is required"}' >&2
  exit 1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# pwd-based slug without --repo (matches ctx-usage.sh/cfq-telemetry.sh); repo-based with --repo
# (matches cfq-lock.sh, which slugs the repo it is locking, not its own cwd).
slug_for() {
  if [ -n "${1:-}" ]; then
    printf '%s' "$1" | tr '/' '-'
  else
    pwd | tr '/' '-'
  fi
}

# $1: optional repo path. Prints the resolved transcript path, or empty. Always exits 0.
resolve_transcript_path() {
  local repo_path="${1:-}" slug dir sid f
  slug=$(slug_for "$repo_path")
  dir="$HOME/.claude/projects/$slug"
  sid="${CLAUDE_CODE_SESSION_ID:-}"
  f=""
  if [ -n "$sid" ] && [ -f "$dir/$sid.jsonl" ]; then
    f="$dir/$sid.jsonl"
  else
    f=$(ls -t "$dir"/*.jsonl 2>/dev/null | head -1 || true)
  fi
  printf '%s' "${f:-}"
}

# $1: model name (may be empty/unknown). CFQ_CTX_LIMIT/CLAUDE_CTX_LIMIT win over the schema table,
# matching today's ctx-usage.sh backward-compat env vars.
ctx_window_limit_for() {
  local model="${1:-}" limits base
  limits=$("$script_dir/cfq-settings.sh" get ctxWindowLimits 2>/dev/null || echo '{}')
  if [ "$(jq -r --arg m "$model" '(.large.models // []) | index($m) != null' <<<"$limits" 2>/dev/null)" = "true" ]; then
    base=$(jq -r '.large.limit // 1000000' <<<"$limits")
  else
    base=$(jq -r '.default // 200000' <<<"$limits")
  fi
  echo "${CFQ_CTX_LIMIT:-${CLAUDE_CTX_LIMIT:-$base}}"
}

# Classifies a statusline payload file. Prints one of:
#   ok:<pct>\t<used>\t<windowSize>
#   not-yet-populated
#   schema-mismatch:<detail>
#   invalid-json
inspect_payload() {
  local file="$1" size row
  if ! jq -e . "$file" >/dev/null 2>&1; then
    echo "invalid-json"
    return
  fi
  if ! jq -e '.context_window != null' "$file" >/dev/null 2>&1; then
    echo "schema-mismatch:context_window key missing"
    return
  fi
  size=$(jq -r '.context_window.context_window_size // 0' "$file" 2>/dev/null)
  case "$size" in ''|*[!0-9-]*) size=0 ;; esac
  if [ "$size" -le 0 ] 2>/dev/null; then
    echo "not-yet-populated"
    return
  fi
  row=$(jq -r '
    .context_window
    | select(.context_window_size > 0)
    | [ ((.used_percentage // ((.current_usage.input + .current_usage.creation + .current_usage.read)
                              / .context_window_size * 100)) | floor),
        ((.current_usage.input // 0) + (.current_usage.creation // 0) + (.current_usage.read // 0)),
        .context_window_size ] | @tsv' "$file" 2>/dev/null || true)
  if [ -z "$row" ]; then
    echo "schema-mismatch:used_percentage and current_usage both missing"
    return
  fi
  printf 'ok:%s\n' "$row"
}

sources_json='[]'
add_source() {
  # $1 name, $2 tried(true|false), $3 used(true|false), $4 code(""|CODE), $5 detail
  sources_json=$(jq -c --arg n "$1" --argjson tried "$2" --argjson used "$3" --arg code "$4" --arg detail "$5" \
    '. + [{name:$n, tried:$tried, used:$used, code: (if $code=="" then null else $code end), detail:$detail}]' \
    <<<"$sources_json")
}

status="" pct="" windowSize="" used="" model="" source="" note="" code="" diagnostic="null"

# Runs the full pct-resolution chain once: test-override > statusline payload > transcript
# fallback. Populates the script-scope result variables above plus $sources_json,
# $transcript_path, $transcript_available.
do_resolve() {
  local repo_path="${1:-}" sid p age primary_code="" primary_detail="" kind rest t_used t_model line

  sid="${CLAUDE_CODE_SESSION_ID:-}"
  p="$HOME/.claude/.ctx/$sid.json"

  if [ -n "${CFQ_CTX_TEST_PCT:-}" ]; then
    case "$CFQ_CTX_TEST_PCT" in
      ''|*[!0-9]*)
        add_source "test-override" true false "" "CFQ_CTX_TEST_PCT not numeric, ignored"
        ;;
      *)
        pct="$CFQ_CTX_TEST_PCT"; source="test-override"; note="test override"; status="ok"
        add_source "test-override" true true "" "pct=$pct"
        ;;
    esac
  else
    add_source "test-override" true false "" "CFQ_CTX_TEST_PCT not set"
  fi

  if [ -z "$pct" ]; then
    if [ -n "$sid" ] && [ -f "$p" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$p" 2>/dev/null || echo 0) ))
      if [ "$age" -lt 600 ]; then
        kind=$(inspect_payload "$p")
        case "$kind" in
          ok:*)
            rest="${kind#ok:}"
            read -r pct used windowSize <<<"$rest"
            source="payload"; status="ok"; note="$used/$windowSize, src=payload"
            add_source "statusline-payload" true true "" "$note"
            ;;
          not-yet-populated)
            add_source "statusline-payload" true false "" "context_window_size <= 0, not yet populated"
            ;;
          invalid-json)
            primary_code="RUNTIME_PAYLOAD_INVALID"
            primary_detail="payload file is not valid JSON"
            add_source "statusline-payload" true false "$primary_code" "$primary_detail"
            ;;
          schema-mismatch:*)
            primary_code="RUNTIME_SCHEMA_MISMATCH"
            primary_detail="${kind#schema-mismatch:}"
            add_source "statusline-payload" true false "$primary_code" "$primary_detail"
            ;;
        esac
      else
        add_source "statusline-payload" true false "" "payload stale (age ${age}s >= 600s)"
      fi
    else
      add_source "statusline-payload" false false "" "$( [ -z "$sid" ] && echo "no CLAUDE_CODE_SESSION_ID" || echo "payload file not found" )"
    fi
  else
    add_source "statusline-payload" false false "" "not needed, test-override already usable"
  fi

  transcript_path=$(resolve_transcript_path "$repo_path")
  transcript_available="false"
  [ -n "$transcript_path" ] && [ -f "$transcript_path" ] && transcript_available="true"

  if [ -z "$pct" ]; then
    if [ "$transcript_available" != "true" ]; then
      add_source "transcript" true false "RUNTIME_SOURCE_MISSING" "no transcript file found"
      if [ -z "$primary_code" ]; then
        status="unavailable"; code="RUNTIME_SOURCE_MISSING"; note="no transcript found"
      else
        status="unavailable"; code="$primary_code"; note="$primary_detail"
        diagnostic=$(jq -n --arg cap "contextUsage" --arg src "statusline-payload" \
          --arg expected "context_window.used_percentage or current_usage with context_window_size" \
          --arg observed "$primary_detail" --arg fbstatus "unavailable" --arg fbcode "RUNTIME_SOURCE_MISSING" \
          --arg scope "cfq-runtime.sh" --arg hint "current Claude Code statusline JSON schema" \
          '{capability:$cap, source:$src, expected:$expected, observed:$observed,
            fallbackStatus:$fbstatus, fallbackCode:$fbcode, repairScope:$scope, researchHint:$hint}')
      fi
    else
      line=$(grep '"type":"assistant"' "$transcript_path" | grep -v '"isSidechain":true' | tail -1)
      read -r t_used t_model <<<"$(printf '%s' "$line" | jq -r '
        [((.message.usage.input_tokens // 0)
          + (.message.usage.cache_read_input_tokens // 0)
          + (.message.usage.cache_creation_input_tokens // 0)),
         (.message.model // "?")] | @tsv' 2>/dev/null || true)"
      if [ -z "${t_used:-}" ] || ! [ "$t_used" -gt 0 ] 2>/dev/null; then
        add_source "transcript" true false "FALLBACK_FAILED" "transcript found but no usable usage data"
        if [ -z "$primary_code" ]; then
          status="unavailable"; code="FALLBACK_FAILED"; note="transcript found but no usable usage data"
        else
          status="unavailable"; code="$primary_code"; note="$primary_detail"
          diagnostic=$(jq -n --arg cap "contextUsage" --arg src "statusline-payload" \
            --arg expected "context_window.used_percentage or current_usage with context_window_size" \
            --arg observed "$primary_detail" --arg fbstatus "unavailable" --arg fbcode "FALLBACK_FAILED" \
            --arg scope "cfq-runtime.sh" --arg hint "current Claude Code statusline JSON schema" \
            '{capability:$cap, source:$src, expected:$expected, observed:$observed,
              fallbackStatus:$fbstatus, fallbackCode:$fbcode, repairScope:$scope, researchHint:$hint}')
        fi
      else
        windowSize=$(ctx_window_limit_for "$t_model")
        used="$t_used"
        [ "$t_model" != "?" ] && model="$t_model"
        pct=$(( used * 100 / windowSize ))
        note="$used/$windowSize, src=transcript"
        add_source "transcript" true true "" "$note"
        if [ -z "$primary_code" ]; then
          status="ok"; source="transcript"
        else
          status="degraded"; source="transcript"; code="$primary_code"
          note="$note, runtime=degraded:$primary_code"
          diagnostic=$(jq -n --arg cap "contextUsage" --arg src "statusline-payload" \
            --arg expected "context_window.used_percentage or current_usage with context_window_size" \
            --arg observed "$primary_detail" --arg fbstatus "ok" \
            --arg scope "cfq-runtime.sh" --arg hint "current Claude Code statusline JSON schema" \
            '{capability:$cap, source:$src, expected:$expected, observed:$observed,
              fallbackStatus:$fbstatus, repairScope:$scope, researchHint:$hint}')
        fi
      fi
    fi
  else
    add_source "transcript" false false "" "not needed, primary source already usable"
  fi
}

result_json() {
  jq -n \
    --arg status "$status" \
    --argjson pct "${pct:-null}" \
    --argjson windowSize "${windowSize:-null}" \
    --argjson used "${used:-null}" \
    --arg model "$model" \
    --arg source "$source" \
    --arg note "$note" \
    --arg code "$code" \
    --argjson diagnostic "$diagnostic" \
    '{status:$status, pct:$pct, windowSize:$windowSize, used:$used,
      model: (if $model == "" then null else $model end),
      source: (if $source == "" then null else $source end),
      note: (if $note == "" then null else $note end),
      code: (if $code == "" then null else $code end),
      diagnostic: $diagnostic}'
}

cmd="${1:-}"
shift || true

repo_path=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo_path="${2:?--repo requires a path}"; shift 2 ;;
    *) echo '{"code":"INVALID_ARGUMENT","message":"unrecognized argument"}' >&2; exit 1 ;;
  esac
done

case "$cmd" in
  session-id)
    printf '%s\n' "${CLAUDE_CODE_SESSION_ID:-}"
    ;;
  transcript-path)
    resolve_transcript_path "$repo_path"
    printf '\n'
    ;;
  context)
    do_resolve ""
    result_json
    ;;
  model)
    do_resolve ""
    jq -n --arg m "$model" '$m | if . == "" then null else . end'
    ;;
  version)
    transcript_path=$(resolve_transcript_path "")
    v=""
    if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
      line=$(tail -1 "$transcript_path" 2>/dev/null || true)
      v=$(printf '%s' "$line" | jq -r '.version // empty' 2>/dev/null || true)
    fi
    jq -n --arg v "$v" '$v | if . == "" then null else . end'
    ;;
  capabilities)
    sid="${CLAUDE_CODE_SESSION_ID:-}"
    p="$HOME/.claude/.ctx/$sid.json"
    statusline="false"
    if [ -n "$sid" ] && [ -f "$p" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$p" 2>/dev/null || echo 0) ))
      [ "$age" -lt 600 ] && statusline="true"
    fi
    tp=$(resolve_transcript_path "")
    transcript="false"
    [ -n "$tp" ] && [ -f "$tp" ] && transcript="true"
    jq -n --argjson sp "$statusline" --argjson ta "$transcript" \
      '{statuslinePayload:$sp, transcriptAvailable:$ta}'
    ;;
  diagnose)
    do_resolve "$repo_path"
    ccv=""
    if [ "$transcript_available" = "true" ]; then
      line=$(tail -1 "$transcript_path" 2>/dev/null || true)
      ccv=$(printf '%s' "$line" | jq -r '.version // empty' 2>/dev/null || true)
    fi
    sid="${CLAUDE_CODE_SESSION_ID:-}"
    p="$HOME/.claude/.ctx/$sid.json"
    sp="false"
    if [ -n "$sid" ] && [ -f "$p" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$p" 2>/dev/null || echo 0) ))
      [ "$age" -lt 600 ] && sp="true"
    fi
    jq -n \
      --arg sid "$sid" \
      --arg tp "$transcript_path" \
      --argjson sources "$sources_json" \
      --argjson result "$(result_json)" \
      --argjson sp "$sp" \
      --argjson ta "$( [ "$transcript_available" = "true" ] && echo true || echo false )" \
      --arg ccv "$ccv" \
      --arg code "$code" \
      '{
        sessionId: (if $sid == "" then null else $sid end),
        transcriptPath: (if $tp == "" then null else $tp end),
        sources: $sources,
        result: $result,
        capabilities: {statuslinePayload:$sp, transcriptAvailable:$ta},
        ccVersion: (if $ccv == "" then null else $ccv end),
        code: (if $code == "" then null else $code end)
      }'
    ;;
  *)
    echo '{"code":"INVALID_ARGUMENT","message":"usage: cfq-runtime.sh session-id | transcript-path [--repo <path>] | context | model | version | capabilities | diagnose [--repo <path>]"}' >&2
    exit 1
    ;;
esac
