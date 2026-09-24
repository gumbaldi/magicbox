#!/usr/bin/env python3
# Usage: cfq_settings.py list [--repo <path>] [--sources]
#        cfq_settings.py get [--repo <path>] [--source] <key>
#        cfq_settings.py set [--repo <path>] <key> <value>
#        cfq_settings.py unset [--repo <path>] <key>
#        cfq_settings.py describe [<key>]
#        cfq_settings.py menu [--repo <path>] [--group <id>] [--format text|json]
#        cfq_settings.py migrate <repo-root>
#        cfq_settings.py state get <key> | state set <key> <value>
"""Manages cfq settings: $HOME/.claude/cfq/settings.json (global) and, per repo,
<repo>/.claude/cfq/settings.json (repo-scoped overrides).

Ported from cfq-settings.sh — a port, not a redesign: exit codes, stdout shapes and error
messages are the invariant this file preserves, not something it improves on.
"""

import argparse
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cfq_lib import errors, paths, render, text  # noqa: E402
from cfq_lib.env import home_dir  # noqa: E402

# The eight fixed settings-menu groups, in display order — `settings menu` walks this list, never
# a set (whose iteration order isn't a promise), so the group order is always this order.
GROUPS = [
    {"id": "models", "title": "Models"},
    {"id": "planning", "title": "Planning"},
    {"id": "implementation", "title": "Implementation"},
    {"id": "limits", "title": "Limits & handoff"},
    {"id": "language", "title": "Language & docs"},
    {"id": "maintenance", "title": "Maintenance & security"},
    {"id": "reports", "title": "Reports & telemetry"},
    {"id": "repo", "title": "Repo & git"},
]
GROUP_IDS = [g["id"] for g in GROUPS]

