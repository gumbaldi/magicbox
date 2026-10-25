"""Tests for scripts/cfq_lib/flags.py -- the portal's deterministic flags and size baselines. Pure
functions over plain dict fixtures in the batch-payload shape, no filesystem.
"""

import sys
import unittest

from cfq_testlib import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import flags as F  # noqa: E402

ROOT = "/repo"


def cost(turns, output):
    return {"total": {"turns": turns, "input": 0, "output": output, "cache_read": 0, "cache_creation": 0},
            "byModel": {}, "layers": {}, "agents": []}


def attempt(status="green", *, turns=10, output=1000, has_cost=True, **extra):
    a = {
        "status": status, "deviations": [], "observations": [], "errors": [], "triggers": [],
        "question": "", "commit": "abc123", "reopened": "", "diffstat": None, "filesTouched": [],
        "parkedPlanEntries": [], "settled": True,
        "cost": cost(turns, output) if has_cost else None,
        "skills": {"recommended": [], "used": []},
    }
    a.update(extra)
    return a


def phase(slug="01-a", size="M", attempts=None, state="done", affected=(), **extra):
    p = {"slug": slug, "size": size, "state": state, "affectedFiles": list(affected),
         "attempts": [attempt()] if attempts is None else attempts, "flags": []}
    p.update(extra)
    return p


def batch(phases, name="001-b", **extra):
    b = {"name": name, "phases": phases, "closing": None, "planning": None, "flags": []}
    b.update(extra)
    return b


def codes(flag_list):
    return [(f["level"], f["code"]) for f in flag_list]


class SizePointsTest(unittest.TestCase):
    def test_point_sums_all_attempts_of_a_green_costed_phase(self):
        p = phase(attempts=[attempt("red", turns=4, output=400), attempt("green", turns=6, output=600)])
        pts = F.size_points([batch([p])])
        self.assertEqual(pts, [{"batch": "001-b", "phase": "01-a", "size": "M", "turns": 10, "output": 1000}])

    def test_no_cost_open_empty_size_or_non_green_make_no_point(self):
        phases = [
            phase("01-a", attempts=[attempt(has_cost=False)]),
            phase("02-b", state="open", attempts=[attempt()]),
            phase("03-c", size=""),
            phase("04-d", attempts=[attempt("red")]),
            phase("05-e", attempts=[]),
        ]
        self.assertEqual(F.size_points([batch(phases)]), [])

    def test_baselines_median_and_odd_even_counts(self):
        pts = [
            {"batch": "b", "phase": f"0{i}", "size": "S", "turns": t, "output": o}
            for i, (t, o) in enumerate([(2, 10), (4, 30), (9, 20)])
        ] + [
            {"batch": "b", "phase": f"1{i}", "size": "L", "turns": t, "output": 0} for i, t in enumerate([10, 20])
        ]
        self.assertEqual(F.baselines(pts), {
            "L": {"n": 2, "turnsMedian": 15, "outputMedian": 0},
            "S": {"n": 3, "turnsMedian": 4, "outputMedian": 20},
        })

    def test_baselines_only_for_sizes_with_points(self):
        self.assertEqual(F.baselines([]), {})


