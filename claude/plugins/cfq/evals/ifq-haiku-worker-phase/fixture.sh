#!/usr/bin/env bash
set -euo pipefail
git init -q -b main .
git config user.email "fixture@example.invalid"
git config user.name "Fixture"
printf '#!/usr/bin/env bash\necho "step one"\necho "step two"\n' > tool.sh
git add tool.sh
git commit -q -m "Add tool.sh"
store="$HOME/.claude/cfq"
install -d "$store"
printf '{\n  "setupDone": true\n}\n' > "$store/state.json"
printf '{\n  "implModels": ["sonnet", "haiku"],\n  "orchestratorModels": ["sonnet"],\n  "branchPerBatch": false\n}\n' > "$store/settings.json"
printf '{\n  "repos": [\n    "%s"\n  ]\n}\n' "$(pwd -P)" > "$store/repos.json"

# One parked batch with one open phase, written through the same bin/cfq sequence plan-for-queue's
# Park step runs. The plugin's dispatcher is resolved from this script's own location.
cfq="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/bin/cfq"
repo="$(pwd -P)"
batch="$("$cfq" batch allocate "$repo" 2026-01-01 verbose-flag | python3 -c 'import json,sys; print(json.load(sys.stdin)["batch"])')"
dir="$repo/.claude/cfq/impl/$batch"
cat > "$dir/01-add-verbose-flag.md" <<PHASE
# Add the verbose flag

## Size

S

## Model

haiku

## Context

tool.sh prints each step silently. A --verbose flag should print the step before running it.

## Affected Files

- \`$repo/tool.sh\`

## Changes

1. Add a \`--verbose\` flag to tool.sh that echoes each step name before it runs.

## Verification

\`\`\`bash
bash $repo/tool.sh --verbose | head -3
\`\`\`

Expected: the first line printed is \`step one\`.
PHASE
cat > "$dir/.batch-context.md" <<'CTX'
# Batch Context

## Goal

Give tool.sh a --verbose flag.
CTX
"$cfq" park "$repo" "$batch" normal
"$cfq" batch ready "$dir"
