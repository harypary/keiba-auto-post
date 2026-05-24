"""
note.com の自分の下書き（未公開記事）を一括削除する。
公開済み記事は触らない。
"""
import sys, os, time, re, json
import urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.sync_api import sync_playwright

USER = "_almanddd"
SESSION = os.path.join(os.path.dirname(__file__), "..", "data", "note_session.json")


def is_published_url(note_id: str) -> bool:
    try:
        req = urllib.request.Request(
            f"https://note.com/{USER}/n/{note_id}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status == 200:
                body = r.read().decode("utf-8", "ignore")
                return 'property="og:type" content="article"' in body
        return False
    except Exception:
        return False


def delete_article(page, note_id: str) -> bool:
    try:
        page.goto(f"https://editor.note.com/notes/{note_id}/edit/",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)
        # JS で削除メニューを直接探す（複数候補）
        opened = page.evaluate("""
            () => {
                const sels = [
                    "button[aria-label*='メニュー']",
                    "button[aria-label*='Menu']",
                    "[class*='more' i] button",
                    "button:has(svg)",
                ];
                for (const s of sels) {
                    const btns = document.querySelectorAll(s);
                    for (const b of btns) {
                        const r = b.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) { b.click(); return true; }
                    }
                }
                return false;
            }
        """)
        time.sleep(1.5)
        # 削除リンクをクリック
        del_clicked = page.evaluate("""
            () => {
                const candidates = document.querySelectorAll('button, a, [role="menuitem"]');
                for (const el of candidates) {
                    const t = (el.innerText || '').trim();
                    if (t === '記事を削除' || t === '削除' || t === '削除する') {
                        el.click(); return true;
                    }
                }
                return false;
            }
        """)
        time.sleep(1.5)
        # 確認ダイアログ
        confirmed = page.evaluate("""
            () => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const t = (b.innerText || '').trim();
                    if (t === '削除する' || t === 'はい' || t === 'OK') {
                        b.click(); return true;
                    }
                }
                return false;
            }
        """)
        time.sleep(3)
        return confirmed
    except Exception as ex:
        print(f"    例外: {ex}")
        return False


def main():
    if not os.path.exists(SESSION):
        print(f"[ERROR] セッションがありません: {SESSION}")
        sys.exit(1)
    state = json.load(open(SESSION, encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(storage_state=state,
                                   viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        print("[1/2] 記事一覧取得中...")
        page.goto("https://note.com/notes", wait_until="networkidle", timeout=30000)
        time.sleep(4)
        for _ in range(30):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.0)
        ids = page.evaluate("""
            () => {
                const seen = new Set();
                document.querySelectorAll('a').forEach(a => {
                    const h = a.getAttribute('href') || '';
                    const m = h.match(/\\/(?:notes|n)\\/(n[a-f0-9]+)/);
                    if (m) seen.add(m[1]);
                });
                return Array.from(seen);
            }
        """)
        print(f"  記事ID: {len(ids)}件")

        print("[2/2] 下書き判定 + 削除実行...")
        drafts = []
        for nid in ids:
            if not is_published_url(nid):
                drafts.append(nid)
        print(f"  下書き判定: {len(drafts)}件")
        ok, ng = 0, 0
        for nid in drafts:
            if delete_article(page, nid):
                ok += 1
                print(f"  ✓ {nid}")
            else:
                ng += 1
                print(f"  ✗ {nid}")
            time.sleep(2)
        print(f"\n[完了] 削除 {ok}件 / 失敗 {ng}件")
        browser.close()


if __name__ == "__main__":
    main()
