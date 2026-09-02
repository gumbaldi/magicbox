---
allowed-tools: Bash(*/bin/cfq:*)
description: Show implementation reports for finished queue batches
---

!`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" report index --text`

No text below this line: print the block above exactly as it is, then stop — no reformatting, no
summary, no sentence before or after.

Any text below is a filter or a request for a specific view — see the skill's own ## Arguments
section for how repo/batch filters are applied. Use the report-for-queue skill and follow its steps
from the beginning; the block above is current context, not a replacement for the skill's own
steps.

$ARGUMENTS