class PhaseFlagsTest(unittest.TestCase):
    def flags(self, p, base=None):
        return F.phase_flags(p, base or {}, ROOT)

    def test_plan_only_phase_has_no_flags(self):
        self.assertEqual(self.flags(phase(attempts=[], state="open")), [])

    def test_clean_green_phase_has_no_flags(self):
        self.assertEqual(self.flags(phase()), [])

    def test_red_attempt_counts_and_latest_red(self):
        earlier = self.flags(phase(attempts=[attempt("red"), attempt("green")]))
        self.assertEqual(codes(earlier), [("warn", "red-attempt")])
        self.assertEqual(earlier[0]["text"], "1 red attempt")
        self.assertEqual(earlier[0]["phase"], "01-a")
        latest = self.flags(phase(state="open", attempts=[attempt("red"), attempt("red")]))
        self.assertEqual(latest[0]["text"], "phase is red after 2 red attempts")

    def test_question(self):
        self.assertIn(("warn", "question"), codes(self.flags(phase(state="open", attempts=[attempt("question")]))))
        self.assertNotIn(("warn", "question"), codes(self.flags(phase())))

    def test_reopened(self):
        p = phase(attempts=[attempt(reopened="2026-09-01T10:00:00Z")])
        self.assertIn(("warn", "reopened"), codes(self.flags(p)))

    def test_no_commit_only_for_done_green(self):
        self.assertIn(("warn", "no-commit"), codes(self.flags(phase(attempts=[attempt(commit="")]))))
        self.assertNotIn(("warn", "no-commit"), codes(self.flags(phase(state="open", attempts=[attempt(commit="")]))))
        self.assertNotIn(("warn", "no-commit"), codes(self.flags(phase(attempts=[attempt("red", commit="")]))))

    def test_no_telemetry_only_when_done(self):
        self.assertIn(("warn", "no-telemetry"), codes(self.flags(phase(attempts=[attempt(has_cost=False)]))))
        self.assertNotIn(("warn", "no-telemetry"),
                         codes(self.flags(phase(state="open", attempts=[attempt(has_cost=False)]))))
        self.assertNotIn(("warn", "no-telemetry"), codes(self.flags(phase())))

    def test_undeclared_files(self):
        stat = {"files": 2, "insertions": 1, "deletions": 0,
                "paths": [{"path": "a/in.py", "added": 1, "deleted": 0}, {"path": "b/out.py", "added": 1, "deleted": 0}]}
        p = phase(affected=["/repo/a/in.py"], attempts=[attempt(diffstat=stat)])
        found = [f for f in self.flags(p) if f["code"] == "undeclared-files"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["level"], "warn")
        self.assertIn("b/out.py", found[0]["text"])
        self.assertNotIn("a/in.py", found[0]["text"])

    def test_undeclared_files_relative_affected_paths_resolve_too(self):
        stat = {"files": 1, "insertions": 1, "deletions": 0, "paths": [{"path": "a/in.py", "added": 1, "deleted": 0}]}
        p = phase(affected=["a/in.py"], attempts=[attempt(diffstat=stat)])
        self.assertNotIn("undeclared-files", [f["code"] for f in self.flags(p)])

    def test_undeclared_files_not_raised_with_deviation_or_without_diffstat(self):
        stat = {"files": 1, "insertions": 1, "deletions": 0, "paths": [{"path": "x.py", "added": 1, "deleted": 0}]}
        declared = phase(attempts=[attempt(diffstat=stat, deviations=["touched x.py"])])
        self.assertNotIn("undeclared-files", [f["code"] for f in self.flags(declared)])
        self.assertNotIn("undeclared-files", [f["code"] for f in self.flags(phase())])

    def test_undeclared_files_names_five_paths_and_a_count(self):
        paths = [{"path": f"f{i}.py", "added": 1, "deleted": 0} for i in range(8)]
        stat = {"files": 8, "insertions": 8, "deletions": 0, "paths": paths}
        text = next(f["text"] for f in self.flags(phase(attempts=[attempt(diffstat=stat)])) if f["code"] == "undeclared-files")
        self.assertIn("f4.py", text)
        self.assertNotIn("f5.py", text)
        self.assertTrue(text.endswith("+3 more"))

    def test_cost_outlier_needs_five_samples(self):
        p = phase(attempts=[attempt(turns=30, output=1000)])
        few = {"M": {"n": 4, "turnsMedian": 10, "outputMedian": 1000}}
        enough = {"M": {"n": 5, "turnsMedian": 10, "outputMedian": 1000}}
        self.assertNotIn("cost-outlier", [f["code"] for f in self.flags(p, few)])
        found = [f for f in self.flags(p, enough) if f["code"] == "cost-outlier"]
        self.assertEqual(len(found), 1)
        self.assertIn("turns 3.0x", found[0]["text"])
        self.assertNotIn("output", found[0]["text"])

    def test_cost_outlier_not_raised_at_or_under_the_factor(self):
        p = phase(attempts=[attempt(turns=20, output=2000)])
        base = {"M": {"n": 9, "turnsMedian": 10, "outputMedian": 1000}}
        self.assertNotIn("cost-outlier", [f["code"] for f in self.flags(p, base)])

    def test_cost_outlier_by_output(self):
        p = phase(attempts=[attempt(turns=5, output=5000)])
        base = {"M": {"n": 9, "turnsMedian": 10, "outputMedian": 1000}}
        text = next(f["text"] for f in self.flags(p, base) if f["code"] == "cost-outlier")
        self.assertIn("output 5.0x", text)

    def test_info_flags(self):
        p = phase(attempts=[attempt(
            observations=["a", "b"], parkedPlanEntries=["plan/x.md"], triggers=["omitted"],
            skills={"recommended": ["tdd", "ponytail"], "used": ["tdd"]}, settled=False,
        )])
        got = {f["code"]: f for f in self.flags(p)}
        self.assertEqual(sorted(got), ["observations", "parked-entries", "provisional", "skills-unused", "triggers"])
        self.assertTrue(all(f["level"] == "info" for f in got.values()))
        self.assertEqual(got["observations"]["text"], "2 observations")
        self.assertIn("ponytail", got["skills-unused"]["text"])
        self.assertNotIn("tdd", got["skills-unused"]["text"])

    def test_info_flags_negatives(self):
        p = phase(attempts=[attempt(skills={"recommended": ["tdd"], "used": ["tdd"]})])
        self.assertEqual(self.flags(p), [])

    def test_warn_sorts_before_info_then_code(self):
        p = phase(attempts=[attempt("red", observations=["x"]), attempt(observations=["y"], commit="")])
        self.assertEqual(codes(self.flags(p)), [("warn", "no-commit"), ("warn", "red-attempt"), ("info", "observations")])