# Single source of truth for every key: type, default, scope, env mapping, description, group,
# plus type-specific validation data (min/max for int, values for enum, pattern for string, shape
# for object). list/get/set/unset/describe/menu and env overrides all walk this generically — a
# new key is one entry here, never a second hand-written case arm.
SCHEMA = {
    "grillMode": {"type": "enum", "default": "stepwise", "values": ["stepwise", "classic"], "scope": ["global", "repo"], "env": "CFQ_GRILL_MODE", "group": "planning", "description": "Interview style for /pfq: stepwise (one question at a time) or classic."},
    "planModels": {"type": "array", "default": ["opus", "fable"], "scope": ["global", "repo"], "env": "CFQ_PLAN_MODELS", "group": "models", "description": "Models /pfq is allowed to run under."},
    "implModels": {"type": "array", "default": ["sonnet"], "scope": ["global", "repo"], "env": "CFQ_IMPL_MODELS", "group": "models", "description": "Models /ifq is allowed to run under."},
    "orchestratorMode": {"type": "bool", "default": True, "scope": ["global", "repo"], "env": "CFQ_ORCHESTRATOR_MODE", "group": "implementation", "description": "/ifq runs each phase in its own sub-agent instead of implementing in the session itself."},
    "orchestratorModels": {"type": "array", "default": [], "scope": ["global", "repo"], "env": "CFQ_ORCHESTRATOR_MODELS", "group": "models", "description": "Models the orchestrator session itself is allowed to run under; falls back to implModels when empty."},
    "planExploreModel": {"type": "string", "default": "haiku", "scope": ["global", "repo"], "env": "CFQ_PLAN_EXPLORE_MODEL", "group": "models", "description": "Model used for /pfq exploratory sub-agent research."},
    "implExploreModel": {"type": "string", "default": "haiku", "scope": ["global", "repo"], "env": "CFQ_IMPL_EXPLORE_MODEL", "group": "models", "description": "Model used for /ifq exploratory sub-agent research and mechanical test-run delegation."},
    "allowAnyModel": {"type": "bool", "default": False, "scope": ["global", "repo"], "env": "CFQ_ALLOW_ANY_MODEL", "group": "models", "description": "Skip the implModels/planModels gate entirely."},
    "scanRoots": {"type": "array", "default": ["~/git"], "scope": ["global"], "env": "CFQ_SCAN_ROOTS", "group": "repo", "description": "Root directories cfq_scan.py searches for repos with a queue."},
    "useMattpocockGrilling": {"type": "bool", "default": True, "scope": ["global", "repo"], "env": "CFQ_USE_MATTPOCOCK", "group": "planning", "description": "Use the mattpocock-skills grilling skill instead of the built-in one, when installed."},
    "usePonytailAudit": {"type": "bool", "default": True, "scope": ["global", "repo"], "env": "CFQ_USE_PONYTAIL", "group": "maintenance", "description": "Run ponytail-audit during maintenance."},
    "codeLanguage": {"type": "string", "default": "en", "pattern": "^[A-Za-z][A-Za-z-]*$", "scope": ["global", "repo"], "env": "CFQ_CODE_LANGUAGE", "group": "language", "description": "Language of everything executed or read as an instruction: code, comments, commit messages, README, CLAUDE.md, SKILL.md."},
    "docLanguages": {"type": "array", "default": [], "scope": ["global", "repo"], "env": "CFQ_DOC_LANGUAGES", "group": "language", "description": "Additional languages kept under docs/<lang>/; empty means documentation follows codeLanguage alone."},
    "docLevel": {"type": "enum", "default": "minimal", "values": ["minimal", "standard"], "scope": ["global", "repo"], "env": "CFQ_DOC_LEVEL", "group": "language", "description": "How much documentation a repo keeps: minimal (README only) or standard."},
    "maintenanceEvery": {"type": "int", "default": 50, "min": 0, "scope": ["global", "repo"], "env": "CFQ_MAINTENANCE_EVERY", "group": "maintenance", "description": "Commits since the last maintenance run before the next one is due; 0 disables maintenance entirely."},
    "branchPerBatch": {"type": "bool", "default": True, "scope": ["global", "repo"], "env": None, "group": "implementation", "description": "Create a dedicated branch per implementation batch instead of committing to the checked-out branch."},
    "changelogFile": {"type": "string", "default": ".claude/cfq/changelog.yml", "scope": ["global", "repo"], "env": None, "group": "reports", "description": "Filename of the per-repo changelog cfq_changelog.py writes to."},
    "htmlReport": {"type": "bool", "default": True, "scope": ["global", "repo"], "env": None, "group": "reports", "description": "Maintain the HTML report portal under `.claude/cfq/reports/` (and `reportDir`); false turns every automatic sync off."},
    "planBlockedPlugins": {"type": "array", "default": ["superpowers"], "scope": ["global", "repo"], "env": None, "group": "planning", "description": "Plugins /pfq must never call, even indirectly."},
    "implBlockedPlugins": {"type": "array", "default": ["superpowers"], "scope": ["global", "repo"], "env": None, "group": "implementation", "description": "Plugins /ifq must never call, even indirectly."},
    "telemetrySyncRepo": {"type": "string", "default": "", "pattern": "^($|/.*)$", "scope": ["global", "repo"], "env": "CFQ_TELEMETRY_SYNC_REPO", "group": "reports", "description": "Absolute path of a repo telemetry is additionally synced to; empty disables sync."},
    "frameworkRepo": {"type": "string", "default": "", "pattern": "^($|/.*)$", "scope": ["global"], "env": "CFQ_FRAMEWORK_REPO", "group": "repo", "description": "Absolute path of the local cfq source repo; findings about cfq itself are parked there instead of in the repo being worked on. Empty means they collect in the global framework inbox."},
    "stopUsed": {"type": "int", "default": 125000, "min": -1, "scope": ["global", "repo"], "env": "CFQ_STOP_USED", "group": "limits", "description": "Absolute context tokens (input+cache_read+cache_creation) at which /ifq hands off instead of starting another phase; 0 means hand off after every phase, -1 means never stop for this reason."},
    "stopFiveHourPct": {"type": "int", "default": 70, "min": -1, "scope": ["global", "repo"], "env": "CFQ_STOP_FIVE_HOUR_PCT", "group": "limits", "description": "Five-hour rate-limit usage in percent at which /ifq hands off instead of starting another phase; -1 disables the check."},
    "stopSevenDayPct": {"type": "int", "default": 95, "min": -1, "scope": ["global", "repo"], "env": "CFQ_STOP_SEVEN_DAY_PCT", "group": "limits", "description": "Seven-day rate-limit usage in percent at which /ifq hands off instead of starting another phase; -1 disables the check."},
    "onePhasePerSession": {"type": "bool", "default": True, "scope": ["global", "repo"], "env": "CFQ_ONE_PHASE_PER_SESSION", "group": "implementation", "description": "When true, /ifq always hands off after one phase instead of continuing automatically while the context gate allows it."},
    "sessionStaleSeconds": {"type": "int", "default": 1800, "min": 1, "scope": ["global", "repo"], "env": "CFQ_SESSION_STALE_SECONDS", "group": "limits", "description": "Seconds since a session transcript was last touched before it is considered stale (lock takeover, resume staleness)."},
    "ctxWindowLimits": {"type": "object", "shape": {"default": "int", "large": "object"}, "default": {"default": 200000, "large": {"models": ["claude-opus-5", "claude-sonnet-5", "claude-opus-4-8"], "limit": 1000000}}, "scope": ["global", "repo"], "env": None, "group": "limits", "description": "Context-window size in tokens per model, keyed by whether the model gets the large window."},
    "securityTimeoutSeconds": {"type": "int", "default": 30, "min": 1, "scope": ["global"], "env": None, "group": "maintenance", "description": "Timeout in seconds for the batch-completion security scan."},
    "securityFindingsCap": {"type": "int", "default": 20, "min": 1, "scope": ["global"], "env": None, "group": "maintenance", "description": "Maximum number of security findings surfaced per batch-completion scan."},
    "gitStatePolicy": {"type": "enum", "default": "local", "values": ["local", "trackable"], "scope": ["global", "repo"], "env": None, "group": "repo", "description": "Whether repo-local cfq workflow state is Git-excluded locally (local) or left to normal repository tracking (trackable)."},
    "i18nExcludePatterns": {"type": "array", "default": ["*/locales/*", "*/locale/*", "*/i18n/*", "*/lang/*", "*/translations/*"], "scope": ["global", "repo"], "env": None, "group": "language", "description": "Git pathspec exclusions applied to the /ifq language-prose sample — directories that intentionally hold multiple languages (i18n/locale resource files), never judged as a codeLanguage violation."},
    "reportDir": {"type": "string", "default": "", "pattern": "^($|/.*)$", "scope": ["global", "repo"], "env": "CFQ_REPORT_DIR", "group": "reports", "description": "Additional copy of every repo's report portal plus a cross-repo index; empty = repo-local only."},
    "planExploreModelComplex": {"type": "string", "default": "sonnet", "scope": ["global", "repo"], "env": "CFQ_PLAN_EXPLORE_MODEL_COMPLEX", "group": "models", "description": "Model for /pfq Explore agents whose task is to judge rather than to locate."},
    "implExploreModelComplex": {"type": "string", "default": "sonnet", "scope": ["global", "repo"], "env": "CFQ_IMPL_EXPLORE_MODEL_COMPLEX", "group": "models", "description": "Model for /ifq Explore agents whose task is to judge rather than to locate."},
}

