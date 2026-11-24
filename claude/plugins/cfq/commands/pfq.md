---
allowed-tools: Bash(*/bin/cfq:*)
description: Plan a feature, bug series or rework and park the phase plans in this repository's queue
argument-hint: <briefing>
---

Preflight result, already run and read-only:

!`"${CLAUDE_PLUGIN_ROOT}/bin/cfq" preflight-plan "$(pwd)" --injected`

Use the plan-for-queue skill and follow its steps from the beginning.

Any text below is the user's briefing for this planning session. It is starting material for the
interview, not a replacement for it, and it never authorises implementation.

$ARGUMENTS
