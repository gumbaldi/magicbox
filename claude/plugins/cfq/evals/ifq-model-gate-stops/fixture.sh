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
printf '{\n  "repos": [\n    "%s"\n  ]\n}\n' "$(pwd -P)" > "$store/repos.json"
printf '{\n  "implModels": ["sonnet"],\n  "orchestratorModels": []\n}\n' > "$store/settings.json"
