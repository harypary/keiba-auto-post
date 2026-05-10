"""IdentificationModal の中身を確認"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright
from src.publisher.note_publisher import SESSION_FILE

with open(SESSION_FILE, encoding="utf-8") as f:
    storage = json.load(f)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(storage_state=storage, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.goto("https://note.com", wait_until="networkidle", timeout=30000)
    time.sleep(3)
    # クリック
    a = page.locator('a[href*="/notes/new"]').first
    a.click(timeout=5000, force=True)
    time.sleep(8)

    # モーダルがあるか
    modal_overlay = page.query_selector(".ReactModalPortal")
    if modal_overlay:
        modal_html = modal_overlay.inner_html()
        print(f"=== Modal HTML (len={len(modal_html)}) ===")
        print(modal_html[:3000])
        # buttons in modal
        btns = page.locator(".ReactModal__Content button").all()
        print(f"\n=== Modal Buttons ({len(btns)}) ===")
        for b in btns:
            try:
                t = (b.text_content() or "").strip()
                print(f"  - {t[:50]}")
            except Exception:
                pass
        # screenshot
        page.screenshot(path="data/debug_publish/modal_capture.png", full_page=True)
        print(f"\nスクショ: data/debug_publish/modal_capture.png")
    else:
        print("Modal not found")
    print(f"\nURL: {page.url}")
    browser.close()
