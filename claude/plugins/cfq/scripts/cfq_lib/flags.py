"""Deterministic "did anything stand out" flags and size baselines for the report portal.

Pure functions over the batch payload dicts `cfq_portal.build_batch_payload()` produces (the shape
in `.batch-context.md`, Portal data files) -- no I/O, stdlib only, zero model tokens. Thresholds are
constants, not settings.

A flag is `{"level": "warn"|"info", "code", "text", "phase"}`; `phase` is a phase slug or `None`
for a batch-level flag.
"""

import os
import statistics

OUTLIER_FACTOR = 2.0
BASELINE_MIN_SAMPLES = 5
UNDECLARED_SHOWN = 5


def _latest(phase):
    attempts = phase.get("attempts") or []
    return attempts[-1] if attempts else None


def _total(attempt, key):
    cost = attempt.get("cost")
    total = cost.get("total") if isinstance(cost, dict) else None
    value = total.get(key) if isinstance(total, dict) else None
    return value if isinstance(value, (int, float)) else 0


def _phase_usage(phase):
    """`(turns, output)` summed over all of a phase's attempts."""
    attempts = phase.get("attempts") or []
    return (sum(_total(a, "turns") for a in attempts), sum(_total(a, "output") for a in attempts))


def size_points(batches):
    """One point per finished, costed, sized phase: `{batch, phase, size, turns, output}`."""
    points = []
    for b in batches:
        for p in b.get("phases") or []:
            latest = _latest(p)
            if (
                latest is None or p.get("state") == "open" or latest.get("status") != "green"
                or not isinstance(latest.get("cost"), dict) or not p.get("size")
            ):
                continue
            turns, output = _phase_usage(p)
            points.append({
                "batch": b.get("name", ""), "phase": p.get("slug", ""), "size": p["size"],
                "turns": turns, "output": output,
            })
    return sorted(points, key=lambda pt: (pt["batch"], pt["phase"]))


def baselines(points):
    """`{size: {n, turnsMedian, outputMedian}}` for every size that has points."""
    by_size = {}
    for pt in points:
        by_size.setdefault(pt["size"], []).append(pt)
    return {
        size: {
            "n": len(pts),
            "turnsMedian": statistics.median(pt["turns"] for pt in pts),
            "outputMedian": statistics.median(pt["output"] for pt in pts),
        }
        for size, pts in sorted(by_size.items())
    }


def _flag(level, code, text, phase):
    return {"level": level, "code": code, "text": text, "phase": phase}


def _plural(n, noun):
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _resolved(path, repo_root):
    return os.path.normpath(os.path.join(repo_root, path))


def _undeclared(latest, phase, repo_root):
    diffstat = latest.get("diffstat")
    paths = diffstat.get("paths") if isinstance(diffstat, dict) else None
    if not paths:
        return []
    declared = [_resolved(f, repo_root) for f in phase.get("affectedFiles") or []]
    outside = []
    for entry in paths:
        path = entry.get("path") if isinstance(entry, dict) else None
        if not path:
            continue
        full = _resolved(path, repo_root)
        if not any(full == d or full.startswith(d.rstrip(os.sep) + os.sep) for d in declared):
            outside.append(path)
    return outside


def _outlier_text(phase, base):
    turns, output = _phase_usage(phase)
    parts = []
    for label, value, median in (
        ("turns", turns, base["turnsMedian"]), ("output", output, base["outputMedian"]),
    ):
        if median > 0 and value > OUTLIER_FACTOR * median:
            parts.append(f"{label} {value / median:.1f}x")
    if not parts:
        return None
    return f"{', '.join(parts)} the median of {phase['size']} phases"