class BatchFlagsTest(unittest.TestCase):
    def test_phase_flags_carry_their_slug_and_batch_flags_none(self):
        b = batch(
            [phase("02-b", attempts=[attempt(observations=["x"])]), phase("01-a", attempts=[attempt("red"), attempt()])],
            closing={"errors": ["boom"], "lang": {"issues": 2}, "security": {"new": {"high": 1}}},
            planning={"settled": False},
        )
        got = F.batch_flags(b, {}, ROOT)
        self.assertEqual([(f["phase"], f["level"], f["code"]) for f in got], [
            ("01-a", "warn", "red-attempt"),
            ("02-b", "info", "observations"),
            (None, "warn", "finish-errors"),
            (None, "warn", "lang-issues"),
            (None, "warn", "security-new"),
            (None, "info", "provisional"),
        ])

    def test_closing_flags_negatives(self):
        clean = {"errors": [], "lang": {"issues": 0}, "security": {"new": {}}}
        self.assertEqual(F.batch_flags(batch([], closing=clean), {}, ROOT), [])
        self.assertEqual(F.batch_flags(batch([], closing=None), {}, ROOT), [])
        odd = {"errors": [], "lang": {"issues": 0}, "security": {"new": {"counts": {}}}}
        self.assertEqual(F.batch_flags(batch([], closing=odd), {}, ROOT), [])

    def test_planning_settled_raises_nothing_and_merged_is_ignored(self):
        b = batch([], planning={"settled": True}, merged=False)
        self.assertEqual(F.batch_flags(b, {}, ROOT), [])

    def test_order_is_deterministic(self):
        b = batch([phase("02-b", attempts=[attempt("red")]), phase("01-a", attempts=[attempt("red")])])
        self.assertEqual(F.batch_flags(b, {}, ROOT), F.batch_flags(b, {}, ROOT))
        self.assertEqual([f["phase"] for f in F.batch_flags(b, {}, ROOT)], ["01-a", "02-b"])


if __name__ == "__main__":
    unittest.main()
