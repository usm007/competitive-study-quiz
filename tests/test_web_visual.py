"""Visual/UX regression tests for the redesigned study workspace.

Static checks on templates/web/app.template.html + generated output:
tokens, typography, layout, modes, drawers, feedback, analytics,
keyboard, a11y, responsive breakpoints, print, offline.
Runnable via unittest discover; stdlib only.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable
TPL = ROOT / "templates" / "web" / "app.template.html"


def run(*args):
    p = subprocess.run([PY] + [str(a) for a in args], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=300)
    return p


def tpl_text():
    return TPL.read_text(encoding="utf-8")


class TestDesignTokens(unittest.TestCase):
    def test_token_system_present(self):
        t = tpl_text()
        for tok in ["--bg", "--surface", "--ink", "--muted", "--line",
                    "--accent", "--good", "--bad", "--warn", "--focus",
                    "--radius", "--font-ui"]:
            self.assertIn(tok, t, tok)

    def test_no_georgia_everywhere(self):
        t = tpl_text()
        m = re.search(r"body\s*\{[^}]*font-family:([^;}]+)", t)
        self.assertIsNotNone(m, "body font-family missing")
        self.assertNotIn("Georgia", m.group(1),
                         "body must not be Georgia-everywhere")

    def test_no_heavy_legacy_markers(self):
        t = tpl_text()
        self.assertNotIn("Georgia,\"Nirmala UI\"", t)
        # no giant flat blue button pattern: primary button is restrained
        self.assertIn(".btn-primary", t)


class TestShellLayout(unittest.TestCase):
    def test_topbar_rail_workspace(self):
        t = tpl_text()
        self.assertIn('class="topbar"', t)
        self.assertIn('id="modebar"', t)
        self.assertIn('class="workspace"', t)
        self.assertIn('id="railToggle"', t)

    def test_no_permanent_sidebar_hog(self):
        t = tpl_text()
        # secondary utility lives in drawers, not a permanent wide sidebar
        for did in ["navDrawer", "filterDrawer", "sourceDrawer", "sessionDrawer"]:
            self.assertIn('id="%s"' % did, t)
        self.assertIn('class="scrim"', t)


class TestModes(unittest.TestCase):
    MODES = ["learn", "practice", "test", "revision", "rapid"]

    def test_all_modes_present_with_descriptions(self):
        t = tpl_text()
        for m in self.MODES:
            self.assertIn('data-mode="%s"' % m, t)
        self.assertIn("Weak areas", t)
        self.assertIn("High-density", t)

    def test_active_mode_unmistakable(self):
        t = tpl_text()
        self.assertIn(".mode-item.active", t)

    def test_test_mode_exam_chrome(self):
        t = tpl_text()
        self.assertIn('id="timerrow"', t)
        self.assertIn('id="finishtest"', t)
        self.assertIn("confirm(", t)
        self.assertIn("No feedback until you submit", t)


class TestQuestionUX(unittest.TestCase):
    def test_question_hierarchy(self):
        t = tpl_text()
        self.assertIn('id="qmeta"', t)
        self.assertIn('id="qstem"', t)
        self.assertIn("Question ", t)
        # tech ids live in a collapsed details element, not the main line
        self.assertIn("<details", t)

    def test_option_states(self):
        t = tpl_text()
        for cls in [".opt.selected", ".opt.correct", ".opt.incorrect",
                    ".opt .verdict"]:
            self.assertIn(cls, t)
        # not color alone: textual verdicts exist
        self.assertIn("Correct", t)
        self.assertIn("Yours", t)

    def test_statement_styling(self):
        t = tpl_text()
        self.assertIn("stmt-list", t)
        self.assertIn("stmt-n", t)
        self.assertIn("Consider the following statements", t)

    def test_match_styling(self):
        t = tpl_text()
        self.assertIn("match-cols", t)
        self.assertIn("Match the following", t)
        self.assertIn("parseMatchLists", t)

    def test_feedback_teaches(self):
        t = tpl_text()
        for s in ["Key distinction", "Why the distractor tempts you",
                  "Common mix-up", "Remember", "Your answer",
                  "Correct answer"]:
            self.assertIn(s, t, s)


class TestProgressNav(unittest.TestCase):
    def test_progress_system(self):
        t = tpl_text()
        self.assertIn('id="progressNum"', t)
        self.assertIn('id="progressFill"', t)
        self.assertIn('id="progressPct"', t)

    def test_navigator_states_and_filters(self):
        t = tpl_text()
        for cls in ["is-right", "is-wrong", "is-marked", "is-hipri",
                    "is-revneed", "cur"]:
            self.assertIn(cls, t)
        for nf in ['data-nf="all"', 'data-nf="unanswered"',
                   'data-nf="incorrect"', 'data-nf="marked"']:
            self.assertIn(nf, t)


class TestAnalyticsActionable(unittest.TestCase):
    def test_analytics_answers_three_questions(self):
        t = tpl_text()
        self.assertIn("What should I study next?", t)
        self.assertIn("Weak areas", t)
        self.assertIn("Confidence problem", t)
        self.assertIn("Revision priority", t)

    def test_analytics_actions(self):
        t = tpl_text()
        for a in ["Revise now", "Practise distinctions", "Review mistakes",
                  "data-act"]:
            self.assertIn(a, t)

    def test_no_raw_table_analytics(self):
        t = tpl_text()
        self.assertIn("bar-row", t)


class TestFiltersSource(unittest.TestCase):
    def test_filter_chips(self):
        t = tpl_text()
        self.assertIn('id="chips"', t)
        self.assertIn('id="clearFilters"', t)
        for fid in ["f_topic", "f_diff", "f_tier", "f_type", "f_purpose",
                    "f_rev", "f_incorrect", "f_marked", "f_weak"]:
            self.assertIn('id="%s"' % fid, t)

    def test_source_drawer(self):
        t = tpl_text()
        self.assertIn('id="sourceBody"', t)
        self.assertIn("never fabricated", t.lower())


class TestKeyboardA11y(unittest.TestCase):
    def test_shortcuts(self):
        t = tpl_text()
        for k in ['"m"', '"h"', '"n"', '"Enter"', '"ArrowRight"',
                  '"ArrowLeft"', '"Escape"']:
            self.assertIn(k, t, k)

    def test_a11y_markers(self):
        t = tpl_text()
        self.assertIn("skip", t)
        self.assertIn("aria-label", t)
        self.assertIn("aria-live", t)
        self.assertIn(":focus-visible", t)
        self.assertIn("radiogroup", t)
        self.assertIn("prefers-reduced-motion", t)


class TestResponsivePrint(unittest.TestCase):
    def test_breakpoints(self):
        t = tpl_text()
        for bp in ["430px", "860px"]:
            self.assertIn(bp, t, bp)
        self.assertIn("mobilebar", t)

    def test_touch_targets(self):
        t = tpl_text()
        self.assertIn("min-height:56px", t)

    def test_print_stylesheet(self):
        t = tpl_text()
        self.assertIn("@media print", t)
        self.assertIn("break-inside:avoid", t)


class TestOfflineBuild(unittest.TestCase):
    def test_placeholders_and_offline(self):
        t = tpl_text()
        self.assertIn("/*__PACKAGE__*/{}", t)
        self.assertIn('/*__STATUS__*/""', t)
        ext = [u for u in re.findall(r"https?://[^\s\"'<>]+", t)
               if "w3.org" not in u]
        self.assertEqual(ext, [], ext)

    def test_generated_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp, "quiz.html"))
            r = run("scripts/build_web.py", "examples/sample_package.json",
                    "--out", out, "--title", "T")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = Path(out).read_text(encoding="utf-8")
            i = html.find("__PACKAGE__")
            self.assertNotEqual(i, -1)
            j = html.find("{", i)
            depth, k = 0, j
            while k < len(html):
                if html[k] == "{":
                    depth += 1
                elif html[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            pkg = json.loads(html[j:k + 1])
            self.assertEqual(len(pkg["questions"]), 64)
            for needle in ["modebar", "navDrawer", "filterDrawer",
                           "sourceDrawer", "study-note", "bar-row",
                           "Consider the following statements"]:
                self.assertIn(needle, html, needle)

    def test_functionality_preserved(self):
        t = tpl_text()
        for eid in ["opts", "submitbtn", "markbtn", "prevbtn", "nextbtn",
                    "confrow", "feedback", "hintbtn", "navgrid",
                    "exportbtn", "importbtn", "importfile", "storagenote",
                    "analyticsBtn", "quizBtn", "srcmode", "printlink"]:
            self.assertIn('id="%s"' % eid, t, eid)
        self.assertIn("quiz_session_v2_", t)
        self.assertIn("study_session.json", t)


class TestRevisionUI(unittest.TestCase):
    def test_engine_placeholder_and_build_inlining(self):
        t = tpl_text()
        self.assertIn("/*__REVISION_ENGINE__*/", t)
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp, "quiz.html"))
            r = run("scripts/build_web.py", "examples/sample_package.json",
                    "--out", out, "--title", "T")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            html = Path(out).read_text(encoding="utf-8")
            self.assertIn("RevisionEngine", html)
            self.assertNotIn("__REVISION_ENGINE__", html)

    def test_revision_modes_and_why(self):
        t = tpl_text()
        for mode in ["targeted", "mistakes", "confusion", "hce",
                     "cognitive", "quick", "full"]:
            self.assertIn('"%s"' % mode, t, mode)
        self.assertIn("Why you are seeing this", t)
        self.assertIn("Why this question", t)
        self.assertIn("revQueue", t)

    def test_session_v2_and_migration(self):
        t = tpl_text()
        self.assertIn("study_session_version", t)
        self.assertIn("migrateSession", t)
        self.assertIn("revision_state", t)
        for field in ["dt_ms", "secondary_kus", "rev_priority"]:
            self.assertIn(field, t, field)

    def test_analytics_revision_section(self):
        t = tpl_text()
        self.assertIn("rev-hce", t)
        self.assertIn("rev-cog", t)
        self.assertIn("High-confidence errors", t)

    def test_neutral_language(self):
        t = tpl_text().lower()
        for phrase in ["you keep failing", "bad performance",
                       "you don't understand", "you do not understand"]:
            self.assertNotIn(phrase, t, phrase)


if __name__ == "__main__":
    unittest.main(verbosity=2)
