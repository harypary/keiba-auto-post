"""全ての下書きを一括公開（修正版・正しいフローで）"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

state = json.load(open("data/note_session.json", encoding="utf-8"))


def get_draft_ids(page):
    """下書き一覧から ID 取得"""
    page.goto("https://note.com/notes/drafts", wait_until="networkidle", timeout=30000)
    time.sleep(4)
    # スクロール
    for _ in range(5):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
    ids = page.evaluate("""
        () => {
            const out = new Set();
            document.querySelectorAll('a').forEach(a => {
                const m = (a.getAttribute('href') || '').match(/\\/notes\\/(n[a-f0-9]+)/);
                if (m) out.add(m[1]);
                const m2 = (a.getAttribute('href') || '').match(/editor\\.note\\.com\\/notes\\/(n[a-f0-9]+)/);
                if (m2) out.add(m2[1]);
            });
            return Array.from(out);
        }
    """)
    return ids


def publish_one(page, note_id):
    """1つの下書きを公開"""
    url = f"https://editor.note.com/notes/{note_id}/publish/"
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(4)

        # ステップ1: 有料エリア設定 クリック
        try:
            page.click('button:has-text("有料エリア設定")', timeout=5000, force=True)
            time.sleep(5)
        except Exception:
            pass

        # ステップ2: このラインより先を有料にする クリック
        try:
            page.click('button:has-text("このラインより先を有料にする")', timeout=4000, force=True)
            time.sleep(4)
        except Exception:
            pass

        # ステップ3: 投稿する クリック
        clicked = False
        for attempt in range(4):
            time.sleep(2)
            for b in page.locator('button:has-text("投稿する")').all():
                try:
                    if b.is_visible() and (b.text_content() or "").strip() == "投稿する":
                        b.scroll_into_view_if_needed(timeout=2000)
                        b.click(timeout=3000, force=True)
                        clicked = True
                        time.sleep(8)
                        break
                except Exception:
                    continue
            if clicked:
                break

        # 検証: 公開URLで200か
        import requests
        r = requests.get(f"https://note.com/_almanddd/n/{note_id}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  [error] {note_id}: {e}")
        return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            storage_state=state,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        ids = get_draft_ids(page)
        print(f"[publish_all] 下書きID: {len(ids)}件")
        for i, note_id in enumerate(ids, 1):
            ok = publish_one(page, note_id)
            mark = "✓" if ok else "✗"
            print(f"[{i:3d}/{len(ids)}] {mark} {note_id}")
            time.sleep(3)

        browser.close()


if __name__ == "__main__":
    main()
