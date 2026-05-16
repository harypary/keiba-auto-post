"""自分の全記事をスキャンして本当の下書き(404)だけ公開する"""
import sys, os, json, time, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

USER = "_almanddd"
state = json.load(open("data/note_session.json", encoding="utf-8"))


def get_all_article_ids(page):
    """記事管理ページから全 ID 取得（公開・下書き両方）"""
    ids = set()
    page.goto("https://note.com/notes", wait_until="networkidle", timeout=30000)
    time.sleep(4)
    for _ in range(15):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
    found = page.evaluate("""
        () => {
            const set = new Set();
            document.querySelectorAll('a').forEach(a => {
                const href = a.getAttribute('href') || '';
                const m1 = href.match(/\\/n\\/(n[a-f0-9]+)/);
                if (m1) set.add(m1[1]);
                const m2 = href.match(/notes\\/(n[a-f0-9]+)/);
                if (m2) set.add(m2[1]);
            });
            return Array.from(set);
        }
    """)
    return [x for x in found if len(x) >= 5]


def is_published(note_id):
    try:
        r = requests.get(f"https://note.com/{USER}/n/{note_id}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def publish(page, note_id):
    """publish/ から公開フロー実行"""
    page.goto(f"https://editor.note.com/notes/{note_id}/publish/",
              wait_until="networkidle", timeout=25000)
    time.sleep(4)
    try:
        page.click('button:has-text("有料エリア設定")', timeout=5000, force=True)
        time.sleep(5)
    except Exception:
        pass
    try:
        page.click('button:has-text("このラインより先を有料にする")', timeout=4000, force=True)
        time.sleep(4)
    except Exception:
        pass
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


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            storage_state=state, viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        all_ids = get_all_article_ids(page)
        print(f"記事ID取得: {len(all_ids)}件")

        drafts = []
        for nid in all_ids:
            if not is_published(nid):
                drafts.append(nid)
        print(f"うち下書き(404): {len(drafts)}件")

        success = 0
        for round_idx in range(3):
            if not drafts:
                break
            print(f"\n=== ラウンド {round_idx+1} ===")
            remaining = []
            for i, nid in enumerate(drafts, 1):
                try:
                    publish(page, nid)
                    ok = is_published(nid)
                except Exception as e:
                    print(f"  err: {e}")
                    ok = False
                if ok:
                    success += 1
                    mark = "✓"
                else:
                    remaining.append(nid)
                    mark = "✗"
                print(f"[R{round_idx+1} {i:3d}/{len(drafts)}] {mark} {nid}", flush=True)
                time.sleep(2)
            drafts = remaining

        print(f"\n=== 完了 ===")
        print(f"成功: {success}")
        print(f"残り未公開: {len(drafts)}件")
        if drafts:
            json.dump(drafts, open("data/draft_unresolved.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        browser.close()


if __name__ == "__main__":
    main()