DEFAULTS = {k: v["default"] for k, v in SCHEMA.items()}

GLOBAL_DIR = f"{home_dir()}/.claude/cfq"
GLOBAL_SETTINGS_FILE = f"{GLOBAL_DIR}/settings.json"
STATE_FILE = f"{GLOBAL_DIR}/state.json"

INT_RE = re.compile(r"^-?\d+$")

PROG = "cfq_settings.py"


def _read_json(path, default):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_raw(path, text):
    with open(path, "w") as f:
        f.write(text)


def _write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def ensure():
    os.makedirs(GLOBAL_DIR, exist_ok=True)
    if not os.path.isfile(GLOBAL_SETTINGS_FILE):
        _write_raw(GLOBAL_SETTINGS_FILE, "{}\n")


def ensure_state():
    os.makedirs(GLOBAL_DIR, exist_ok=True)
    if not os.path.isfile(STATE_FILE):
        _write_raw(STATE_FILE, "{}\n")


def _merge_objects(base, overlay):
    """jq's `*` operator: recursive merge, overlay wins, nested dicts merge recursively rather
    than replacing a sibling field wholesale."""
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge_objects(result[k], v)
        else:
            result[k] = v
    return result


def merge_tier_file(base, file_path):
    """Overlays one JSON file's known keys onto `base`. Object-typed keys merge recursively (a
    partial override must not erase sibling fields); everything else replaces fully. A missing
    file, or one that doesn't parse to a JSON object, leaves `base` unchanged."""
    if not os.path.isfile(file_path):
        return dict(base)
    overlay = _read_json(file_path, default={})
    if not isinstance(overlay, dict):
        return dict(base)
    result = dict(base)
    for k, v in overlay.items():
        if k not in result:
            continue
        if SCHEMA.get(k, {}).get("type") == "object":
            result[k] = _merge_objects(result.get(k) or {}, v)
        else:
            result[k] = v
    return result


