#!/usr/bin/env bash
set -eu
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ctx="$repo_root/scripts/ctx-usage.sh"

# boundary matrix, default limit 60
out=$(CFQ_CTX_TEST_PCT=52 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate S)
[[ "$out" == *"PROJECTED=59"*START* ]] || { echo "FAIL: 52+S -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=53 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate S)
[[ "$out" == *"PROJECTED=60"*HANDOFF* ]] || { echo "FAIL: 53+S -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=44 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate M)
[[ "$out" == *"PROJECTED=59"*START* ]] || { echo "FAIL: 44+M -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=45 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate M)
[[ "$out" == *"PROJECTED=60"*HANDOFF* ]] || { echo "FAIL: 45+M -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=34 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate L)
[[ "$out" == *"PROJECTED=59"*START* ]] || { echo "FAIL: 34+L -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=35 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate L)
[[ "$out" == *"PROJECTED=60"*HANDOFF* ]] || { echo "FAIL: 35+L -> $out"; exit 1; }

# custom stopPct
out=$(CFQ_CTX_TEST_PCT=10 CLAUDE_CTX_STOP_PCT=20 bash "$ctx" gate S)
[[ "$out" == *"PROJECTED=17"*START* ]] || { echo "FAIL: custom stopPct start -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=13 CLAUDE_CTX_STOP_PCT=20 bash "$ctx" gate S)
[[ "$out" == *"PROJECTED=20"*HANDOFF* ]] || { echo "FAIL: custom stopPct handoff -> $out"; exit 1; }

# stopPct=0 bypass (pre-phase gate never blocks, regardless of pct)
out=$(CLAUDE_CTX_STOP_PCT=0 bash "$ctx" gate S)
[[ "$out" == *"START"*"stopPct=0 bypass"* ]] || { echo "FAIL: stopPct=0 bypass -> $out"; exit 1; }

# malformed size -> M
out=$(CFQ_CTX_TEST_PCT=40 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate XL)
[[ "$out" == *"SIZE=M EXPECTED=15"* ]] || { echo "FAIL: malformed size -> $out"; exit 1; }

# missing size -> M
out=$(CFQ_CTX_TEST_PCT=40 CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate)
[[ "$out" == *"SIZE=M EXPECTED=15"* ]] || { echo "FAIL: missing size -> $out"; exit 1; }

# unknown pct with stopPct>0 -> conservative HANDOFF (throwaway HOME, no transcript/session)
tmp_home=$(mktemp -d)
out=$(HOME="$tmp_home" CLAUDE_CTX_STOP_PCT=60 bash "$ctx" gate M)
[[ "$out" == *"PCT=?"*HANDOFF* ]] || { echo "FAIL: unknown pct -> $out"; exit 1; }
rm -rf "$tmp_home"

# legacy no-arg call unaffected
out=$(CFQ_CTX_TEST_PCT=70 CLAUDE_CTX_STOP_PCT=60 bash "$ctx")
[ "$out" = "PCT=70 STOP (test override)" ] || { echo "FAIL: legacy call -> $out"; exit 1; }
out=$(CFQ_CTX_TEST_PCT=10 CLAUDE_CTX_STOP_PCT=60 bash "$ctx")
[ "$out" = "PCT=10 OK (test override)" ] || { echo "FAIL: legacy call OK -> $out"; exit 1; }

echo PASS
