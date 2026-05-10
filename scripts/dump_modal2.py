"""出版直前のモーダル内容を確認"""
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
    page.on("dialog", lambda d: d.accept())

    page.goto("https://note.com", wait_until="networkidle")
    time.sleep(2)
    page.locator('a[href*="/notes/new"]').first.click(timeout=5000, force=True)
    time.sleep(8)

    # title
    page.fill('input[placeholder*="タイトル"]', "テスト")
    time.sleep(1)

    # body
    body = page.query_selector(".ProseMirror") or page.query_selector("[contenteditable='true']")
    if body:
        body.click()
        page.evaluate('navigator.clipboard.writeText("テスト本文。")')
        page.keyboard.press("Control+v")
        time.sleep(2)

    # 公開に進む クリック
    print("[click] 公開に進む")
    try:
        page.click('button:has-text("公開に進む")', timeout=8000, force=True)
        time.sleep(5)
        print(f"  url: {page.url}")
    except Exception as e:
        print(f"  failed: {e}")

    # IdentificationModal の中身
    modal = page.query_selector(".ReactModalPortal .ReactModal__Content, .IdentificationModal__overlay")
    if modal:
        text = modal.text_content() or ""
        print(f"\n=== Modal Text ===\n{text[:2000]}")
        # buttons
        btns = page.locator(".ReactModal__Content button, .IdentificationModal__overlay button").all()
        print(f"\nButtons in modal:")
        for b in btns:
            t = (b.text_content() or "").strip()
            if t:
                print(f"  - {t[:60]}")
        page.screenshot(path="data/debug_publish/modal_publish.png", full_page=True)
    else:
        print("Modal not found")
    browser.close()