def phase_flags(phase, base, repo_root):
    """Flags for one phase payload; `base` is the `baselines()` result."""
    attempts = phase.get("attempts") or []
    if not attempts:
        return []
    slug = phase.get("slug", "")
    latest = attempts[-1]
    done = phase.get("state") == "done"
    flags = []

    reds = sum(1 for a in attempts if a.get("status") == "red")
    if reds:
        text = "phase is red" if latest.get("status") == "red" else _plural(reds, "red attempt")
        if latest.get("status") == "red" and reds > 1:
            text += f" after {_plural(reds, 'red attempt')}"
        flags.append(_flag("warn", "red-attempt", text, slug))
    if latest.get("status") == "question":
        flags.append(_flag("warn", "question", "phase ended on an open question", slug))
    if any(a.get("reopened") for a in attempts):
        flags.append(_flag("warn", "reopened", "phase was reopened", slug))
    if done and latest.get("status") == "green" and not latest.get("commit"):
        flags.append(_flag("warn", "no-commit", "green phase without a commit", slug))
    if done and latest.get("cost") is None:
        flags.append(_flag("warn", "no-telemetry", "no telemetry recorded", slug))

    outside = _undeclared(latest, phase, repo_root)
    if outside and not latest.get("deviations"):
        shown = ", ".join(outside[:UNDECLARED_SHOWN])
        more = f" +{len(outside) - UNDECLARED_SHOWN} more" if len(outside) > UNDECLARED_SHOWN else ""
        flags.append(_flag("warn", "undeclared-files", f"files outside the plan without a deviation: {shown}{more}", slug))

    size_base = base.get(phase.get("size"))
    if (
        size_base and size_base["n"] >= BASELINE_MIN_SAMPLES and latest.get("status") == "green"
        and isinstance(latest.get("cost"), dict) and phase.get("state") != "open"
    ):
        text = _outlier_text(phase, size_base)
        if text:
            flags.append(_flag("warn", "cost-outlier", text, slug))

    observations = sum(len(a.get("observations") or []) for a in attempts)
    if observations:
        flags.append(_flag("info", "observations", _plural(observations, "observation"), slug))
    parked = sum(len(a.get("parkedPlanEntries") or []) for a in attempts)
    if parked:
        flags.append(_flag("info", "parked-entries", f"{parked} plan {'entry' if parked == 1 else 'entries'} parked", slug))
    triggers = sorted({t for a in attempts for t in a.get("triggers") or []})
    if triggers:
        flags.append(_flag("info", "triggers", f"triggers: {', '.join(triggers)}", slug))
    if latest.get("settled") is False:
        flags.append(_flag("info", "provisional", "telemetry not settled yet", slug))

    return sort_flags(flags)


def sort_flags(flags):
    return sorted(flags, key=lambda f: (f["phase"] is None, f["phase"] or "", f["level"] != "warn", f["code"]))


def batch_flags(batch, base, repo_root):
    """Every phase flag plus the batch-level ones, in deterministic order."""
    flags = []
    for p in batch.get("phases") or []:
        flags += phase_flags(p, base, repo_root)

    closing = batch.get("closing")
    if isinstance(closing, dict):
        errors = closing.get("errors") or []
        if errors:
            flags.append(_flag("warn", "finish-errors", f"finish reported {_plural(len(errors), 'error')}", None))
        lang = closing.get("lang") if isinstance(closing.get("lang"), dict) else {}
        issues = lang.get("issues")
        if isinstance(issues, (int, float)) and issues > 0:
            flags.append(_flag("warn", "lang-issues", f"{_plural(int(issues), 'language issue')}", None))
        security = closing.get("security") if isinstance(closing.get("security"), dict) else {}
        new = security.get("new") if isinstance(security.get("new"), dict) else {}
        found = {k: v for k, v in new.items() if isinstance(v, (int, float)) and v > 0}
        if found:
            detail = ", ".join(f"{k} +{v}" for k, v in sorted(found.items()))
            flags.append(_flag("warn", "security-new", f"new security findings: {detail}", None))

    planning = batch.get("planning")
    if isinstance(planning, dict) and planning.get("settled") is False:
        flags.append(_flag("info", "provisional", "planning telemetry not settled yet", None))

    return sort_flags(flags)
