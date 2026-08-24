#!/usr/bin/env bash
set -eu
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ctx="$repo_root/scripts/ctx-usage.sh"

home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT

# routine: used under stopUsed -> START/OK
out=$(HOME="$home" CFQ_CTX_TEST_USED=50000 CFQ_STOP_USED=100000 bash "$ctx" gate S)
[[ "$out" == *"USED=50000"*"SIZE=S"*"LIMIT=100000"*START* ]] || { echo "FAIL: under limit gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=50000 CFQ_STOP_USED=100000 bash "$ctx")
[ "$out" = "USED=50000 OK (test override)" ] || { echo "FAIL: under limit no-arg -> $out"; exit 1; }

# boundary: exactly at stopUsed -> HANDOFF/STOP (>=, not >)
out=$(HOME="$home" CFQ_CTX_TEST_USED=100000 CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *"USED=100000"*HANDOFF* ]] || { echo "FAIL: boundary gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=100000 CFQ_STOP_USED=100000 bash "$ctx")
[ "$out" = "USED=100000 STOP (test override)" ] || { echo "FAIL: boundary no-arg -> $out"; exit 1; }

# one token over -> HANDOFF/STOP
out=$(HOME="$home" CFQ_CTX_TEST_USED=100001 CFQ_STOP_USED=100000 bash "$ctx")
[ "$out" = "USED=100001 STOP (test override)" ] || { echo "FAIL: over limit -> $out"; exit 1; }

# custom stopUsed
out=$(HOME="$home" CFQ_CTX_TEST_USED=19999 CFQ_STOP_USED=20000 bash "$ctx" gate L)
[[ "$out" == *"USED=19999"*"LIMIT=20000"*START* ]] || { echo "FAIL: custom limit start -> $out"; exit 1; }

# special value: stopUsed=0 -> gate always START (pre-phase bypass); no-arg always STOP
out=$(HOME="$home" CFQ_STOP_USED=0 bash "$ctx" gate S)
[[ "$out" == *"LIMIT=0"*START*"stopUsed=0 bypass"* ]] || { echo "FAIL: stopUsed=0 gate bypass -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=0 bash "$ctx")
[ "$out" = "USED=1 STOP (test override)" ] || { echo "FAIL: stopUsed=0 no-arg always stop -> $out"; exit 1; }

# special value: stopUsed=-1 -> never stop, gate and no-arg both, even with a huge used
out=$(HOME="$home" CFQ_CTX_TEST_USED=99999999 CFQ_STOP_USED=-1 bash "$ctx" gate L)
[[ "$out" == *"LIMIT=-1"*START* ]] || { echo "FAIL: stopUsed=-1 gate -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=99999999 CFQ_STOP_USED=-1 bash "$ctx")
[[ "$out" == *OK* ]] || { echo "FAIL: stopUsed=-1 no-arg -> $out"; exit 1; }

# malformed/missing size still defaults to M (passthrough only, no effect on the decision)
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=100000 bash "$ctx" gate XL)
[[ "$out" == *"SIZE=M"* ]] || { echo "FAIL: malformed size -> $out"; exit 1; }
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=100000 bash "$ctx" gate)
[[ "$out" == *"SIZE=M"* ]] || { echo "FAIL: missing size -> $out"; exit 1; }

# unknown used (throwaway HOME, no transcript/session, no override) -> conservative HANDOFF/UNKNOWN
tmp_home=$(mktemp -d)
out=$(HOME="$tmp_home" CFQ_STOP_USED=100000 bash "$ctx" gate M)
[[ "$out" == *"USED=?"*HANDOFF* ]] || { echo "FAIL: unknown used gate -> $out"; exit 1; }
out=$(HOME="$tmp_home" CFQ_STOP_USED=100000 bash "$ctx")
[[ "$out" == *"USED=?"*UNKNOWN* ]] || { echo "FAIL: unknown used no-arg -> $out"; exit 1; }
rm -rf "$tmp_home"

# malformed CFQ_STOP_USED env falls back to the schema default (100000)
out=$(HOME="$home" CFQ_CTX_TEST_USED=1 CFQ_STOP_USED=abc bash "$ctx")
[ "$out" = "USED=1 OK (test override)" ] || { echo "FAIL: malformed stopUsed env fallback -> $out"; exit 1; }

echo PASS
