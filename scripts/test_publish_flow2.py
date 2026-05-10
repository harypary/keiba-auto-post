"""editor.note.com 起動失敗を解析する"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.sync_api import sync_playwright
from src.publisher.note_publisher import SESSION_FILE

DEBUG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "debug_publish")
os.makedirs(DEBUG_DIR, exist_ok=True)

with open(SESSION_FILE, encoding="utf-8") as f:
    storage = json.load(f)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        storage_state=storage,
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = ctx.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # Network log
    requests_log = []
    page.on("request", lambda req: requests_log.append({"url": req.url[:120], "method": req.method}))
    page.on("response", lambda res: None)

    # 1. note.com 確認
    print("[1] /me 確認")
    page.goto("https://note.com", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    # ログイン状態確認
    user_icon = page.query_selector('[data-testid="user-icon"], .o-header__userIcon, a[href*="/settings"]')
    print(f"  user_icon: {bool(user_icon)}")

    # 2. /notes/new に直リンク（noteで「新規」ボタンを押す代わりに）
    print("\n[2] noteの「投稿する」ボタン経由でエディタ起動")
    requests_log.clear()
    # Look for 投稿する link/button on the homepage
    for sel in ['a[href*="/notes/new"]', 'a[href="/notes/new"]', 'button:has-text("投稿")', 'a:has-text("投稿")']:
        els = page.locator(sel).all()
        if els:
            print(f"  found: {sel} count={len(els)}")
            try:
                els[0].click(timeout=5000)
                time.sleep(5)
                print(f"  clicked, current URL: {page.url}")
                break
            except Exception as e:
                print(f"  click failed: {e}")

    time.sleep(8)
    print(f"\n[3] 最終URL: {page.url}")
    print(f"  body size: {len(page.content())}")

    # Save final state
    page.screenshot(path=f"{DEBUG_DIR}/click_flow.png", full_page=True)
    with open(f"{DEBUG_DIR}/click_flow.html", "w", encoding="utf-8") as f:
        f.write(page.content())

    # Show editor.note.com requests
    editor_reqs = [r for r in requests_log if "editor.note.com" in r["url"] or "note.com/api" in r["url"]]
    print(f"\n[network] editor/api requests:")
    for r in editor_reqs[:30]:
        print(f"  {r['method']} {r['url']}")

    browser.close()
