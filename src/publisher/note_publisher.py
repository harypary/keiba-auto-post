"""note.com 自動投稿（Playwright + ストレージステート方式）

設計思想:
  - 一度 setup_note_session.py で手動ログインして session.json を作る
  - 以降は session.json を読み込んでブラウザに復元するだけで認証完了
  - GitHub Actions では NOTE_SESSION_B64 環境変数（Base64エンコード済み）から復元
  - 期限切れ時は renew_note_session.py が自動更新

参考: C:\\Users\\haryp\\game\\12.uranai\\src\\publishers\\note_publisher.py
"""

import os, json, time, base64
from pathlib import Path
from typing import Optional
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.settings import NOTE_USER_ID

SESSION_FILE = Path(__file__).parent.parent.parent / "data" / "note_session.json"

NOTE_NEW_ARTICLE_URL = "https://note.com/notes/new"
POST_INTERVAL = 35   # 投稿間隔（秒）


def _wait(seconds: float):
    import random
    time.sleep(seconds + random.uniform(0, 0.4))


class NotePublisher:
    """note.com 有料記事の自動投稿"""

    def __init__(self):
        self._storage_state = self._load_session()

    # ────────────────────────────────────────────
    # セッション管理
    # ────────────────────────────────────────────

    def _load_session(self) -> Optional[dict]:
        # GitHub Actions: 環境変数（Base64）優先
        b64 = os.environ.get("NOTE_SESSION_B64", "").strip()
        if b64:
            try:
                state = json.loads(base64.b64decode(b64).decode("utf-8"))
                print(f"[note] セッション復元（NOTE_SESSION_B64）: cookies={len(state.get('cookies', []))}")
                return state
            except Exception as e:
                print(f"[note] B64セッション復元失敗: {e}")

        # ローカル: ファイル
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, encoding="utf-8") as f:
                    state = json.load(f)
                print(f"[note] セッション復元（ファイル）: cookies={len(state.get('cookies', []))}")
                return state
            except Exception as e:
                print(f"[note] ファイルセッション復元失敗: {e}")
        return None

    def login(self) -> bool:
        """互換のため残す。session_state があれば True"""
        return self._storage_state is not None

    # ────────────────────────────────────────────
    # 記事投稿（公開API）
    # ────────────────────────────────────────────

    def create_paid_article(
        self,
        title: str,
        body: str,
        tags: list[str],
        price: int = 300,
        paid_body_start_marker: str = "👇 ここから有料公開部分",
    ) -> dict | None:
        """有料記事を作成・公開してURL情報を返す"""
        if not self._storage_state:
            print("[note] セッションなし → 投稿不可。setup_note_session.py を先に実行してください。")
            return None

        # 無料/有料の分割
        if paid_body_start_marker in body:
            idx = body.index(paid_body_start_marker)
            free_body = body[:idx].strip()
            paid_body = body[idx:].strip()
        else:
            free_body = body
            paid_body = ""

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[note] playwright未インストール → pip install playwright && playwright install chromium")
            return None

        url = self._publish_with_playwright(
            title=title, teaser=free_body, paid=paid_body,
            tags=tags or [], price=price,
        )
        if url:
            return {"url": url, "title": title}
        return None

    # ────────────────────────────────────────────
    # Playwrightによる投稿
    # ────────────────────────────────────────────

    def _publish_with_playwright(self, title, teaser, paid, tags, price) -> Optional[str]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                permissions=["clipboard-read", "clipboard-write"],
                storage_state=self._storage_state,
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.on("dialog", lambda d: d.accept())

            try:
                # セッション確認 + 新規ノート作成のためにトップから「投稿」リンクをクリック
                page.goto("https://note.com", wait_until="networkidle", timeout=30000)
                _wait(2)
                print(f"[note] 投稿開始: {title[:40]}")

                # ★トップページの年齢認証/同意モーダルを最初に閉じる
                self._dismiss_modals(page)

                # 「投稿する」リンク経由でエディタを起動（force=True でモーダル無視）
                opened = False
                for sel in [
                    'a[href*="/notes/new"]',
                    'a[href="/notes/new"]',
                    'a:has-text("投稿")',
                ]:
                    try:
                        els = page.locator(sel).all()
                        if els:
                            els[0].click(timeout=5000, force=True)
                            opened = True
                            break
                    except Exception:
                        continue
                if not opened:
                    page.goto(NOTE_NEW_ARTICLE_URL, wait_until="networkidle", timeout=30000)
                _wait(5)
                # editorのProseMirrorが現れるまで待機（最大30秒）
                try:
                    page.wait_for_selector(".ProseMirror, [contenteditable='true']", timeout=30000)
                except Exception as ex:
                    print(f"[note] エディタ起動タイムアウト: {ex} (URL: {page.url})")
                    return None
                _wait(2)

                # モーダル（年齢認証など）が現れたら閉じる
                self._dismiss_modals(page)

                # タイトル入力
                self._fill_title(page, title)
                _wait(1)

                # 本文入力（無料 + 有料区切り + 有料）
                self._fill_body(page, teaser, paid)
                _wait(2)

                # 公開設定ページへ
                try:
                    page.click('button:has-text("公開に進む")', timeout=8000)
                    _wait(4)
                except Exception as e:
                    # スクリーンショット＋HTML保存
                    try:
                        page.screenshot(path=f"/tmp/note_fail_publish_btn_{int(time.time())}.png")
                        with open(f"/tmp/note_fail_html_{int(time.time())}.html", "w", encoding="utf-8") as f:
                            f.write(page.content()[:50000])
                    except Exception:
                        pass
                    print(f"[note] 「公開に進む」失敗: {e}")
                    print(f"[note] 現URL: {page.url}")
                    # ボタンテキスト探索
                    buttons = page.locator("button").all()
                    btn_texts = []
                    for b in buttons[:30]:
                        try:
                            t = b.text_content() or ""
                            if t.strip():
                                btn_texts.append(t.strip()[:30])
                        except Exception:
                            pass
                    print(f"[note] 利用可能ボタン: {btn_texts}")
                    return None

                # ハッシュタグ
                if tags:
                    self._set_hashtags(page, tags[:5])
                    _wait(1)

                # 価格設定
                self._set_price(page, price)
                _wait(1)

                # 有料エリア設定
                try:
                    page.click('button:has-text("有料エリア設定")', timeout=8000)
                    _wait(4)
                except Exception:
                    pass

                # 投稿する
                try:
                    page.click('button:has-text("投稿する")', timeout=8000)
                    _wait(8)
                except Exception as e:
                    print(f"[note] 「投稿する」失敗: {e}")
                    return None

                url = page.url
                print(f"[note] 投稿完了: {url}")
                return url
            finally:
                browser.close()

    def _dismiss_modals(self, page):
        """note.com で出てくるモーダル（年齢認証/同意/通知許可など）を強制的に閉じる"""
        for attempt in range(8):
            modal = page.query_selector(".ReactModal__Overlay--after-open, .IdentificationModal__overlay")
            if not modal:
                # JSで強制非表示
                try:
                    page.evaluate("""
                        document.querySelectorAll('.ReactModalPortal, .ReactModal__Overlay, [class*="Modal__overlay"]').forEach(el => el.remove());
                    """)
                except Exception:
                    pass
                return
            print(f"[note] モーダル検出 (attempt {attempt+1}) → 閉じる")
            # ボタンクリック試行
            for sel in [
                'button:has-text("確認")', 'button:has-text("OK")',
                'button:has-text("はい")', 'button:has-text("同意")',
                'button:has-text("閉じる")', 'button:has-text("Skip")',
                'button[aria-label="閉じる"]', 'button[aria-label="Close"]',
                '.ReactModal__Content button',
            ]:
                try:
                    btns = page.locator(sel).all()
                    if btns:
                        btns[-1].click(timeout=1500, force=True)
                        _wait(1)
                        break
                except Exception:
                    continue
            # それでも残っていれば JS で強制削除
            try:
                page.evaluate("""
                    document.querySelectorAll('.ReactModalPortal, .ReactModal__Overlay, [class*="Modal__overlay"]').forEach(el => el.remove());
                    document.body.style.overflow = 'auto';
                """)
            except Exception:
                pass
            _wait(0.5)

    def _fill_title(self, page, title: str):
        for sel in [
            'input[placeholder*="タイトル"]',
            'textarea[placeholder*="タイトル"]',
            '[data-placeholder*="タイトル"]',
        ]:
            try:
                page.wait_for_selector(sel, timeout=4000)
                page.fill(sel, title)
                return
            except Exception:
                continue
        # フォールバック
        page.keyboard.press("Tab")
        page.keyboard.type(title)

    def _fill_body(self, page, teaser: str, paid: str):
        # 本文エリアをクリック
        body_el = None
        for sel in [".ProseMirror", '[role="textbox"]', '[contenteditable="true"]']:
            try:
                page.wait_for_selector(sel, timeout=4000)
                body_el = page.query_selector(sel)
                if body_el:
                    break
            except Exception:
                continue
        if body_el:
            body_el.click()
        _wait(0.5)

        # 無料部分（クリップボード経由）
        page.evaluate(f"navigator.clipboard.writeText({json.dumps(teaser)})")
        _wait(0.3)
        page.keyboard.press("Control+v")
        _wait(0.5)

        # 有料区切り挿入
        if paid:
            self._insert_paid_boundary(page)
            _wait(1)
            # 有料部分
            page.evaluate(f"navigator.clipboard.writeText({json.dumps(paid)})")
            _wait(0.5)
            page.keyboard.press("Control+v")
            _wait(2)

    def _insert_paid_boundary(self, page):
        try:
            page.keyboard.press("Control+End")
            _wait(0.5)
            page.hover(".ProseMirror > *:last-child", timeout=4000)
            _wait(0.3)
            page.click('[aria-label="メニューを開く"]', timeout=4000)
            _wait(0.5)
            page.click('text=有料エリア指定', timeout=4000)
            _wait(1)
        except Exception:
            page.keyboard.press("Enter")
            page.keyboard.type("【ここから有料コンテンツ】")
            page.keyboard.press("Enter")

    def _set_hashtags(self, page, hashtags):
        try:
            loc = page.locator('input[placeholder*="ハッシュタグ"]').first
            loc.wait_for(state="visible", timeout=4000)
            for tag in hashtags:
                loc.fill(tag)
                loc.press("Enter")
                _wait(0.3)
        except Exception as e:
            print(f"[note] ハッシュタグ失敗: {e}")

    def _set_price(self, page, price):
        try:
            loc = page.locator('#price').first
            loc.wait_for(state="visible", timeout=4000)
            loc.click(click_count=3)
            _wait(0.2)
            loc.fill(str(price))
            _wait(0.3)
            loc.press("Tab")
        except Exception as e:
            print(f"[note] 価格設定失敗: {e}")

    # ────────────────────────────────────────────
    # ファイル保存（バックアップ用）
    # ────────────────────────────────────────────

    def save_to_file(self, note_data: dict, output_dir: str):
        os.makedirs(output_dir, exist_ok=True)
        filename = note_data["title"].replace("/", "-").replace(" ", "_")[:80] + ".md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {note_data['title']}\n\n")
            f.write(note_data.get("body", ""))
        print(f"[file] 保存: {filepath}")