def merged_tiers(repo_path):
    """Three tiers below env, highest wins: <repo>/.claude/cfq/settings.json (if repo_path
    given) > $HOME/.claude/cfq/settings.json > schema default."""
    base = merge_tier_file(DEFAULTS, GLOBAL_SETTINGS_FILE)
    if repo_path:
        base = merge_tier_file(base, paths.repo_settings_file(repo_path))
    if base.get("docLevel") == "full":
        # docLevel dropped "full" -- a value stored by an older cfq reads back as "standard"
        # rather than erroring, and the file is never rewritten just for reading it.
        base["docLevel"] = "standard"
    return base


def with_overrides(data):
    """Applies env-var overrides on top of tiered JSON, walking SCHEMA generically. Precedence:
    env > everything piped in."""
    result = dict(data)
    for key, entry in SCHEMA.items():
        env_name = entry.get("env")
        if not env_name:
            continue
        val = os.environ.get(env_name, "")
        if not val:
            continue
        type_ = entry["type"]
        if type_ == "bool":
            result[key] = val == "1"
        elif type_ == "int":
            if INT_RE.match(val):
                result[key] = int(val)
            # malformed -- skip, leaves tiered value in place
        elif type_ == "array":
            result[key] = val.split(",")
        elif type_ == "object":
            # No key currently maps an env var to an object type; recursive merge is here so a
            # future one is handled without touching this loop again.
            try:
                parsed = json.loads(val)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                result[key] = _merge_objects(result.get(key) or {}, parsed)
        else:  # enum, string
            result[key] = val
    return result


def key_source(key, repo_path, base_json, final_json):
    """Determines which tier actually supplied `key`'s final value: env:process /
    env:repo-legacy / repo / global / default. "global"/"repo" mean the key is actually present
    in that tier's file on disk — ensure() only ever materializes an empty {} for a fresh global
    file, so a key no one ever `set` stays "default" no matter how many other calls touched it."""
    entry = SCHEMA.get(key, {})
    env_name = entry.get("env")
    if env_name:
        same = base_json.get(key) == final_json.get(key)
        if not same:
            if repo_path:
                legacy_settings = os.path.join(repo_path, ".claude", "settings.json")
                if os.path.isfile(legacy_settings):
                    legacy = _read_json(legacy_settings, default={})
                    legacy_env = legacy.get("env", {}) if isinstance(legacy, dict) else {}
                    legacy_val = legacy_env.get(env_name, "") if isinstance(legacy_env, dict) else ""
                    if legacy_val and legacy_val == os.environ.get(env_name, ""):
                        return "env:repo-legacy"
            return "env:process"
    if repo_path:
        repo_file = paths.repo_settings_file(repo_path)
        if os.path.isfile(repo_file):
            repo_data = _read_json(repo_file, default={})
            if isinstance(repo_data, dict) and key in repo_data:
                return "repo"
    if os.path.isfile(GLOBAL_SETTINGS_FILE):
        global_data = _read_json(GLOBAL_SETTINGS_FILE, default={})
        if isinstance(global_data, dict) and key in global_data:
            return "global"
    return "default"


