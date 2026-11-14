"""Checks for scripts/council-report.py. Run: python3 -m unittest discover -s tests (from the skill dir)."""
import contextlib
import copy
import importlib.util
import io
import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "council-report.py"
spec = importlib.util.spec_from_file_location("council_report", SCRIPT)
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

REVIEW = {
    "kind": "review",
    "title": "Discount branch",
    "summary": "Two problems to fix before merging.",
    "round": 1,
    "reviewers": [
        {"id": "claude", "label": "Claude", "status": "ok"},
        {"id": "codex", "label": "Codex", "status": "ok"},
        {"id": "agy", "label": "agy", "status": "timeout"},
    ],
    "findings": [
        {"id": "F1", "severity": "low", "title": "Unused import", "verdict": "false_positive",
         "raised_by": ["codex"]},
        {"id": "F2", "severity": "high", "title": "Token compared with ==", "verdict": "confirmed",
         "location": "shop/auth.py:42", "raised_by": ["claude", "codex"]},
    ],
    "decisions": [{"id": "D1", "question": "Is 3x write volume realistic?"}],
}

CONSULT = {
    "kind": "consultation",
    "title": "Cache choice",
    "summary": "Use the in-process cache with a short TTL.",
    "recommendation": "Option A.",
    "reviewers": [{"id": "claude", "status": "ok"}, {"id": "codex", "status": "ok"},
                  {"id": "agy", "status": "failed"}],
    "options": [
        {"id": "A", "title": "In-process LRU", "detail": "Per-process cache.",
         "positions": {"claude": {"stance": "recommended", "note": "Simple."}, "codex": "acceptable"}},
    ],
}


def problems(report):
    """The validator's error lines for `report` ([] when it is accepted)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            cr.validate(report)
        except SystemExit as e:
            assert e.code == 2, e.code
            return err.getvalue().splitlines()[1:]
    return []


def page(report, raw=()):
    cr.validate(report)
    return cr.render(report, cr.LABELS["en"], list(raw), "en")


def changed(base, **fields):
    r = copy.deepcopy(base)
    r.update(fields)
    return r


class Validate(unittest.TestCase):
    def test_examples_are_valid(self):
        self.assertEqual(problems(REVIEW), [])
        self.assertEqual(problems(CONSULT), [])

    def test_wrong_shapes_are_reported_not_raised(self):
        for fields in (
            {"findings": ["oops"]},
            {"findings": {"id": "F1"}},
            {"reviewers": ["claude", "codex"]},
            {"round": "two"},
            {"round": 0},
            {"title": None},
            {"summary": 3},
            {"decisions": [{"id": ["D1"], "question": "q"}]},
            {"history": [{"round": 1, "feedback": None, "response": "r"}]},
        ):
            with self.subTest(fields=fields):
                self.assertTrue(problems(changed(REVIEW, **fields)))

    def test_raised_by_must_be_a_list_of_known_reviewers(self):
        f = dict(REVIEW["findings"][0])
        self.assertTrue(problems(changed(REVIEW, findings=[dict(f, raised_by="codex")])))
        self.assertTrue(problems(changed(REVIEW, findings=[dict(f, raised_by=["gemini"])])))

    def test_status_is_required(self):
        errs = problems(changed(REVIEW, reviewers=[{"id": "claude"}]))
        self.assertTrue(any("status" in e for e in errs), errs)

    def test_duplicate_ids(self):
        twice = [REVIEW["findings"][0], REVIEW["findings"][0]]
        self.assertTrue(any("duplicate" in e for e in problems(changed(REVIEW, findings=twice))))
        same = [{"id": "x", "status": "ok"}, {"id": "x", "status": "ok"}]
        self.assertTrue(any("duplicate" in e for e in problems(changed(REVIEW, reviewers=same))))

    def test_consultation_needs_recommendation_and_every_answer(self):
        self.assertTrue(problems(changed(CONSULT, recommendation="")))
        self.assertTrue(problems(changed(CONSULT, options=[])))
        opt = copy.deepcopy(CONSULT["options"][0])
        del opt["positions"]["codex"]
        errs = problems(changed(CONSULT, options=[opt]))
        self.assertTrue(any("codex" in e for e in errs), errs)
        opt = dict(CONSULT["options"][0], detail="")
        self.assertTrue(problems(changed(CONSULT, options=[opt])))


class Rich(unittest.TestCase):
    def test_code_and_bold(self):
        self.assertEqual(cr.rich("use `a` and **b**"), "<p>use <code>a</code> and <strong>b</strong></p>")

    def test_stars_inside_code_stay_literal(self):
        self.assertEqual(cr.rich("Compare `a ** b` with `c ** d`"),
                         "<p>Compare <code>a ** b</code> with <code>c ** d</code></p>")

    def test_markup_is_escaped(self):
        self.assertNotIn("<img", cr.rich("`<img src=x>` <img src=y>"))


class Render(unittest.TestCase):
    def test_placeholder_text_in_content_is_not_substituted(self):
        r = changed(REVIEW, title="T <img src=x onerror=alert(1)>", summary="see @@DATA@@ and @@BODY@@")
        html = page(r, raw=[("codex.md", "the template uses @@DATA@@ and @@TITLE@@")])
        self.assertNotIn("<img", html)
        self.assertIn("see @@DATA@@ and @@BODY@@", html)
        self.assertIn("the template uses @@DATA@@ and @@TITLE@@", html)

    def test_embedded_json_cannot_touch_the_script_element(self):
        html = page(changed(REVIEW, title="x <!--<script> </script> & y"))
        data = re.search(r'<script id="council-data" type="application/json">(.*?)</script>', html, re.S).group(1)
        self.assertFalse(set("<>&") & set(data), data)

    def test_findings_are_listed_most_severe_first(self):
        html = page(REVIEW)
        self.assertLess(html.index('id="F2"'), html.index('id="F1"'))

    def test_items_that_need_attention_start_open(self):
        html = page(changed(REVIEW, round=2, findings=[
            dict(REVIEW["findings"][0], updated_round=2), REVIEW["findings"][1],
            {"id": "F3", "severity": "low", "title": "t", "verdict": "confirmed"},
        ]))
        self.assertIn('id="F1" open', html)      # changed this round
        self.assertIn('id="F2" open', html)      # high severity
        self.assertNotIn('id="F3" open', html)

    def test_every_item_gets_a_comment_box(self):
        html = page(REVIEW) + page(CONSULT)
        for item in ("F1", "F2", "D1", "A", "overall"):
            self.assertIn(f'data-id="{item}"', html)

    def test_reviewer_status_is_shown(self):
        self.assertIn("timed out", page(REVIEW))


if __name__ == "__main__":
    unittest.main()
