"""
note.com 上の自分の投稿から重複（同じ race_key を持つ複数記事）を検出して
古い方を削除する。最新の1記事だけ残す。
"""
import sys, os, time, re, json
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.sync_api import sync_playwright

USER = "_almanddd"
SESSION = os.path.join(os.path.dirname(__file__), "..", "data", "note_session.json")


def title_to_race_key(title: str) -> str:
    """重複判定キー: 日付_場_R"""
    m = re.search(r"【(\d+/\d+)[^】]*】[^｜]*?([東京京都新潟中山阪神中京福島小倉札幌函館]+)\s*(\d+)R", title or "")
    if m:
        return f"{m.group(1)}_{m.group(2)}_{m.group(3)}R"
    mm = re.search(r"【(\d+/\d+)[^】]*】([^｜]+)", title or "")
    if mm:
        return f"{mm.group(1)}_{mm.group(2).strip()}"
    return (title or "").strip()[:80]


def main():
    state = json.load(open(SESSION, encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        # 記事管理ページから全記事 (note_id, title, publish_date) を取得
        print("[delete_dup] 記事一覧取得中...")
        page.goto("https://note.com/notes", wait_until="networkidle", timeout=30000)
        time.sleep(4)
        for _ in range(20):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.2)

        items = page.evaluate("""
            () => {
                const result = [];
                const seen = new Set();
                document.querySelectorAll('a').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/(?:notes|n)\\/(n[a-f0-9]+)/);
                    if (m) {
                        const nid = m[1];
                        if (seen.has(nid)) return;
                        seen.add(nid);
                        const card = a.closest('article, li, div');
                        let title = '';
                        if (card) {
                            const t = card.querySelector('h3, .o-noteTitle, [class*="title" i]');
                            if (t) title = t.innerText.trim();
                        }
                        if (!title) title = a.innerText.trim();
                        result.push({note_id: nid, title: title});
                    }
                });
                return result;
            }
        """)
        print(f"[delete_dup] {len(items)} 記事検出")

        # race_key でグループ化
        groups = defaultdict(list)
        for it in items:
            t = it.get("title", "")
            if not t: continue
            key = title_to_race_key(t)
            groups[key].append(it)

        # 2件以上ある重複だけを処理
        deleted = 0
        for key, lst in groups.items():
            if len(lst) <= 1: continue
            print(f"\n[重複] {key}: {len(lst)} 件")
            for it in lst:
                print(f"  - {it['note_id']}: {it['title'][:50]}")
            # 最初の1件を残し、残りを削除
            keep = lst[0]
            print(f"  残す: {keep['note_id']}")
            for it in lst[1:]:
                nid = it["note_id"]
                # 削除URL: editor.note.com の各記事から削除メニュー
                try:
                    page.goto(f"https://editor.note.com/notes/{nid}/edit/", wait_until="networkidle", timeout=20000)
                    time.sleep(3)
                    # 右上メニューから削除
                    # まず「・・・」メニューを開く
                    menu_btn = page.locator("button[aria-label*='メニュー'], button:has-text('・・・'), button.more-actions").first
                    if menu_btn.count() > 0:
                        menu_btn.click(timeout=5000)
                        time.sleep(1)
                    # 「記事を削除」をクリック
                    delete_link = page.locator("button:has-text('記事を削除'), button:has-text('削除する'), a:has-text('削除')").first
                    if delete_link.count() > 0:
                        delete_link.click(timeout=5000)
                        time.sleep(1)
                        # 確認ダイアログの「削除」
                        confirm = page.locator("button:has-text('削除する'), button:has-text('はい')").first
                        if confirm.count() > 0:
                            confirm.click(timeout=5000)
                            time.sleep(3)
                    deleted += 1
                    print(f"  ✓ 削除: {nid}")
                except Exception as ex:
                    print(f"  ✗ 削除失敗 {nid}: {ex}")
                time.sleep(2)

        print(f"\n[delete_dup] 完了 / 削除: {deleted}件")
        browser.close()


if __name__ == "__main__":
    main()