def _apply_set(key, val, repo_path):
    entry = SCHEMA.get(key)
    if entry is None:
        errors.die(f"{PROG}: unknown key '{key}'")

    if repo_path:
        if "repo" not in entry["scope"]:
            errors.die(f"{PROG}: '{key}' cannot be set per repo (scope is global-only)")
        os.makedirs(os.path.join(repo_path, ".claude", "cfq"), exist_ok=True)
        target = paths.repo_settings_file(repo_path)
        if not os.path.isfile(target):
            _write_raw(target, "{}\n")
        data = _read_json(target, default={})
    else:
        ensure()
        target = GLOBAL_SETTINGS_FILE
        data = _read_json(target, default={})

    type_ = entry["type"]
    if type_ == "bool":
        if val not in ("true", "false"):
            errors.die(f"{PROG}: '{key}' must be true or false")
        data[key] = val == "true"
    elif type_ == "int":
        if not INT_RE.match(val):
            errors.die(f"{PROG}: '{key}' must be an integer")
        n = int(val)
        if "min" in entry and n < entry["min"]:
            errors.die(f"{PROG}: '{key}' must be >= {entry['min']}")
        if "max" in entry and n > entry["max"]:
            errors.die(f"{PROG}: '{key}' must be <= {entry['max']}")
        data[key] = n
    elif type_ == "enum":
        if val not in entry["values"]:
            allowed = ", ".join(entry["values"])
            errors.die(f"{PROG}: '{key}' must be one of {allowed}")
        data[key] = val
    elif type_ == "string":
        pattern = entry.get("pattern")
        if pattern and not re.search(pattern, val):
            errors.die(f"{PROG}: '{key}' does not match the required pattern")
        data[key] = val
    elif type_ == "array":
        data[key] = val.split(",")
    elif type_ == "object":
        try:
            parsed = json.loads(val)
        except json.JSONDecodeError:
            errors.die(f"{PROG}: '{key}' must be valid JSON")
        shape = entry.get("shape", {})
        if not isinstance(parsed, dict) or (set(parsed.keys()) - set(shape.keys())):
            errors.die(f"{PROG}: '{key}' has unknown fields")
        data[key] = parsed

    _write_json(target, data)


def cmd_list(args):
    ensure()
    base = merged_tiers(args.repo)
    final = with_overrides(base)
    if args.want_source:
        out = {k: {"value": final.get(k), "source": key_source(k, args.repo, base, final)} for k in SCHEMA}
        print(render.dump_json(out))
    else:
        print(render.dump_json(final))


def cmd_get(args):
    ensure()
    base = merged_tiers(args.repo)
    final = with_overrides(base)
    if args.want_source:
        src = key_source(args.key, args.repo, base, final)
        print(render.dump_json({"value": final.get(args.key), "source": src}))
        return
    type_ = SCHEMA.get(args.key, {}).get("type", "")
    value = final.get(args.key)
    if type_ == "array":
        print(",".join(value))
    elif type_ == "object":
        print(render.dump_json(value))
    else:
        print(render.tostring(value))


def cmd_set(args):
    _apply_set(args.key, args.value, args.repo)


def cmd_unset(args):
    key = args.key
    if key not in SCHEMA:
        errors.die(f"{PROG}: unknown key '{key}'")
    if args.repo:
        target = paths.repo_settings_file(args.repo)
        if not os.path.isfile(target):
            return
        data = _read_json(target, default={})
    else:
        ensure()
        target = GLOBAL_SETTINGS_FILE
        data = _read_json(target, default={})
    data.pop(key, None)
    _write_json(target, data)


def cmd_describe(args):
    fields = ("type", "default", "scope", "env", "description")
    if args.key:
        entry = SCHEMA.get(args.key, {})
        print(render.dump_json({f: entry.get(f) for f in fields}))
    else:
        out = {k: {f: v.get(f) for f in fields} for k, v in SCHEMA.items()}
        print(render.dump_json(out))


def _marker(source):
    """Maps a `key_source()` result onto the four-letter legend `settings menu` prints:
    [D] default [G] global [R] repo [E] env — both env flavours (`env:process` and the legacy
    `env:repo-legacy`) share the E marker, distinguished in text output by a trailing note
    instead of a fifth letter."""
    if source in ("env:process", "env:repo-legacy"):
        return "E"
    if source == "repo":
        return "R"
    if source == "global":
        return "G"
    return "D"


def _format_menu_value(entry, value):
    type_ = entry["type"]
    if type_ == "array":
        return ",".join(value) if value else ""
    if type_ == "object":
        return render.dump_json(value)
    return render.tostring(value)


