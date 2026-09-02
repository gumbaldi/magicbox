---
allowed-tools: Bash(*/bin/cfq:*)
description: Show the cross-repo queue dashboard and manage cfq settings
---

!`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" dash render`

No text below this line: print the block above exactly as it is, then stop — no reformatting, no
summary, no sentence before or after.

Any text below is a filter or a request for a specific view (a repo name, a settings key, a
management action). Use the code-for-queue skill and follow its steps from the beginning; the block
above is current context, not a replacement for the skill's own steps.

$ARGUMENTS
