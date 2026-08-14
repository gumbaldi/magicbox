#!/usr/bin/env bash
# Reports the running session's context usage as "PCT=28 OK (...)" or "PCT=63 STOP (...)".
# Used by implement-for-queue after each finished phase.
# Primary source: the statusline payload captured to ~/.claude/.ctx/<sid>.json (Claude Code's own number).
# Fallback: prompt tokens of the last assistant line in the transcript against a model-dependent limit.
set -u
# stopPct: env > settings.json > default, resolved by cfq-settings.sh (it applies CFQ_STOP_PCT itself).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
stop_pct="${CLAUDE_CTX_STOP_PCT:-$("$script_dir/cfq-settings.sh" get stopPct 2>/dev/null || true)}"
case "$stop_pct" in ''|*[!0-9]*) stop_pct=40 ;; esac
sid="${CLAUDE_CODE_SESSION_ID:-}"
p="$HOME/.claude/.ctx/$sid.json"

pct=""; info=""
if [ -n "$sid" ] && [ -f "$p" ] && [ $(( $(date +%s) - $(stat -c %Y "$p") )) -lt 600 ]; then
  read -r pct used limit <<<"$(jq -r '
    .context_window
    | select(.context_window_size > 0)
    | [ (.used_percentage // ((.current_usage.input + .current_usage.creation + .current_usage.read)
                              / .context_window_size * 100)) | floor,
        ((.current_usage.input // 0) + (.current_usage.creation // 0) + (.current_usage.read // 0)),
        .context_window_size ] | @tsv' "$p" 2>/dev/null)"
  [ -n "${pct:-}" ] && info="($used/$limit, src=payload)"
fi

if [ -z "${pct:-}" ]; then
  slug="$(pwd | tr '/' '-')"; dir="$HOME/.claude/projects/$slug"
  f="$dir/$sid.jsonl"; [ -f "$f" ] || f=$(ls -t "$dir"/*.jsonl 2>/dev/null | head -1)
  [ -n "${f:-}" ] && [ -f "$f" ] || { echo "PCT=? UNKNOWN (no transcript found)"; exit 0; }
  line=$(grep '"type":"assistant"' "$f" | grep -v '"isSidechain":true' | tail -1)
  read -r used model <<<"$(printf '%s' "$line" | jq -r '
    [((.message.usage.input_tokens // 0)
      + (.message.usage.cache_read_input_tokens // 0)
      + (.message.usage.cache_creation_input_tokens // 0)),
     (.message.model // "?")] | @tsv' 2>/dev/null)"
  [ -n "${used:-}" ] && [ "$used" -gt 0 ] 2>/dev/null || { echo "PCT=? UNKNOWN (no usage data)"; exit 0; }
  case "$model" in
    claude-opus-5|claude-sonnet-5|claude-opus-4-8) d=1000000 ;;
    *) d=200000 ;;
  esac
  limit="${CFQ_CTX_LIMIT:-${CLAUDE_CTX_LIMIT:-$d}}"
  pct=$(( used * 100 / limit ))
  info="($used/$limit, $model, src=transcript)"
fi

if [ "$pct" -ge "$stop_pct" ]; then echo "PCT=$pct STOP $info"; else echo "PCT=$pct OK $info"; fi
