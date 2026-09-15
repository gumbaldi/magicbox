"""Canonical repo-local CFQ path helpers.

Pure string work only, no mutation, no I/O.
"""

# The queue's path components relative to a repo root, as a tuple rather than a string so a
# consumer that needs to test whether some other path has ".claude/cfq" as consecutive path
# components (cfq_guard.py) can walk it without re-typing the literal.
QUEUE_DIR_COMPONENTS = (".claude", "cfq")
QUEUE_DIR_REL = "/".join(QUEUE_DIR_COMPONENTS)


def cfq_repo_dir(repo):
    return f"{repo}/{QUEUE_DIR_REL}"


def plan_dir(repo):
    return f"{repo}/{QUEUE_DIR_REL}/plan"


def impl_dir(repo):
    return f"{repo}/{QUEUE_DIR_REL}/impl"


def impl_done_dir(repo):
    return f"{repo}/{QUEUE_DIR_REL}/impl/done"


def todo_dir(repo):
    return f"{repo}/{QUEUE_DIR_REL}/todo"


def repo_settings_file(repo):
    return f"{repo}/{QUEUE_DIR_REL}/settings.json"


def lockfile(repo):
    return f"{repo}/{QUEUE_DIR_REL}/.lock"


def maintenance_marker(repo):
    return f"{repo}/{QUEUE_DIR_REL}/.maintenance"


def telemetry_log(repo):
    return f"{repo}/{QUEUE_DIR_REL}/telemetry.jsonl"
