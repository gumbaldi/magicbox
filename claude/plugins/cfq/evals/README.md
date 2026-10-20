# cfq evals

## What this is

Behavioural cases for the cfq skill prose: each one runs a prompt against the plugin in a fresh
headless session and grades the transcript. They run on demand, never in CI, because every run
spends model usage. `tests/test_evals_layout.py` checks only the static layout of this directory.

## Run

```bash
cd <repo-root> && claude plugin eval claude/plugins/cfq --case <name> \
  --runs 1 --ablation none --scaffold --trust-plugin --model sonnet --max-cost-usd 3 \
  --no-publish --json "$TMPDIR/cfq-eval.json" \
  --allow-tools "Bash(*/bin/cfq *)" "Bash(cfq *)" Write Edit
```

Model per skill: pfq cases run with `--model opus`, ifq cases with `--model sonnet`, and a case
that sets its own model gets no `--model`. `--runs 1 --ablation none` is the cheap iteration form;
the default three runs with the no-plugin baseline is the form to quote a score from. Results land
in `evals/results/` (git-ignored). Read the JSON through a filter, never raw.

`ifq-model-gate-stops` sets `model: haiku` itself and must run without a `--model` override, which
would replace it: run it alone with `--tag gate`, and exclude it from any `--model sonnet` pass.

`ifq-haiku-worker-phase` sets `model: sonnet` itself and spawns a real worker, so it needs wider
grants (`Bash(git *)` on top of the usual ones) and no `--model` override. Run it alone:

```bash
cd <repo-root> && claude plugin eval claude/plugins/cfq --tag worker \
  --runs 1 --ablation none --scaffold --trust-plugin --max-cost-usd 5 --no-publish \
  --json "$TMPDIR/cfq-eval.json" \
  --allow-tools "Bash(*/bin/cfq *)" "Bash(cfq *)" "Bash(git *)" Write Edit
```

The suite cannot run on this host yet: fact 1 below is `no` (`socat` is not installed, so the
sandbox the eval requires is unavailable). Install `bubblewrap` and `socat` first.

## Harness facts

Recorded by the spike in batch 053 phase 01 (Claude Code 2.1.293, Linux, `bwrap` present, `socat` missing):

1. cfq runs inside the sandbox: no · `socat not installed`; with `Bash` granted the run is refused before the model starts ("sandbox required but unavailable ... dependencies are missing: socat not installed"), so cfq itself was not exercised. Install `bubblewrap` and `socat`, then re-run the command above to settle it.
2. AskUserQuestion in a headless run: no · the tool is absent from the session's tool list even when the case's `allowed_tools` names it; without `Bash` the model's `preflight-plan` call returned `No such tool available: Bash`, and it ended its turn with a plain-text message offering options instead of asking.
3. fixture.sh resolves its own path into the plugin tree: yes · `${BASH_SOURCE[0]}` was `.../claude/plugins/cfq/evals/pfq-start-block/fixture.sh`; the script runs with the case's workspace as cwd and `HOME` pointing at the run's temporary home.

## Writing a case

A case tests behaviour up to the first user question, because nobody answers one. Graders prefer
`tool_used`, `tool_order` and `regex` over `llm`. Every case carries one grader on the result and
one on the steps. A grader that needs a tool (`Bash`, `Write`, `Edit`) also needs that tool in the
case's `allowed_tools` and in `--allow-tools`, or it can never pass.
