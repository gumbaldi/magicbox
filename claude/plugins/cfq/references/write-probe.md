# Write Probe: Fail Before the Interview, Not After It

Read at the end of Step 4, once the interview-depth answer is in and before Step 5 starts.

A `PreToolUse` hook on `Write`/`Edit` can deny exactly the calls Step 15 depends on. Finding that
out in Step 15 costs the whole interview. Probing costs one `Write` and one `rm`.

## Procedure

1. **Queue probe, always.** Write the single line `probe` to
   `<repo-root>/.claude/cfq/.writeprobe` **with the `Write` tool**. Never with `Bash`: the hook
   intercepts tool calls, not filesystem writes, so a shell write succeeds on a repo where `Write`
   is denied and proves nothing.
2. **Docs probe, only on "Grilling with docs".** Write the same line to
   `<repo-root>/docs/adr/.writeprobe`. Then check `test -f "<repo-root>/CONTEXT.md"`: if it does
   **not** exist, probe it too, at that exact path. If it does exist, skip it and note
   `⚠️ CONTEXT.md exists, not probed` on the sub-line — there is no non-destructive way to test a
   basename-driven rule against an existing file, and clobbering a glossary to test a hook is not a
   trade worth making.
3. **Clean up** with one `Bash` call: `rm -f` over whichever probe paths were written, plus
   `rmdir --ignore-fail-on-non-empty` for a `docs/adr/` this step created.

## On denial

End the session, exactly as `status: "NO_REPO"` does in Step 4. Print `❌ Write Probe` with the
blocking hook's own `stopReason` quoted verbatim as the sub-line — the user needs the hook's message
to find the hook, and paraphrasing it loses the path it names. Nothing has been parked at this
point, so there is nothing to roll back.

Never work around a denial. Not by falling back to `Bash` for the phase files — that defeats the
guard the user configured and leaves them with an unaudited write. And never by writing an unlock
marker of any kind: those lift the guard for the entire session rather than for the queue, which
would let this session write product code too. A planning session does not disable its own guard.
That decision is fixed; treat a request to "just probe again" as a request to end and restart.

Contract for what a guard hook has to allow: **Hook contract** in the plugin's `README.md`.
