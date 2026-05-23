"""自分の全記事をスキャンして本当の下書き(404)だけ公開する。
重複防止: 公開前に同じ race_key の記事が既に公開済みなら、その下書きは公開せずスキップ"""
import sys, os, json, time, re, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

USER = "_almanddd"
state = json.load(open("data/note_session.json", encoding="utf-8"))


def title_to_race_key(title: str) -> str:
    """重複判定キー"""
    m = re.search(r"【(\d+/\d+)[^】]*】[^｜]*?([東京京都新潟中山阪神中京福島小倉札幌函館]+)\s*(\d+)R", title or "")
    if m:
        return f"{m.group(1)}_{m.group(2)}_{m.group(3)}R"
    return (title or "").strip()[:80]


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
    """厳格な公開確認: 200 + 記事本文の存在を確認"""
    try:
        r = requests.get(f"https://note.com/{USER}/n/{note_id}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return False
        # 公開記事には og:type=article か note-body のいずれかが必ず含まれる
        body = r.text or ""
        if 'property="og:type" content="article"' in body:
            return True
        if '"isLimited"' in body and '"name":' in body:
            return True
        return False
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

        # 既に公開済みの race_key を収集（重複公開防止）
        published_keys = set()
        for nid in all_ids:
            if is_published(nid):
                try:
                    rr = requests.get(f"https://note.com/{USER}/n/{nid}",
                                      headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                    tm = re.search(r'<meta property="og:title" content="([^"]+)"', rr.text or "")
                    if tm:
                        published_keys.add(title_to_race_key(tm.group(1)))
                except Exception:
                    pass
        print(f"公開済み race_key: {len(published_keys)}件")

        drafts = []
        skipped_dup = 0
        for nid in all_ids:
            if is_published(nid):
                continue
            # 下書きの場合、タイトルを取得して既存公開済みと重複チェック
            try:
                page.goto(f"https://editor.note.com/notes/{nid}/edit/",
                          wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                title = page.evaluate("""
                    () => {
                        const t = document.querySelector('[data-testid="title"], input[name="title"], .title input, h1, [class*="title" i]');
                        return t ? (t.value || t.innerText || '').trim() : '';
                    }
                """) or ""
                if title:
                    key = title_to_race_key(title)
                    if key in published_keys:
                        skipped_dup += 1
                        print(f"  [SKIP重複] {nid}: '{title[:50]}' (key={key} は既に公開済み)")
                        continue
                drafts.append(nid)
            except Exception as e:
                print(f"  タイトル取得失敗 {nid}: {e}")
                drafts.append(nid)   # 取れなくても下書きは公開試行
        print(f"うち真の下書き: {len(drafts)}件 / 重複スキップ: {skipped_dup}件")

        success = 0
        for round_idx in range(6):   # 3→6 ラウンドに増やして公開達成率向上
            if not drafts:
                break
            print(f"\n=== ラウンド {round_idx+1}/6 ===")
            remaining = []
            for i, nid in enumerate(drafts, 1):
                try:
                    publish(page, nid)
                    # 公開反映には数秒のラグがある場合があるので再確認
                    ok = is_published(nid)
                    if not ok:
                        time.sleep(5)
                        ok = is_published(nid)
                except Exception as e:
                    print(f"  err: {e}")
                    ok = False
                if ok:
                    success += 1
                    mark = "✓"
                    # 永続ログを後追い記録（タイトル取得を試みる）
                    try:
                        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
                        from src.publisher.article_log import record_post
                        # 公開ページからタイトル取得
                        rr = requests.get(f"https://note.com/{USER}/n/{nid}",
                                          headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                        import re as _re
                        tm = _re.search(r'<meta property="og:title" content="([^"]+)"', rr.text or "")
                        title = tm.group(1) if tm else f"draft_{nid}"
                        record_post(title, "", nid, f"https://note.com/{USER}/n/{nid}", verified=True)
                    except Exception:
                        pass
                else:
                    remaining.append(nid)
                    mark = "✗"
                print(f"[R{round_idx+1} {i:3d}/{len(drafts)}] {mark} {nid}", flush=True)
                time.sleep(2)
            drafts = remaining
            # ラウンド間で待機（note.com側のクールダウン）
            if drafts and round_idx < 5:
                time.sleep(15)

        print(f"\n=== 完了 ===")
        print(f"成功: {success}")
        print(f"残り未公開: {len(drafts)}件")
        # 未解決はファイルに保存（次runで優先処理対象）
        if drafts:
            json.dump(drafts, open("data/draft_unresolved.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        else:
            # 全て解決したらクリア
            unresolved_path = "data/draft_unresolved.json"
            if os.path.exists(unresolved_path):
                os.remove(unresolved_path)
        browser.close()
        # 残り0件なら exit 0、残ってたら exit 1（上位がエスカレ判定）
        sys.exit(0 if not drafts else 1)


if __name__ == "__main__":
    main()
