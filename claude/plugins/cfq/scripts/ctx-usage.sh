#!/usr/bin/env bash
# Gate policy only: stopUsed comparison against the absolute context-token count (input +
# cache_read + cache_creation). Runtime discovery (statusline payload, transcript parsing) lives
# in cfq-runtime.sh; this script only consumes its `context` subcommand's `used` field.
# Used by implement-for-queue after each finished phase, and in `gate` mode before a phase starts.
# Usage: ctx-usage.sh              # post-phase check
#        ctx-usage.sh gate <SIZE>  # pre-phase gate; SIZE kept for call-site compatibility with an
#                                  # existing consumer, no longer affects the decision
set -u
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stop_used=$("$script_dir/cfq-settings.sh" get stopUsed 2>/dev/null || echo 100000)
case "$stop_used" in
  -1) ;;
  ''|*[!0-9]*) stop_used=100000 ;;
esac

cmd="${1:-}"; size=""
if [ "$cmd" = "gate" ]; then
  case "${2:-}" in S|M|L) size="${2}" ;; *) size="M" ;; esac
fi

# stopUsed=-1: never stop for this reason, unconditionally -- no need to even resolve `used`.
if [ "$stop_used" = "-1" ]; then
  if [ "$cmd" = "gate" ]; then
    echo "USED=? SIZE=$size LIMIT=-1 START (stopUsed=-1, unlimited)"
  else
    echo "USED=? OK (stopUsed=-1, unlimited)"
  fi
  exit 0
fi

# stopUsed=0, gate mode only: the predictive gate must never be the reason the one phase that
# semantics still allows doesn't start. The post-phase check below already hands off after every
# phase once stop_used=0 is compared against any used>=0.
if [ "$cmd" = "gate" ] && [ "$stop_used" -eq 0 ]; then
  echo "USED=? SIZE=$size LIMIT=0 START (stopUsed=0 bypass)"
  exit 0
fi

ctx=$("$script_dir/cfq-runtime.sh" context)
used=$(jq -r '.used // empty' <<<"$ctx")
note=$(jq -r '.note' <<<"$ctx")

if [ -z "$used" ]; then
  if [ "$cmd" = "gate" ]; then
    echo "USED=? SIZE=$size LIMIT=$stop_used HANDOFF ($note)"
    exit 0
  fi
  echo "USED=? UNKNOWN ($note)"; exit 0
fi

if [ "$cmd" = "gate" ]; then
  if [ "$used" -ge "$stop_used" ]; then decision=HANDOFF; else decision=START; fi
  echo "USED=$used SIZE=$size LIMIT=$stop_used $decision ($note)"
  exit 0
fi

if [ "$used" -ge "$stop_used" ]; then echo "USED=$used STOP ($note)"; else echo "USED=$used OK ($note)"; fi
