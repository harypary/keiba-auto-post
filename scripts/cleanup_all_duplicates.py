"""
note.com の重複記事を一括クリーンアップ:
1. 同じ race_key で複数公開されている → 最古の1件を残し他を削除
2. 公開済みと同じ race_key の下書き → 全て削除

実行: ローカル PC で python scripts/cleanup_all_duplicates.py
"""
import sys, os, time, re, json
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.sync_api import sync_playwright

USER = "_almanddd"
SESSION = os.path.join(os.path.dirname(__file__), "..", "data", "note_session.json")


def title_to_race_key(title: str) -> str:
    m = re.search(r"【(\d+/\d+)[^】]*】[^｜]*?([東京京都新潟中山阪神中京福島小倉札幌函館]+)\s*(\d+)R", title or "")
    if m:
        return f"{m.group(1)}_{m.group(2)}_{m.group(3)}R"
    mm = re.search(r"【(\d+/\d+)[^】]*】([^｜]+)", title or "")
    if mm:
        return f"{mm.group(1)}_{mm.group(2).strip()}"
    return (title or "").strip()[:80]


def delete_article(page, note_id: str) -> bool:
    """editor.note.com で記事を削除"""
    try:
        page.goto(f"https://editor.note.com/notes/{note_id}/edit/",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)
        # 削除メニュー候補をいくつか試す
        for menu_sel in [
            "button[aria-label*='メニュー']",
            "button[aria-label*='menu' i]",
            "button:has-text('・・・')",
            "button.more-actions",
            "[class*='menu' i] button",
        ]:
            try:
                btn = page.locator(menu_sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=4000, force=True)
                    time.sleep(1)
                    break
            except Exception:
                continue
        # 削除リンク
        for del_sel in [
            "button:has-text('記事を削除')",
            "button:has-text('削除する')",
            "a:has-text('記事を削除')",
            "a:has-text('削除する')",
            "[role='menuitem']:has-text('削除')",
        ]:
            try:
                el = page.locator(del_sel).first
                if el.count() > 0 and el.is_visible():
                    el.click(timeout=4000, force=True)
                    time.sleep(1.5)
                    break
            except Exception:
                continue
        # 確認ダイアログ
        for confirm_sel in [
            "button:has-text('削除する')",
            "button:has-text('はい')",
            "button:has-text('OK')",
        ]:
            try:
                el = page.locator(confirm_sel).first
                if el.count() > 0 and el.is_visible():
                    el.click(timeout=4000, force=True)
                    time.sleep(3)
                    return True
            except Exception:
                continue
    except Exception as ex:
        print(f"    例外: {ex}")
    return False


def get_article_title(page, note_id: str) -> str:
    """記事タイトルを編集ページから取得"""
    try:
        page.goto(f"https://editor.note.com/notes/{note_id}/edit/",
                  wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)
        title = page.evaluate("""
            () => {
                const tags = ['input[name="title"]', '[data-testid="title"]',
                              '.title input', 'h1', 'textarea[placeholder*="タイトル"]'];
                for (const sel of tags) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const v = (el.value || el.innerText || '').trim();
                        if (v) return v;
                    }
                }
                return '';
            }
        """) or ""
        return title
    except Exception:
        return ""


def is_published_url(note_id: str) -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(f"https://note.com/{USER}/n/{note_id}",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status == 200:
                body = r.read().decode("utf-8", "ignore")
                if 'property="og:type" content="article"' in body:
                    return True
        return False
    except Exception:
        return False


def main():
    if not os.path.exists(SESSION):
        print(f"[ERROR] セッションファイルがありません: {SESSION}")
        sys.exit(1)
    state = json.load(open(SESSION, encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(storage_state=state, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        # 全記事 ID と タイトル取得
        print("[1/3] 記事一覧取得中...")
        page.goto("https://note.com/notes", wait_until="networkidle", timeout=30000)
        time.sleep(4)
        for _ in range(25):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.0)
        items = page.evaluate("""
            () => {
                const seen = new Set();
                const out = [];
                document.querySelectorAll('a').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const m = href.match(/\\/(?:notes|n)\\/(n[a-f0-9]+)/);
                    if (m) {
                        const nid = m[1];
                        if (seen.has(nid)) return;
                        seen.add(nid);
                        const card = a.closest('article, li, [class*="card" i]');
                        let title = '';
                        if (card) {
                            const t = card.querySelector('h3, h2, [class*="title" i]');
                            if (t) title = t.innerText.trim();
                        }
                        out.push({note_id: nid, title: title});
                    }
                });
                return out;
            }
        """)
        print(f"  記事ID取得: {len(items)}件")

        # タイトル不明なものは編集ページから取得
        for it in items:
            if not it.get("title"):
                it["title"] = get_article_title(page, it["note_id"])

        # 公開/下書き判定
        print("\n[2/3] 公開/下書き判定中...")
        for it in items:
            it["published"] = is_published_url(it["note_id"])
            it["race_key"] = title_to_race_key(it.get("title", ""))

        published = [it for it in items if it["published"] and it.get("race_key")]
        drafts    = [it for it in items if not it["published"] and it.get("race_key")]
        print(f"  公開: {len(published)}件 / 下書き: {len(drafts)}件")

        # 公開済みの race_key
        published_keys = defaultdict(list)
        for it in published:
            published_keys[it["race_key"]].append(it)

        # 削除対象収集
        targets = []
        # 1. 同race_keyの公開重複 → 最初の1つを残し他を削除
        for key, lst in published_keys.items():
            if len(lst) > 1:
                # 最初を残し、残りを削除対象に
                for extra in lst[1:]:
                    targets.append(("公開重複", key, extra))
        # 2. 公開済みと同race_keyの下書き → 全て削除
        for it in drafts:
            if it["race_key"] in published_keys:
                targets.append(("被り下書き", it["race_key"], it))

        print(f"\n[3/3] 削除対象: {len(targets)}件")
        for kind, key, it in targets:
            print(f"  [{kind}] {key} / {it['note_id']}: {it['title'][:50]}")

        if not targets:
            print("\n削除対象なし。クリーンな状態です。")
            browser.close()
            return

        # 削除実行
        print("\n削除実行中...")
        ok, ng = 0, 0
        for kind, key, it in targets:
            print(f"  削除: [{kind}] {it['note_id']} ({key})")
            if delete_article(page, it["note_id"]):
                ok += 1
                print(f"    ✓ 削除成功")
            else:
                ng += 1
                print(f"    ✗ 削除失敗")
            time.sleep(2)

        print(f"\n[完了] 削除成功 {ok}件 / 失敗 {ng}件")
        browser.close()


if __name__ == "__main__":
    main()
