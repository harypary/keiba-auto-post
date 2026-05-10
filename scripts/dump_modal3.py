"""IdentificationModal の実際のテキストを取得"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright
from src.publisher.note_publisher import SESSION_FILE

with open(SESSION_FILE, encoding="utf-8") as f:
    storage = json.load(f)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(storage_state=storage, viewport={"width": 1280, "height": 900},
                              permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()

    page.goto("https://note.com", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    # クリック前のモーダル
    print("=== Step 1: top page modal ===")
    for cls in [".ReactModalPortal", ".IdentificationModal__overlay", ".ReactModal__Content"]:
        el = page.query_selector(cls)
        if el:
            t = (el.text_content() or "").strip()[:1000]
            print(f"{cls}: {t}")
    # 投稿リンクをクリック
    page.locator('a[href*="/notes/new"]').first.click(timeout=5000, force=True)
    time.sleep(8)
    print(f"\n=== Step 2: after click, url={page.url} ===")
    for cls in [".ReactModalPortal", ".IdentificationModal__overlay", ".ReactModal__Content"]:
        el = page.query_selector(cls)
        if el:
            t = (el.text_content() or "").strip()[:1500]
            print(f"--- {cls} ---")
            print(t)
            # buttons
            btns = page.locator(f"{cls} button").all()
            print(f"buttons: {[(b.text_content() or '').strip()[:40] for b in btns]}")
    page.screenshot(path="data/debug_publish/modal3.png", full_page=True)
    browser.close()
