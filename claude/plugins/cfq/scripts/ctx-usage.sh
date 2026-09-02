#!/usr/bin/env bash
# Gate policy: two independent stop reasons, three independent off switches.
#   - Capacity: stopUsed against the absolute context-token count (input + cache_read +
#     cache_creation). The window fills up whether or not the tokens were cheap, so `used` is
#     never weighted by cache share.
#   - Rate limit: stopFiveHourPct / stopSevenDayPct against the statusline payload's five-hour and
#     seven-day usage percentages. Checked first, since it is the constraint no later session can
#     work around -- the context window resets on /clear, the five-hour budget does not.
# The cache share (fresh/creation/read split) is display only and never enters a verdict --
# current_usage is a snapshot of the last API call, so the ratio swings after a /clear or a cache
# miss without anything being wrong; it is shown so a human can weigh whether attaching another
# phase to a warm session is worth it.
# Runtime discovery (statusline payload, transcript parsing) lives in cfq-runtime.sh; this script
# only consumes its `context` subcommand's `used`/`cache`/`rateLimits` fields.
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

stop_5h=$("$script_dir/cfq-settings.sh" get stopFiveHourPct 2>/dev/null || echo 70)
case "$stop_5h" in
  -1) ;;
  ''|*[!0-9]*) stop_5h=70 ;;
esac

stop_7d=$("$script_dir/cfq-settings.sh" get stopSevenDayPct 2>/dev/null || echo 95)
case "$stop_7d" in
  -1) ;;
  ''|*[!0-9]*) stop_7d=95 ;;
esac

cmd="${1:-}"; size=""
if [ "$cmd" = "gate" ]; then
  case "${2:-}" in S|M|L) size="${2}" ;; *) size="M" ;; esac
fi

# All three switches off: no reason can ever fire, nothing to resolve.
if [ "$stop_used" = "-1" ] && [ "$stop_5h" = "-1" ] && [ "$stop_7d" = "-1" ]; then
  if [ "$cmd" = "gate" ]; then
    echo "USED=? SIZE=$size LIMIT=-1 START (all stop reasons disabled)"
  else
    echo "USED=? OK (all stop reasons disabled)"
  fi
  exit 0
fi

ctx=$("$script_dir/cfq-runtime.sh" context)
used=$(jq -r '.used // empty' <<<"$ctx")
note=$(jq -r '.note' <<<"$ctx")
cache_read=$(jq -r '.cache.read // empty' <<<"$ctx")
five_hour_pct=$(jq -r '.rateLimits.fiveHourPct // empty' <<<"$ctx")
seven_day_pct=$(jq -r '.rateLimits.sevenDayPct // empty' <<<"$ctx")

# Cache share and rate-limit percentages are appended to the note as display info regardless of
# the decision below; the note must stay parenthesis-free (cfq-ifq-preflight.sh's capture is
# greedy to the final `)`).
if [ -n "$cache_read" ] && [ -n "$used" ] && [ "$used" -gt 0 ] 2>/dev/null; then
  note="$note, cache $((cache_read * 100 / used))%"
fi
[ -n "$five_hour_pct" ] && note="$note, 5h ${five_hour_pct}%"
[ -n "$seven_day_pct" ] && note="$note, 7d ${seven_day_pct}%"

decision="" stop_reason=""

# 1. Rate limit -- checked first, a rate-limit stop always wins over the stopUsed=0 bypass below.
if [ -n "$five_hour_pct" ] && [ "$stop_5h" != "-1" ] && [ "$five_hour_pct" -ge "$stop_5h" ] 2>/dev/null; then
  decision=STOP; stop_reason="5h ${five_hour_pct}% >= $stop_5h"
elif [ -n "$seven_day_pct" ] && [ "$stop_7d" != "-1" ] && [ "$seven_day_pct" -ge "$stop_7d" ] 2>/dev/null; then
  decision=STOP; stop_reason="7d ${seven_day_pct}% >= $stop_7d"
fi

# 2. stopUsed=0, gate mode only: bypasses only the capacity reason below, not a rate-limit stop.
if [ -z "$decision" ] && [ "$cmd" = "gate" ] && [ "$stop_used" -eq 0 ] 2>/dev/null; then
  decision=START
fi

if [ -z "$decision" ] && [ -z "$used" ]; then
  if [ "$cmd" = "gate" ]; then
    echo "USED=? SIZE=$size LIMIT=$stop_used HANDOFF ($note)"
    exit 0
  fi
  echo "USED=? UNKNOWN ($note)"; exit 0
fi

# 3. Capacity.
if [ -z "$decision" ] && [ "$stop_used" != "-1" ] && [ "$used" -ge "$stop_used" ] 2>/dev/null; then
  decision=STOP; stop_reason="used $used >= $stop_used"
fi

[ -n "$decision" ] || decision=START
[ -n "$stop_reason" ] && note="$note, $stop_reason"

if [ "$cmd" = "gate" ]; then
  case "$decision" in START) verdict=START ;; *) verdict=HANDOFF ;; esac
  echo "USED=${used:-?} SIZE=$size LIMIT=$stop_used $verdict ($note)"
  exit 0
fi

case "$decision" in START) verdict=OK ;; *) verdict=STOP ;; esac
echo "USED=${used:-?} $verdict ($note)"
