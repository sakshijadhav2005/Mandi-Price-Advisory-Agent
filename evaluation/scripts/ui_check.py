"""Phone-width UI check and demo recording (plan: "test at 360px", "2-minute demo").

Drives the real web app in Chrome at 360x740 (a common low-end Android size),
walks every screen in Marathi and English, saves screenshots, and checks each
screen for horizontal scrolling and too-small tap targets. With --video it
records the same walkthrough, slowed down, as a demo video.

Needs the backend on :8000 and the web dev server on :5173, and
`pip install playwright` (uses the installed Chrome, no browser download).

    python evaluation/scripts/ui_check.py [--video] [--browser chrome|msedge]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
DEMO = ROOT / "docs" / "demo"
WEB = os.environ.get("UI_CHECK_WEB", "http://localhost:5173")
VIEWPORT = {"width": 360, "height": 740}
MIN_TAP_PX = 40

CHECK_JS = """
(min) => {
  const doc = document.documentElement;
  const overflow = doc.scrollWidth - doc.clientWidth;
  const small = [];
  for (const el of document.querySelectorAll('button, a, select, input, textarea, [role=tab]')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;  // hidden
    if (el.type === 'checkbox') continue;            // wrapped in a 48px label
    if (r.height < min && r.width < 2 * min) small.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40) + ` (${Math.round(r.width)}x${Math.round(r.height)})`);
  }
  return { overflow, small };
}
"""


class Walk:
    def __init__(self, page: Page, pause_ms: int):
        self.page = page
        self.pause_ms = pause_ms
        self.results: list[dict] = []

    def pause(self, factor: float = 1.0) -> None:
        if self.pause_ms:
            self.page.wait_for_timeout(int(self.pause_ms * factor))

    def check(self, name: str) -> None:
        self.page.wait_for_timeout(300)
        res = self.page.evaluate(CHECK_JS, MIN_TAP_PX)
        self.page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
        self.results.append({"screen": name, **res})
        self.pause()

    def type_slowly(self, selector: str, text: str) -> None:
        box = self.page.locator(selector)
        if self.pause_ms:
            box.press_sequentially(text, delay=60)
        else:
            box.fill(text)

    def ask(self, question: str) -> None:
        self.type_slowly("#question", question)
        self.pause(0.5)
        self.page.locator("form button[type=submit]").click()
        self.page.locator("article").last.wait_for(timeout=60_000)
        self.page.wait_for_timeout(500)
        self.page.locator("article").last.scroll_into_view_if_needed()


def run(walk: Walk) -> None:
    p = walk.page
    p.goto(WEB)
    p.evaluate("localStorage.clear()")
    p.reload()
    p.get_by_role("button", name="मराठी").wait_for()
    walk.check("01-language-picker")

    p.get_by_role("button", name="मराठी").click()
    p.locator("#question").wait_for()
    walk.check("02-mr-ask-empty")

    walk.ask("माझ्याकडे 20 क्विंटल कांदा आहे, आता विकू की थांबू?")
    walk.check("03-mr-sell-hold-answer")
    p.get_by_role("button", name="स्रोत आणि तपशील पाहा").last.click()
    walk.check("04-mr-sources-open")

    walk.ask("कांदा साठवण कशी करावी?")
    walk.check("05-mr-storage-answer")

    p.get_by_role("link", name="दर").click()
    p.locator("li.card").first.wait_for()
    walk.check("06-mr-prices")

    p.get_by_role("link", name="इतिहास").click()
    p.wait_for_timeout(800)
    walk.check("07-mr-history")

    p.get_by_role("link", name="सेटिंग").click()
    walk.check("08-mr-settings")

    # Switch to English and Pune district, then ask about potato.
    p.get_by_role("button", name="English").click()
    p.get_by_role("button", name="Pune").click()
    walk.pause()
    p.get_by_role("link", name="Ask").click()  # the Ask page starts a fresh conversation
    walk.ask("I have potatoes in cold storage. Hold or sell?")
    walk.check("09-en-pune-potato-answer")

    p.get_by_role("link", name="Prices").click()
    p.get_by_role("tab", name="Potato").click()
    p.locator("li.card").first.wait_for()
    walk.check("10-en-pune-potato-prices")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="store_true", help="record a slowed-down demo video to docs/demo/")
    ap.add_argument("--browser", default="chrome", choices=["chrome", "msedge"])
    args = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    tmp_video = ROOT / "docs" / "demo" / "_raw"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.browser)
        ctx_args = {"viewport": VIEWPORT, "device_scale_factor": 2, "is_mobile": True, "has_touch": True, "locale": "mr-IN"}
        if args.video:
            ctx_args["record_video_dir"] = str(tmp_video)
            ctx_args["record_video_size"] = {"width": 720, "height": 1480}
        ctx = browser.new_context(**ctx_args)
        page = ctx.new_page()
        walk = Walk(page, pause_ms=1800 if args.video else 0)
        run(walk)
        video_path = page.video.path() if args.video else None
        ctx.close()
        browser.close()
    if video_path:
        DEMO.mkdir(parents=True, exist_ok=True)
        final = DEMO / "mandi-advisor-demo.webm"
        shutil.move(video_path, final)
        shutil.rmtree(tmp_video, ignore_errors=True)
        print(f"demo video: {final}")

    problems = [r for r in walk.results if r["overflow"] > 0 or r["small"]]
    (ROOT / "evaluation" / "reports" / "ui_check.json").write_text(json.dumps(walk.results, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for r in walk.results:
        status = "OK " if r not in problems else "FIX"
        print(f"{status} {r['screen']}: horizontal overflow {r['overflow']}px; small tap targets: {r['small'] or 'none'}")
    print(f"screenshots: {SHOTS}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
