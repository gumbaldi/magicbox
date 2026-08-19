#!/usr/bin/env bash
# Reports the running session's context usage as "PCT=28 OK (...)" or "PCT=63 STOP (...)".
# Used by implement-for-queue after each finished phase, and in `gate` mode before a phase starts
# to predict whether it would cross stopPct.
# Primary source: the statusline payload captured to ~/.claude/.ctx/<sid>.json (Claude Code's own number).
# Fallback: prompt tokens of the last assistant line in the transcript against a model-dependent limit.
# Usage: ctx-usage.sh              # post-phase check (unchanged)
#        ctx-usage.sh gate <SIZE>  # pre-phase predictive gate; SIZE = S/M/L, anything else -> M
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# stopPct: env > settings.json > default, resolved by cfq-settings.sh (it applies CFQ_STOP_PCT itself).
stop_pct="${CLAUDE_CTX_STOP_PCT:-$("$script_dir/cfq-settings.sh" get stopPct 2>/dev/null || true)}"
case "$stop_pct" in ''|*[!0-9]*) stop_pct=60 ;; esac

# Single source of truth for how many percentage points a phase of a given size is expected to
# add to context usage. Missing/malformed size counts as M. Initial heuristic (S=7, M=15, L=25);
# replace with telemetry-derived numbers later by editing only this function.
size_growth() {
  case "$1" in
    S) echo 7 ;;
    M) echo 15 ;;
    L) echo 25 ;;
    *) echo 15 ;;
  esac
}

cmd="${1:-}"
size=""
if [ "$cmd" = "gate" ]; then
  case "${2:-}" in S|M|L) size="${2}" ;; *) size="M" ;; esac
  # stopPct 0 already hands off after every phase via the unchanged post-phase check below. The
  # predictive gate must never be the reason the one phase that semantics still allows doesn't start.
  if [ "$stop_pct" -eq 0 ]; then
    echo "PCT=? SIZE=$size EXPECTED=$(size_growth "$size") LIMIT=0 START (stopPct=0 bypass)"
    exit 0
  fi
fi

sid="${CLAUDE_CODE_SESSION_ID:-}"
p="$HOME/.claude/.ctx/$sid.json"

pct=""; info=""
if [ -n "${CFQ_CTX_TEST_PCT:-}" ]; then
  case "$CFQ_CTX_TEST_PCT" in
    ''|*[!0-9]*) : ;;                              # not plain digits -> ignore, detect for real
    *) pct="$CFQ_CTX_TEST_PCT"; info="(test override)" ;;
  esac
fi

if [ -z "$pct" ] && [ -n "$sid" ] && [ -f "$p" ] && [ $(( $(date +%s) - $(stat -c %Y "$p") )) -lt 600 ]; then
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
  if [ -z "${f:-}" ] || [ ! -f "$f" ]; then
    if [ "$cmd" = "gate" ]; then
      echo "PCT=? SIZE=$size EXPECTED=$(size_growth "$size") LIMIT=$stop_pct HANDOFF (no transcript found)"
      exit 0
    fi
    echo "PCT=? UNKNOWN (no transcript found)"; exit 0
  fi
  line=$(grep '"type":"assistant"' "$f" | grep -v '"isSidechain":true' | tail -1)
  read -r used model <<<"$(printf '%s' "$line" | jq -r '
    [((.message.usage.input_tokens // 0)
      + (.message.usage.cache_read_input_tokens // 0)
      + (.message.usage.cache_creation_input_tokens // 0)),
     (.message.model // "?")] | @tsv' 2>/dev/null)"
  if [ -z "${used:-}" ] || ! [ "$used" -gt 0 ] 2>/dev/null; then
    if [ "$cmd" = "gate" ]; then
      echo "PCT=? SIZE=$size EXPECTED=$(size_growth "$size") LIMIT=$stop_pct HANDOFF (no usage data)"
      exit 0
    fi
    echo "PCT=? UNKNOWN (no usage data)"; exit 0
  fi
  case "$model" in
    claude-opus-5|claude-sonnet-5|claude-opus-4-8) d=1000000 ;;
    *) d=200000 ;;
  esac
  limit="${CFQ_CTX_LIMIT:-${CLAUDE_CTX_LIMIT:-$d}}"
  pct=$(( used * 100 / limit ))
  info="($used/$limit, $model, src=transcript)"
fi

if [ "$cmd" = "gate" ]; then
  growth=$(size_growth "$size")
  projected=$((pct + growth))
  if [ "$projected" -ge "$stop_pct" ]; then decision=HANDOFF; else decision=START; fi
  echo "PCT=$pct SIZE=$size EXPECTED=$growth PROJECTED=$projected LIMIT=$stop_pct $decision $info"
  exit 0
fi

if [ "$pct" -ge "$stop_pct" ]; then echo "PCT=$pct STOP $info"; else echo "PCT=$pct OK $info"; fi
