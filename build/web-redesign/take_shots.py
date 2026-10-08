"""Capture redesign screenshots at desktop/tablet/mobile widths."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "build" / "web-redesign" / "quiz.html").resolve()
OUT = ROOT / "build" / "web-redesign" / "shots"
OUT.mkdir(parents=True, exist_ok=True)
URL = HTML.as_uri()

STMT_ID = "Q-0003"  # statement-based question in sample package


def answer(page, key="A", conf=None):
    page.locator("#opts .opt input[value='%s']" % key).check(force=True)
    if conf:
        page.locator("#confRow input[value='%s']" % conf).check(force=True)


def do_submit(page):
    if page.is_visible("#submitbtn"):
        page.click("#submitbtn")
    else:
        page.click("#mSubmit")


def do_next(page):
    if page.is_visible("#nextbtn"):
        page.click("#nextbtn")
    else:
        page.click("#mNext")


def shot(page, name):
    page.wait_for_timeout(350)
    page.screenshot(path=str(OUT / name), full_page=False)
    print("shot", name)


def run_width(width, tag, height=900):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": width, "height": height})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL)
        pg.wait_for_selector("#opts .opt")
        # 1 practice unanswered
        shot(pg, "%s-01-practice-unanswered.png" % tag)
        # 3 incorrect (answer wrong on Q-0001, key is A)
        answer(pg, "B", "Certain")
        do_submit(pg)
        pg.wait_for_selector("#feedback.sn-badge, .sn-badge")
        shot(pg, "%s-03-practice-incorrect.png" % tag)
        # 2 correct: next question, answer correctly
        do_next(pg)
        pg.wait_for_timeout(200)
        # find correct key from page
        key = pg.evaluate("() => { var q=QUESTIONS[view[state.idx]]; var o=normOptions(q); return normKey(q,o); }")
        answer(pg, key, "Fairly confident")
        do_submit(pg)
        pg.wait_for_selector(".sn-badge")
        shot(pg, "%s-02-practice-correct.png" % tag)
        # 4 statement question
        pg.evaluate("() => { var k=view.indexOf(QUESTIONS.findIndex(q=>q.id==='%s')); state.idx=(function(){ for(var i=0;i<view.length;i++){ if(QUESTIONS[view[i]].id==='%s') return i; } return 0; })(); render(); }" % (STMT_ID, STMT_ID))
        pg.wait_for_timeout(200)
        shot(pg, "%s-04-statement.png" % tag)
        # 5 learn mode
        pg.evaluate("() => setMode('learn')")
        pg.wait_for_timeout(200)
        shot(pg, "%s-05-learn.png" % tag)
        # 6 test mode
        pg.evaluate("() => setMode('test')")
        pg.wait_for_timeout(200)
        shot(pg, "%s-06-test.png" % tag)
        # 7 revision mode (queue)
        pg.evaluate("() => setMode('revision')")
        pg.wait_for_timeout(200)
        shot(pg, "%s-07-revision.png" % tag)
        # 8 rapid
        pg.evaluate("() => setMode('rapid')")
        pg.wait_for_timeout(200)
        shot(pg, "%s-08-rapid.png" % tag)
        # 9 analytics
        pg.evaluate("() => showAnalytics()")
        pg.wait_for_timeout(300)
        shot(pg, "%s-09-analytics.png" % tag)
        # back to practice for drawers
        pg.evaluate("() => { document.getElementById('quizBtn').click(); }")
        pg.wait_for_timeout(200)
        # 10 navigator open
        pg.click("#navToggle")
        pg.wait_for_timeout(300)
        shot(pg, "%s-10-navigator.png" % tag)
        pg.keyboard.press("Escape")
        # 11 filter drawer
        pg.click("#filterToggle")
        pg.wait_for_timeout(300)
        shot(pg, "%s-11-filters.png" % tag)
        pg.keyboard.press("Escape")
        # 12 source drawer (needs answered q or any q)
        pg.evaluate("() => openDrawer('sourceDrawer')")
        pg.wait_for_timeout(300)
        shot(pg, "%s-12-source.png" % tag)
        pg.keyboard.press("Escape")
        if errs:
            print("PAGEERRORS:", errs[:5])
        b.close()


run_width(1440, "d1440")
run_width(1280, "d1280", 900)
run_width(768, "tablet", 1024)
run_width(390, "m390", 844)
print("done", sorted(p.name for p in OUT.glob("*.png")))
