"""note.com 投稿フロー実検証：各ステップで HTML を保存し UI を解析する"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.sync_api import sync_playwright
from src.publisher.note_publisher import SESSION_FILE

DEBUG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "debug_publish")
os.makedirs(DEBUG_DIR, exist_ok=True)


def dump(page, name):
    ts = int(time.time())
    page.screenshot(path=f"{DEBUG_DIR}/{name}_{ts}.png", full_page=True)
    with open(f"{DEBUG_DIR}/{name}_{ts}.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    # 全button情報
    buttons = []
    for b in page.locator("button").all()[:50]:
        try:
            t = (b.text_content() or "").strip()
            if t:
                buttons.append({"text": t[:50], "enabled": b.is_enabled(), "visible": b.is_visible()})
        except Exception:
            pass
    inputs = []
    for i in page.locator("input").all()[:30]:
        try:
            inputs.append({
                "type": i.get_attribute("type"),
                "id":   i.get_attribute("id"),
                "name": i.get_attribute("name"),
                "placeholder": i.get_attribute("placeholder"),
            })
        except Exception:
            pass
    with open(f"{DEBUG_DIR}/{name}_{ts}_meta.json", "w", encoding="utf-8") as f:
        json.dump({"url": page.url, "buttons": buttons, "inputs": inputs}, f, ensure_ascii=False, indent=2)
    print(f"[debug] {name} dumped: {ts}")
    print(f"  url: {page.url}")
    print(f"  buttons (top 20): {[b['text'] for b in buttons[:20]]}")


with open(SESSION_FILE, encoding="utf-8") as f:
    storage = json.load(f)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(storage_state=storage, viewport={"width": 1280, "height": 900})
    page = ctx.new_page()

    print("[1] note.com トップ確認")
    page.goto("https://note.com", wait_until="networkidle", timeout=30000)
    time.sleep(2)
    dump(page, "1_top")

    print("[2] /notes/new")
    page.goto("https://note.com/notes/new", wait_until="networkidle", timeout=30000)
    time.sleep(3)
    dump(page, "2_editor_new_short_wait")
    # wait for content to load - up to 30 seconds
    for sec in range(30):
        body_size = len(page.content())
        title_input = page.query_selector('input[placeholder*="タイトル"], textarea[placeholder*="タイトル"]')
        prosemirror = page.query_selector(".ProseMirror")
        if title_input or prosemirror:
            print(f"  [{sec}s] エディタロード完了 (size={body_size})")
            break
        if sec % 5 == 0:
            print(f"  [{sec}s] 待機中... size={body_size}")
        time.sleep(1)
    dump(page, "2_editor_new_after_wait")

    # Title fill
    print("[3] タイトル入力")
    for sel in ['input[placeholder*="タイトル"]', 'textarea[placeholder*="タイトル"]']:
        try:
            page.fill(sel, "デバッグテスト")
            print(f"  title filled via {sel}")
            break
        except Exception as e:
            print(f"  {sel}: {e}")
    time.sleep(2)
    dump(page, "3_title_filled")

    # Body fill
    print("[4] 本文入力")
    body_el = page.query_selector(".ProseMirror") or page.query_selector("[contenteditable='true']")
    if body_el:
        body_el.click()
        time.sleep(0.5)
        page.evaluate('navigator.clipboard.writeText("テスト本文だよ")')
        time.sleep(0.3)
        page.keyboard.press("Control+v")
        time.sleep(2)
    dump(page, "4_body_filled")

    # 公開に進む
    print("[5] 公開に進む クリック試行")
    btn_texts_to_try = ["公開に進む", "次へ", "公開", "公開設定"]
    clicked = False
    for txt in btn_texts_to_try:
        try:
            page.click(f'button:has-text("{txt}")', timeout=4000)
            print(f"  clicked: {txt}")
            clicked = True
            break
        except Exception as e:
            print(f"  {txt}: {type(e).__name__}")
    time.sleep(5)
    dump(page, "5_after_publish_click")

    print("[6] 価格 input 探索")
    for sel in ["#price", "input[type='number']", "input[inputmode='numeric']", "input[placeholder*='円']"]:
        els = page.locator(sel).all()
        print(f"  {sel}: {len(els)}個")

    browser.close()
print(f"\nデバッグデータ: {DEBUG_DIR}")
