#!/usr/bin/env bash
# Self-test for scripts/cfq-telemetry.sh. No framework, no fixtures — just `bash tests/test-telemetry.sh`.
set -eu

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
telemetry_sh="$repo_root/scripts/cfq-telemetry.sh"
report_sh="$repo_root/scripts/cfq-report.sh"
settings_sh="$repo_root/scripts/cfq-settings.sh"

home=$(mktemp -d)
repo=$(mktemp -d)
trap 'rm -rf "$home" "$repo" "${repo2:-}" "${home_empty:-}" "${target:-}"' EXIT

git init -q "$repo"
batch="$repo/.claude/cfq/2026-01-01-demo"
mkdir -p "$batch"

slug="$(printf '%s' "$repo" | tr '/' '-')"
tdir="$home/.claude/projects/$slug"
mkdir -p "$tdir"
transcript="$tdir/testsid.jsonl"

# Four assistant turns: two models, two effort levels, one sidechain (subagent) turn, one
# tool_use (Bash). The marker GEHEIMER_PROMPT_TEXT sits once in a text block and once in a tool
# input.command — the recorded telemetry must never carry either occurrence forward.
cat >"$transcript" <<'EOF'
{"type":"assistant","timestamp":"2026-08-13T10:00:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"high","attributionSkill":"code-for-queue:implement-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-sonnet-5","usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":10,"cache_creation_input_tokens":5},"content":[{"type":"text","text":"GEHEIMER_PROMPT_TEXT shows up in assistant prose here"}]}}
{"type":"assistant","timestamp":"2026-08-13T10:01:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"high","attributionSkill":"code-for-queue:implement-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-sonnet-5","usage":{"input_tokens":200,"output_tokens":80,"cache_read_input_tokens":20,"cache_creation_input_tokens":0},"content":[{"type":"tool_use","name":"Bash","input":{"command":"echo GEHEIMER_PROMPT_TEXT"}}]}}
{"type":"assistant","timestamp":"2026-08-13T10:02:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"medium","attributionSkill":"code-for-queue:plan-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-opus-5","usage":{"input_tokens":150,"output_tokens":60,"cache_read_input_tokens":15,"cache_creation_input_tokens":0},"content":[{"type":"text","text":"planning turn"}]}}
{"type":"assistant","timestamp":"2026-08-13T10:03:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":true,"effort":"medium","attributionSkill":"code-for-queue:plan-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-opus-5","usage":{"input_tokens":50,"output_tokens":20,"cache_read_input_tokens":5,"cache_creation_input_tokens":0},"content":[{"type":"text","text":"subagent turn"}]}}
EOF

jsonl="$repo/.claude/cfq/telemetry.jsonl"

# Seed report.json with a phase entry, as implement-for-queue would via cfq-report.sh append.
HOME="$home" bash "$report_sh" append "$batch" '{"phase":"01-foo","status":"green","summary":"test"}'

# 1. First record call
out=$(cd "$repo" && HOME="$home" CLAUDE_CODE_SESSION_ID=testsid bash "$telemetry_sh" record "$batch" phase 01-foo)
[ "$out" = "telemetry: 4 turns, 210 out / 555 in" ] || { echo "FAIL: unexpected record output: $out"; exit 1; }

rec1=$(tail -n 1 "$jsonl")

got=$(jq -r '.totals.output' <<<"$rec1")
[ "$got" = "210" ] || { echo "FAIL: totals.output = $got, want 210 (50+80+60+20)"; exit 1; }
got=$(jq -r '.totals.cache_read' <<<"$rec1")
[ "$got" = "50" ] || { echo "FAIL: totals.cache_read = $got, want 50 (10+20+15+5)"; exit 1; }

got=$(jq -c '.by_model | to_entries | map({(.key): .value.turns}) | add' <<<"$rec1")
[ "$got" = '{"claude-opus-5":2,"claude-sonnet-5":2}' ] || { echo "FAIL: by_model = $got"; exit 1; }
got=$(jq -c '.by_effort | to_entries | map({(.key): .value.turns}) | add' <<<"$rec1")
[ "$got" = '{"high":2,"medium":2}' ] || { echo "FAIL: by_effort = $got"; exit 1; }
got=$(jq -c '.by_skill | to_entries | map({(.key): .value.turns}) | add' <<<"$rec1")
[ "$got" = '{"code-for-queue:implement-for-queue":2,"code-for-queue:plan-for-queue":2}' ] \
  || { echo "FAIL: by_skill = $got"; exit 1; }

got=$(jq -c '.tools' <<<"$rec1")
[ "$got" = '{"Bash":1}' ] || { echo "FAIL: tools = $got"; exit 1; }

got=$(jq -r '.subagent.turns' <<<"$rec1")
[ "$got" = "1" ] || { echo "FAIL: subagent.turns = $got, want 1"; exit 1; }

# No prompt/tool-argument text ever reaches the stored record.
grep -c GEHEIMER_PROMPT_TEXT "$jsonl" >/dev/null 2>&1 && n=$(grep -c GEHEIMER_PROMPT_TEXT "$jsonl") || n=0
[ "$n" = "0" ] || { echo "FAIL: telemetry.jsonl leaked prompt text ($n hits)"; exit 1; }

# Structural whitelist: every leaf field name must be one we deliberately added.
allowed='["schema","kind","repo","batch","phase","session_id","branch","cc_version","from","until","wallclock_s","turns","input","output","cache_read","cache_creation","billable_in","Bash"]'
leaves=$(jq -c '[paths(scalars) | .[-1]] | unique' <<<"$rec1")
extra=$(jq -n --argjson a "$allowed" --argjson l "$leaves" '$l - $a')
[ "$extra" = "[]" ] || { echo "FAIL: unexpected leaf field(s) in telemetry record: $extra"; exit 1; }

# report.json got the telemetry block attached to the last phase.
match=$(jq --argjson r "$rec1" '.phases[-1].telemetry == $r' "$batch/report.json")
[ "$match" = "true" ] || { echo "FAIL: report.json .phases[-1].telemetry does not match recorded telemetry"; exit 1; }

# 2. Second record call of the same session only picks up the new line (window logic)
cat >>"$transcript" <<'EOF'
{"type":"assistant","timestamp":"2026-08-13T10:04:00.000Z","sessionId":"testsid","gitBranch":"v0.2","version":"1.0.0","isSidechain":false,"effort":"high","attributionSkill":"code-for-queue:implement-for-queue","attributionPlugin":"code-for-queue","message":{"model":"claude-sonnet-5","usage":{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"content":[{"type":"text","text":"one more turn"}]}}
EOF
cd "$repo" && HOME="$home" CLAUDE_CODE_SESSION_ID=testsid bash "$telemetry_sh" record "$batch" phase 01-foo >/dev/null
rec2=$(tail -n 1 "$jsonl")
got=$(jq -r '.totals.turns' <<<"$rec2")
[ "$got" = "1" ] || { echo "FAIL: windowed record turns = $got, want 1"; exit 1; }

# 3. kind=planning writes to .planning instead of .phases[-1].telemetry
cd "$repo" && HOME="$home" CLAUDE_CODE_SESSION_ID=testsid bash "$telemetry_sh" record "$batch" planning >/dev/null
rec3=$(tail -n 1 "$jsonl")
match=$(jq --argjson r "$rec3" '.planning == $r' "$batch/report.json")
[ "$match" = "true" ] || { echo "FAIL: report.json .planning does not match recorded telemetry"; exit 1; }

# 4. Fail-soft: no transcript found -> exit 0, no telemetry.jsonl written
repo2=$(mktemp -d)
git init -q "$repo2"
batch2="$repo2/.claude/cfq/2026-01-02-empty"
mkdir -p "$batch2"
home_empty=$(mktemp -d)
(cd "$repo2" && HOME="$home_empty" CLAUDE_CODE_SESSION_ID=nope bash "$telemetry_sh" record "$batch2" phase 02-bar) \
  || { echo "FAIL: record without transcript should exit 0"; exit 1; }
[ -f "$repo2/.claude/cfq/telemetry.jsonl" ] \
  && { echo "FAIL: telemetry.jsonl written despite missing transcript"; exit 1; }

# 5. Sync path, no network: local git target without a remote
target=$(mktemp -d)
git init -q "$target"
git -C "$target" config user.email "test@example.com"
git -C "$target" config user.name "Test"
HOME="$home" bash "$settings_sh" set telemetrySyncRepo "$target" >/dev/null

out=$(HOME="$home" bash "$telemetry_sh" sync "$repo" 2>&1)
rc=$?
[ "$rc" = "0" ] || { echo "FAIL: sync exited $rc despite a failed push (must stay non-fatal)"; exit 1; }
[[ "$out" == *"non-fatal"* ]] || { echo "FAIL: sync output missing non-fatal note: $out"; exit 1; }
name="$(basename "$repo").jsonl"
lines_target=$(wc -l <"$target/$name")
lines_src=$(wc -l <"$jsonl")
[ "$lines_target" = "$lines_src" ] || { echo "FAIL: sync copied $lines_target lines, want $lines_src"; exit 1; }

out=$(HOME="$home" bash "$telemetry_sh" sync "$repo" 2>&1)
[ "$out" = "telemetry sync: nothing new" ] || { echo "FAIL: second sync = $out"; exit 1; }

# 6. bootstrap kind: numbers-only record, no transcript needed, own leaf-field whitelist
out=$(HOME="$home" bash "$telemetry_sh" record "$batch" bootstrap implement-for-queue 3 420)
[ "$out" = "telemetry: bootstrap implement-for-queue 3 calls / 420 ms" ] \
  || { echo "FAIL: unexpected bootstrap record output: $out"; exit 1; }

rec6=$(tail -n 1 "$jsonl")
got=$(jq -r '.kind' <<<"$rec6"); [ "$got" = "bootstrap" ] || { echo "FAIL: bootstrap kind = $got"; exit 1; }
got=$(jq -r '.skill' <<<"$rec6"); [ "$got" = "implement-for-queue" ] || { echo "FAIL: bootstrap skill = $got"; exit 1; }
got=$(jq -r '.call_count' <<<"$rec6"); [ "$got" = "3" ] || { echo "FAIL: bootstrap call_count = $got"; exit 1; }
got=$(jq -r '.duration_ms' <<<"$rec6"); [ "$got" = "420" ] || { echo "FAIL: bootstrap duration_ms = $got"; exit 1; }

allowed_bootstrap='["schema","kind","repo","batch","skill","call_count","duration_ms","timestamp"]'
leaves6=$(jq -c '[paths(scalars) | .[-1]] | unique' <<<"$rec6")
extra6=$(jq -n --argjson a "$allowed_bootstrap" --argjson l "$leaves6" '$l - $a')
[ "$extra6" = "[]" ] || { echo "FAIL: unexpected leaf field(s) in bootstrap telemetry record: $extra6"; exit 1; }

# Non-numeric callCount/durationMs is rejected, not silently coerced.
if HOME="$home" bash "$telemetry_sh" record "$batch" bootstrap implement-for-queue notanumber 420 >/dev/null 2>&1; then
  echo "FAIL: bootstrap accepted a non-numeric callCount"; exit 1
fi

echo PASS
