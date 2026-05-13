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
        draft_only: bool = False,
    ) -> dict | None:
        """有料記事を作成・公開してURL情報を返す。
        draft_only=True で公開せず下書き保存のみ"""
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
            tags=tags or [], price=price, draft_only=draft_only,
        )
        if url:
            return {"url": url, "title": title}
        return None

    # ────────────────────────────────────────────
    # Playwrightによる投稿
    # ────────────────────────────────────────────

    def _publish_with_playwright(self, title, teaser, paid, tags, price, draft_only: bool = False) -> Optional[str]:
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

                # 有料モードへ切替：#paid ラジオを確実に選択（scroll + JS click）
                try:
                    paid_radio = page.locator('#paid').first
                    paid_radio.scroll_into_view_if_needed(timeout=3000)
                    _wait(0.3)
                    # JS で確実にチェック状態にして change イベント発火
                    page.evaluate("""
                        const r = document.getElementById('paid');
                        if (r) { r.click(); r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); }
                    """)
                    _wait(1.5)
                    print("[note] 有料モード切替 OK (JS)")
                except Exception as e:
                    print(f"[note] 有料モード切替失敗: {e}")

                # 価格設定
                self._set_price(page, price)
                _wait(1)

                # 「有料エリア設定」ボタン → 投稿確認画面 → 「投稿する」表示
                try:
                    page.click('button:has-text("有料エリア設定")', timeout=8000, force=True)
                    _wait(5)
                except Exception as e:
                    print(f"[note] 有料エリア設定失敗: {e}")

                # draft_only モードなら投稿せず編集URLを返す
                if draft_only:
                    print("[note] draft_only: 公開せず下書き保存")
                    _wait(3)
                    return page.url

                # 「投稿する」「公開する」のいずれかをクリック
                published = False
                for txt in ["投稿する", "公開する", "公開"]:
                    try:
                        btns = page.locator(f'button:has-text("{txt}"):not([disabled])').all()
                        if btns:
                            btns[-1].click(timeout=5000, force=True)
                            published = True
                            _wait(8)
                            break
                    except Exception:
                        continue
                if not published:
                    print(f"[note] 「投稿する」相当ボタンが見つからない")
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

        # ▼ 戦略: 一意マーカー文字列を本文に埋め込んで全文貼付
        #   → 貼付後にProseMirror APIでマーカー位置を特定して境界に置換
        BOUNDARY_MARKER = "==PAID_BOUNDARY_HERE=="
        full_body = teaser + ("\n\n" + BOUNDARY_MARKER + "\n\n" + paid if paid else "")

        self._paste_chunked(page, full_body)
        _wait(2)

        if paid:
            self._replace_marker_with_boundary(page, BOUNDARY_MARKER)
            _wait(2)

    def _replace_marker_with_boundary(self, page, marker: str):
        """マーカー段落を選択 → カーソル設定 → +メニュー → 有料エリア指定"""
        try:
            # マーカーを含む段落要素を特定し、その要素にユニークIDを設定
            bbox = page.evaluate(f"""
                () => {{
                    const pm = document.querySelector('.ProseMirror');
                    if (!pm) return null;
                    for (const child of pm.children) {{
                        if (child.textContent && child.textContent.includes({json.dumps(marker)})) {{
                            child.scrollIntoView({{block: 'center'}});
                            const r = child.getBoundingClientRect();
                            // マーカー段落のテキストを空にしてカーソル設定の準備
                            return {{x: r.x, y: r.y, w: r.width, h: r.height}};
                        }}
                    }}
                    return null;
                }}
            """)
            if not bbox:
                print(f"[note] マーカー段落不明")
                return
            _wait(0.5)

            cx = bbox["x"] + bbox["w"] / 2
            cy = bbox["y"] + bbox["h"] / 2

            # ★ STEP1: マーカー段落をクリックしてカーソルを置く
            page.mouse.click(cx, cy)
            _wait(0.5)
            # マーカーテキストを全選択して削除（空段落になる、カーソルそこに残る）
            page.keyboard.press("Control+a")  # 文字単位で全選択は段落全体
            _wait(0.2)
            # 全選択は全体になってしまうので、Home → Shift+End で段落内のみ選択
            page.keyboard.press("Home")
            _wait(0.1)
            page.keyboard.press("Shift+End")
            _wait(0.2)
            page.keyboard.press("Delete")
            _wait(0.5)

            # ★ STEP2: 同じ位置にマウス移動して + ボタンを発火（カーソルもそこにある）
            page.mouse.move(cx, cy, steps=8)
            _wait(0.8)

            # +ボタンクリック
            menu_btn = page.locator('[aria-label="メニューを開く"]').first
            try:
                menu_btn.wait_for(state="visible", timeout=4000)
            except Exception:
                # 出ない場合はマウスを少し動かして再発火
                page.mouse.move(bbox["x"] - 50, cy, steps=5)
                _wait(0.5)
                page.mouse.move(cx, cy, steps=5)
                _wait(0.8)
                menu_btn.wait_for(state="visible", timeout=2000)

            menu_btn.click(timeout=3000, force=True)
            _wait(1)

            # ★ STEP3: 「有料エリア指定」をクリック
            page.click('text=有料エリア指定', timeout=4000)
            _wait(2)
            print("[note] 境界マーカー置換成功（クリック+マウス+メニュー）")
        except Exception as e:
            print(f"[note] +メニュー失敗: {e}")

    def _paste_chunked(self, page, text: str, chunk_size: int = 1500):
        """長文を行単位で小さく分割し keyboard.type() で確実に挿入"""
        if not text:
            return
        # 1500文字ごと（行単位で区切る）
        chunks = []
        cur = ""
        for line in text.split("\n"):
            if len(cur) + len(line) + 1 > chunk_size and cur:
                chunks.append(cur)
                cur = line
            else:
                cur = (cur + "\n" + line) if cur else line
        if cur:
            chunks.append(cur)

        total = len(chunks)
        print(f"[note] 本文 {len(text)}文字 → {total}分割で貼付")
        for i, ch in enumerate(chunks):
            try:
                # クリップボード経由（高速）
                page.evaluate(f"navigator.clipboard.writeText({json.dumps(ch if i == 0 else chr(10) + ch)})")
                _wait(0.3)
                page.keyboard.press("Control+v")
                _wait(0.6)
                if i > 0 and i % 5 == 0:
                    print(f"[note]  ...{i}/{total}件")
            except Exception as e:
                print(f"[note] paste chunk {i} 失敗: {e}")

    def _insert_paid_boundary(self, page):
        """有料エリア境界線を挿入（複数戦略でフォールバック）"""
        # 戦略1: + ボタン（メニューを開く）→ 有料エリア指定
        try:
            page.keyboard.press("Control+End")
            _wait(0.5)
            page.keyboard.press("Enter")
            _wait(0.3)
            # ProseMirror 行の左端に + ボタンが出る
            page.hover(".ProseMirror > *:last-child", timeout=3000)
            _wait(0.5)
            menu_btn = page.locator('[aria-label="メニューを開く"], button[aria-label*="メニュー"]').first
            menu_btn.click(timeout=3000, force=True)
            _wait(0.7)
            page.click('text=有料エリア指定', timeout=3000)
            _wait(1)
            print("[note] 有料エリア境界 挿入成功（+メニュー経由）")
            return
        except Exception as e:
            print(f"[note] 戦略1失敗: {e}")

        # 戦略2: スラッシュコマンド
        try:
            page.keyboard.press("Control+End")
            _wait(0.3)
            page.keyboard.press("Enter")
            _wait(0.3)
            page.keyboard.type("/")
            _wait(1)
            page.keyboard.type("有料")
            _wait(0.5)
            page.keyboard.press("Enter")
            _wait(1)
            print("[note] 有料エリア境界 挿入成功（/コマンド経由）")
            return
        except Exception as e:
            print(f"[note] 戦略2失敗: {e}")

        # 戦略3: テキストフォールバック（境界線にはならないが視覚的に区切る）
        page.keyboard.press("Enter")
        page.keyboard.type("───────── 有料エリア ─────────")
        page.keyboard.press("Enter")
        print("[note] 有料エリア境界 テキストフォールバック")

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
            loc.scroll_into_view_if_needed(timeout=3000)
            _wait(0.3)
            loc.wait_for(state="visible", timeout=4000)
            loc.click(click_count=3)
            _wait(0.2)
            loc.fill(str(price))
            _wait(0.3)
            loc.press("Tab")
            print(f"[note] 価格設定 OK: {price}円")
        except Exception as e:
            print(f"[note] 価格設定失敗: {e}")
            # JSフォールバック
            try:
                page.evaluate(f"""
                    const p = document.getElementById('price');
                    if (p) {{ p.value = '{price}'; p.dispatchEvent(new Event('input', {{bubbles:true}})); p.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                """)
                print(f"[note] 価格設定 JSフォールバック")
            except Exception as ex:
                print(f"[note] 価格JS失敗: {ex}")

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
