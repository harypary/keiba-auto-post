"""自分の下書き全件を取得して公開する（検証＆リトライ付き）"""
import sys, os, json, time, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

state = json.load(open("data/note_session.json", encoding="utf-8"))
USER = "_almanddd"


def collect_draft_ids(page):
    """記事管理ページから下書きの note ID を全部集める"""
    ids = []
    page.goto("https://note.com/notes", wait_until="networkidle", timeout=30000)
    time.sleep(4)
    # 「公開ステータス」→「下書き」フィルタ
    try:
        page.click('button:has-text("公開ステータス")', timeout=4000, force=True)
        time.sleep(1.5)
        page.click('text=下書き', timeout=3000, force=True)
        time.sleep(3)
    except Exception as e:
        print(f"フィルタ失敗: {e}")
    # スクロールで全件ロード
    last_h = 0
    for _ in range(20):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_h:
            break
        last_h = h
    # リンク取得
    found = page.evaluate("""
        () => {
            const set = new Set();
            document.querySelectorAll('a').forEach(a => {
                const m = (a.getAttribute('href') || '').match(/notes\\/(n[a-f0-9]+)/);
                if (m) set.add(m[1]);
            });
            return Array.from(set);
        }
    """)
    return found


def publish_one(page, note_id):
    """publish/ ページから公開する"""
    try:
        page.goto(f"https://editor.note.com/notes/{note_id}/publish/",
                  wait_until="networkidle", timeout=25000)
        time.sleep(4)
        # 有料エリア設定
        try:
            page.click('button:has-text("有料エリア設定")', timeout=5000, force=True)
            time.sleep(5)
        except Exception:
            pass
        # このラインより先を有料にする
        try:
            page.click('button:has-text("このラインより先を有料にする")', timeout=4000, force=True)
            time.sleep(4)
        except Exception:
            pass
        # 投稿する
        for attempt in range(4):
            time.sleep(2)
            for b in page.locator('button:has-text("投稿する")').all():
                try:
                    if b.is_visible() and (b.text_content() or "").strip() == "投稿する":
                        b.scroll_into_view_if_needed(timeout=2000)
                        b.click(timeout=3000, force=True)
                        time.sleep(10)
                        break
                except Exception:
                    continue
        # 検証
        r = requests.get(f"https://note.com/{USER}/n/{note_id}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  error: {e}")
        return False


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            storage_state=state, viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        ids = collect_draft_ids(page)
        print(f"下書きID取得: {len(ids)}件")

        success = 0
        unresolved = []
        for round_idx in range(2):  # 最大2周
            print(f"\n=== ラウンド {round_idx+1} ===")
            remaining = []
            target = ids if round_idx == 0 else unresolved
            for i, nid in enumerate(target, 1):
                ok = publish_one(page, nid)
                if ok:
                    success += 1
                    mark = "✓"
                else:
                    remaining.append(nid)
                    mark = "✗"
                print(f"[R{round_idx+1} {i:3d}/{len(target)}] {mark} {nid}", flush=True)
                time.sleep(2)
            unresolved = remaining
            if not unresolved:
                break

        print(f"\n=== 完了 ===")
        print(f"成功: {success} / 初期下書き: {len(ids)}")
        print(f"残り未公開: {len(unresolved)}件")
        if unresolved:
            with open("data/draft_unresolved.json", "w", encoding="utf-8") as f:
                json.dump(unresolved, f, ensure_ascii=False, indent=2)

        browser.close()


if __name__ == "__main__":
    main()
