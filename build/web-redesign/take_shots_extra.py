"""Supplementary fit captures: fresh-learn (unanswered), 1280x720 key states."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "build" / "web-redesign" / "quiz.html").resolve()
OUT = ROOT / "build" / "web-redesign" / "shots"
URL = HTML.as_uri()


def shot(page, name):
    page.wait_for_timeout(350)
    page.screenshot(path=str(OUT / name), full_page=False)
    fit = page.evaluate("() => ({doc: document.documentElement.scrollHeight, win: window.innerHeight})")
    mark = "FIT" if fit["doc"] <= fit["win"] + 1 else "OVERFLOW(+%dpx)" % (fit["doc"] - fit["win"])
    print("shot %-32s %s" % (name, mark))


with sync_playwright() as p:
    b = p.chromium.launch()
    # fresh learn on an unanswered question (Q index 5 never touched)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL)
    pg.wait_for_selector("#opts .opt")
    pg.evaluate("() => { setMode('learn'); state.idx=5; render(); }")
    pg.wait_for_timeout(300)
    shot(pg, "d1440-05b-learn-fresh.png")
    # match-the-following list rendering (Q-0014)
    pg.evaluate("() => { setMode('practice'); for (var i=0;i<QUESTIONS.length;i++){ var qq=QUESTIONS[i]; if(qq.type==='match_pairs'){ state.idx=view.indexOf(i); break; } } render(); }")
    pg.wait_for_timeout(300)
    shot(pg, "d1440-04b-match.png")
    pg.close()
    # 1280x720 acceptance: practice unanswered/answered, statement, test
    pg = b.new_page(viewport={"width": 1280, "height": 720})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL)
    pg.wait_for_selector("#opts .opt")
    shot(pg, "d720-01-practice-unanswered.png")
    pg.locator("#opts .opt input[value='B']").check(force=True)
    pg.click("#submitbtn")
    pg.wait_for_selector(".sn-badge")
    shot(pg, "d720-02-practice-incorrect.png")
    pg.evaluate("() => { setMode('test'); }")
    pg.wait_for_timeout(300)
    shot(pg, "d720-03-test.png")
    pg.close()
    # 1280x800 acceptance: practice answered + statement
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL)
    pg.wait_for_selector("#opts .opt")
    pg.locator("#opts .opt input[value='B']").check(force=True)
    pg.click("#submitbtn")
    pg.wait_for_selector(".sn-badge")
    shot(pg, "d800-01-practice-incorrect.png")
    pg.evaluate("() => { for (var i=0;i<QUESTIONS.length;i++){ if(QUESTIONS[i].statements&&QUESTIONS[i].statements.length){ state.idx=view.indexOf(i); break; } } render(); }")
    pg.wait_for_timeout(300)
    shot(pg, "d800-02-statement.png")
    if errs:
        print("PAGEERRORS:", errs[:5])
    b.close()
print("done")
