#!/usr/bin/env bash
# Gate policy only: stopPct comparison and S/M/L growth projection. Runtime discovery (statusline
# payload, transcript parsing, model->window table) lives in cfq-runtime.sh; this script only
# consumes its `context` subcommand.
# Used by implement-for-queue after each finished phase, and in `gate` mode before a phase starts
# to predict whether it would cross stopPct.
# Usage: ctx-usage.sh              # post-phase check (unchanged)
#        ctx-usage.sh gate <SIZE>  # pre-phase predictive gate; SIZE = S/M/L, anything else -> M
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_pct=$("$script_dir/cfq-settings.sh" get stopPct 2>/dev/null || echo 60)
case "$stop_pct" in ''|*[!0-9]*) stop_pct=60 ;; esac
growth_json=$("$script_dir/cfq-settings.sh" get phaseContextGrowth 2>/dev/null || echo '{"S":7,"M":15,"L":25}')
size_growth() { jq -r --arg s "$1" '.[$s] // .M' <<<"$growth_json" 2>/dev/null || echo 15; }

cmd="${1:-}"; size=""
if [ "$cmd" = "gate" ]; then
  case "${2:-}" in S|M|L) size="${2}" ;; *) size="M" ;; esac
  # stopPct 0 already hands off after every phase via the unchanged post-phase check below. The
  # predictive gate must never be the reason the one phase that semantics still allows doesn't start.
  if [ "$stop_pct" -eq 0 ]; then
    echo "PCT=? SIZE=$size EXPECTED=$(size_growth "$size") LIMIT=0 START (stopPct=0 bypass)"
    exit 0
  fi
fi

ctx=$("$script_dir/cfq-runtime.sh" context)
pct=$(jq -r '.pct // empty' <<<"$ctx")
note=$(jq -r '.note' <<<"$ctx")
# `status:"degraded"` is intentionally still usable when pct exists. The runtime adapter already
# folds its compact diagnostic into `note`; this gate does not re-diagnose Claude Code itself.

if [ -z "$pct" ]; then
  if [ "$cmd" = "gate" ]; then
    echo "PCT=? SIZE=$size EXPECTED=$(size_growth "$size") LIMIT=$stop_pct HANDOFF ($note)"
    exit 0
  fi
  echo "PCT=? UNKNOWN ($note)"; exit 0
fi

if [ "$cmd" = "gate" ]; then
  growth=$(size_growth "$size")
  projected=$((pct + growth))
  if [ "$projected" -ge "$stop_pct" ]; then decision=HANDOFF; else decision=START; fi
  echo "PCT=$pct SIZE=$size EXPECTED=$growth PROJECTED=$projected LIMIT=$stop_pct $decision ($note)"
  exit 0
fi

if [ "$pct" -ge "$stop_pct" ]; then echo "PCT=$pct STOP ($note)"; else echo "PCT=$pct OK ($note)"; fi
