"""指定IDの下書きを実際に公開する"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

if len(sys.argv) < 2:
    print("Usage: python publish_one_draft.py <note_id>")
    sys.exit(1)

note_id = sys.argv[1]
state = json.load(open("data/note_session.json", encoding="utf-8"))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(storage_state=state, viewport={"width":1280,"height":900})
    page = ctx.new_page()

    def on_dialog(d):
        try:
            print(f"dialog: {d.message[:80]}")
            d.accept()
        except Exception:
            pass
    page.on("dialog", on_dialog)

    page.goto(f"https://editor.note.com/notes/{note_id}/publish/", wait_until="networkidle", timeout=30000)
    time.sleep(5)

    try:
        page.click('button:has-text("有料エリア設定")', timeout=5000, force=True)
        time.sleep(5)
    except Exception as e:
        print(f"有料エリア設定 fail: {e}")

    # Click 投稿する
    clicked = False
    for attempt in range(6):
        time.sleep(2)
        for b in page.locator('button:has-text("投稿する")').all():
            try:
                if b.is_visible() and (b.text_content() or "").strip() == "投稿する":
                    b.scroll_into_view_if_needed(timeout=2000)
                    b.click(timeout=4000, force=True)
                    clicked = True
                    print(f"clicked 投稿する (attempt {attempt+1})")
                    break
            except Exception:
                continue
        if clicked:
            break

    # 確認モーダル「投稿する」「公開する」を待ってクリック
    time.sleep(3)
    for attempt in range(8):
        time.sleep(2)
        confirm_clicked = False
        for txt in ["投稿する", "OK", "公開する", "はい"]:
            try:
                for b in page.locator(f'button:has-text(\"{txt}\")').all():
                    try:
                        if b.is_visible() and (b.text_content() or '').strip() == txt:
                            b.click(timeout=3000, force=True)
                            confirm_clicked = True
                            print(f'confirm clicked: {txt}')
                            time.sleep(10)
                            break
                    except: pass
                if confirm_clicked:
                    break
            except: pass
        # URL change check
        if '/n/' in page.url and '/publish' not in page.url:
            break

    time.sleep(8)
    print(f"final url: {page.url}")
    browser.close()
