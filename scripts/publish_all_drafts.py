"""note 下書きを全部公開する"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

SESSION = "data/note_session.json"
state = json.load(open(SESSION, encoding="utf-8"))


def publish_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            storage_state=state,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        # 下書き一覧を取得
        page.goto("https://note.com/notes", wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # 下書きフィルタ
        try:
            page.click('a:has-text("下書き"), button:has-text("下書き")', timeout=4000)
        except Exception:
            pass
        time.sleep(2)

        # 全下書き URL を取得
        urls = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/notes/n"]');
                const out = new Set();
                links.forEach(a => {
                    const m = a.href.match(/notes\\/(n[a-f0-9]+)/);
                    if (m) out.add(m[1]);
                });
                return Array.from(out);
            }
        """)
        print(f"[publish] 下書き候補: {len(urls)}件")
        if not urls:
            # 別ページ
            page.goto("https://note.com/manage/notes?status=draft", wait_until="networkidle", timeout=20000)
            time.sleep(3)
            urls = page.evaluate("""
                () => {
                    const links = document.querySelectorAll('a[href*="notes/n"]');
                    const out = new Set();
                    links.forEach(a => {
                        const m = a.href.match(/notes\\/(n[a-f0-9]+)/);
                        if (m) out.add(m[1]);
                    });
                    return Array.from(out);
                }
            """)
            print(f"[publish] manage 下書き: {len(urls)}件")

        success = 0
        for i, nid in enumerate(urls, 1):
            url = f"https://editor.note.com/notes/{nid}/publish/"
            print(f"\n[{i}/{len(urls)}] {nid}")
            try:
                page.goto(url, wait_until="networkidle", timeout=20000)
                time.sleep(3)

                # 「投稿する」「公開する」のいずれかをクリック
                clicked = False
                for txt in ["投稿する", "公開する", "公開"]:
                    try:
                        btns = page.locator(f'button:has-text("{txt}"):not([disabled])').all()
                        if btns:
                            btns[-1].click(timeout=4000, force=True)
                            clicked = True
                            print(f"  → clicked: {txt}")
                            time.sleep(6)
                            break
                    except Exception:
                        continue
                if not clicked:
                    print(f"  → 公開ボタンが見つからない")
                    continue

                cur = page.url
                if "/n/" in cur:
                    print(f"  ✓ 公開URL: {cur}")
                    success += 1
                else:
                    print(f"  → 不明な状態: {cur}")
            except Exception as e:
                print(f"  → エラー: {e}")
            time.sleep(2)

        print(f"\n[完了] {success}/{len(urls)}件公開")
        browser.close()


if __name__ == "__main__":
    publish_all()