def _range_str(entry):
    """Allowed-values-or-range text for `settings menu --group`'s type column: enum lists its
    values, int shows its min/max bounds, string shows its validation pattern. Empty for a type
    with none of the three (bool, array, object)."""
    type_ = entry["type"]
    if type_ == "enum":
        return "one of " + "|".join(entry["values"])
    if type_ == "int":
        parts = []
        if "min" in entry:
            parts.append(f">= {entry['min']}")
        if "max" in entry:
            parts.append(f"<= {entry['max']}")
        return ", ".join(parts)
    if type_ == "string" and entry.get("pattern"):
        return f"pattern {entry['pattern']}"
    return ""


def _repo_label(repo_path):
    return pathlib.Path(repo_path).name or "global" if repo_path else "global"


LEGEND = "[D] default  [G] global  [R] repo  [E] env"


def _menu_groups(args, base, final):
    """Builds `{groups:[{id,title,keys:[...]}]}`'s `groups` list -- the one data structure every
    `settings menu` format (text overview, text --group, --format json) renders from, so the three
    can never disagree about a key's value/source/marker."""
    keys_by_group = {g["id"]: [] for g in GROUPS}
    for key, entry in SCHEMA.items():
        keys_by_group[entry["group"]].append(key)

    groups_out = []
    for g in GROUPS:
        if args.group and g["id"] != args.group:
            continue
        group_keys = []
        for key in keys_by_group[g["id"]]:
            entry = SCHEMA[key]
            source = key_source(key, args.repo, base, final)
            group_keys.append({
                "key": key,
                "value": final.get(key),
                "source": source,
                "marker": _marker(source),
                "type": entry["type"],
                "values": entry.get("values"),
                "min": entry.get("min"),
                "scopes": entry["scope"],
                "default": entry["default"],
                "description": entry["description"],
            })
        groups_out.append({"id": g["id"], "title": g["title"], "keys": group_keys})
    return groups_out


def _render_menu_overview(groups_out, repo_path):
    lines = [f"SETTINGS · {_repo_label(repo_path)}", LEGEND, ""]
    for i, g in enumerate(groups_out, start=1):
        lines.append(f"{i}. {g['title']}")
        # Non-default keys first (stable sort keeps each side in schema-declared order).
        ordered = sorted(g["keys"], key=lambda k: k["source"] == "default")
        preview, remaining = ordered[:2], len(ordered) - min(2, len(ordered))
        rows = [
            [f"[{k['marker']}]", k["key"], _format_menu_value(SCHEMA[k["key"]], k["value"])]
            for k in preview
        ]
        lines.extend(text.table(rows, indent="   "))
        if remaining > 0:
            lines.append(f"   … +{remaining}")
        lines.append("")
    # A trailing all-empty column (the last row's notes cell, or a value cell of "") still gets a
    # gap inserted ahead of it by text.table() -- rstrip every line rather than special-case it.
    return "\n".join(ln.rstrip() for ln in lines).rstrip("\n")


def _render_menu_group(group_out, repo_path):
    lines = [f"SETTINGS · {_repo_label(repo_path)} · {group_out['title']}", LEGEND, ""]
    rows = []
    for k in group_out["keys"]:
        entry = SCHEMA[k["key"]]
        notes = []
        if "repo" not in entry["scope"]:
            notes.append("global only")
        if k["source"] == "env:repo-legacy":
            notes.append("(legacy env)")
        rows.append([
            f"[{k['marker']}]",
            k["key"],
            _format_menu_value(entry, k["value"]),
            entry["type"],
            _range_str(entry),
            " ".join(notes),
        ])
    lines.extend(text.table(rows, indent="  "))
    return "\n".join(ln.rstrip() for ln in lines)


def cmd_menu(args):
    ensure()
    if args.group and args.group not in GROUP_IDS:
        errors.fail("UNKNOWN_GROUP", detail=f"unknown group '{args.group}', want one of {', '.join(GROUP_IDS)}")
    base = merged_tiers(args.repo)
    final = with_overrides(base)
    groups_out = _menu_groups(args, base, final)

    if args.format == "json":
        print(render.dump_json({"groups": groups_out}))
        return
    if args.group:
        print(_render_menu_group(groups_out[0], args.repo))
    else:
        print(_render_menu_overview(groups_out, args.repo))


def cmd_migrate(args):
    repo_root = args.repo_root
    legacy = os.path.join(repo_root, ".claude", "settings.json")
    if not os.path.isfile(legacy):
        print(f"{PROG}: no {legacy} found, nothing to migrate")
        return
    legacy_data = _read_json(legacy, default={})
    env_block = legacy_data.get("env", {}) if isinstance(legacy_data, dict) else {}
    if not isinstance(env_block, dict):
        env_block = {}
    migrated = 0
    for key, entry in SCHEMA.items():
        env_name = entry.get("env")
        if not env_name:
            continue
        val = env_block.get(env_name)
        if not val:
            continue
        _apply_set(key, str(val), repo_root)
        print(f"migrated {key} = {val}")
        migrated += 1
    print(f"done — {migrated} key(s) migrated into {repo_root}/.claude/cfq/settings.json; original {legacy} left untouched")


def cmd_state_get(args):
    ensure_state()
    data = _read_json(STATE_FILE, default={})
    value = data.get(args.key)
    if value is None or value is False:
        print("null")
    else:
        print(render.tostring(value))


def cmd_state_set(args):
    ensure_state()
    try:
        parsed = json.loads(args.value)
    except json.JSONDecodeError:
        errors.die(f"{PROG}: state value must be valid JSON")
    data = _read_json(STATE_FILE, default={})
    data[args.key] = parsed
    _write_json(STATE_FILE, data)


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    list_p = sub.add_parser("list")
    list_p.add_argument("--repo")
    list_p.add_argument("--global", action="store_true", dest="_global")
    list_p.add_argument("--source", "--sources", action="store_true", dest="want_source")
    list_p.set_defaults(func=cmd_list)

    get_p = sub.add_parser("get")
    get_p.add_argument("--repo")
    get_p.add_argument("--global", action="store_true", dest="_global")
    get_p.add_argument("--source", "--sources", action="store_true", dest="want_source")
    get_p.add_argument("key")
    get_p.set_defaults(func=cmd_get)

    set_p = sub.add_parser("set")
    set_p.add_argument("--repo")
    set_p.add_argument("--global", action="store_true", dest="_global")
    set_p.add_argument("key")
    set_p.add_argument("value")
    set_p.set_defaults(func=cmd_set)

    unset_p = sub.add_parser("unset")
    unset_p.add_argument("--repo")
    unset_p.add_argument("--global", action="store_true", dest="_global")
    unset_p.add_argument("key")
    unset_p.set_defaults(func=cmd_unset)

    describe_p = sub.add_parser("describe")
    describe_p.add_argument("key", nargs="?")
    describe_p.set_defaults(func=cmd_describe)

    menu_p = sub.add_parser("menu")
    menu_p.add_argument("--repo")
    menu_p.add_argument("--group")
    menu_p.add_argument("--format", choices=["text", "json"], default="text")
    menu_p.set_defaults(func=cmd_menu)

    migrate_p = sub.add_parser("migrate")
    migrate_p.add_argument("repo_root")
    migrate_p.set_defaults(func=cmd_migrate)

    state_p = sub.add_parser("state")
    state_sub = state_p.add_subparsers(dest="state_cmd")
    state_get_p = state_sub.add_parser("get")
    state_get_p.add_argument("key")
    state_get_p.set_defaults(func=cmd_state_get)
    state_set_p = state_sub.add_parser("set")
    state_set_p.add_argument("key")
    state_set_p.add_argument("value")
    state_set_p.set_defaults(func=cmd_state_set)
    state_p.set_defaults(func=None)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if args.cmd == "state" and func is None:
        errors.die(f"usage: {PROG} state get <key> | state set <key> <value>")
    if func is None:
        errors.die(
            f"usage: {PROG} list [--repo <path>] [--sources] | get [--repo <path>] [--source] <key> | "
            f"set [--repo <path>] <key> <value> | unset [--repo <path>] <key> | describe [<key>] | "
            f"menu [--repo <path>] [--group <id>] [--format text|json] | "
            f"migrate <repo-root> | state get <key> | state set <key> <value>"
        )
    func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
