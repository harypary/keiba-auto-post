"""
note.com への記事自動投稿
ログイン優先順:
  1. キャッシュCookie（前回の成功時のセッション、有効ならそのまま使う）
  2. NOTE_SESSION_COOKIE 環境変数（手動で設定された場合）
  3. Selenium ヘッドレスブラウザでログイン → Cookie取得（永遠の自動運用）
  4. APIログイン（緊急フォールバック）
"""
import json
import time
import requests
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.settings import NOTE_EMAIL, NOTE_PASSWORD, NOTE_USER_ID

NOTE_API = "https://note.com/api/v1"
NOTE_API_V2 = "https://note.com/api/v2"
COOKIE_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "note_session.json")


class NotePublisher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Referer": "https://note.com/",
            "Origin": "https://note.com",
        })
        self._logged_in = False
        self._user_key = None

    def login(self) -> bool:
        """note.comにログイン（4段階フォールバックで永遠の自動化）"""
        # === 1. キャッシュCookie ===
        if self._try_cookie_login(self._load_cached_cookie(), source="cache"):
            return True

        # === 2. 環境変数のCookie ===
        env_cookie = os.environ.get("NOTE_SESSION_COOKIE", "").strip()
        if env_cookie and self._try_cookie_login(env_cookie, source="env"):
            return True

        # === 3. Seleniumブラウザログイン（メイン手段） ===
        try:
            cookie = self._selenium_login()
            if cookie and self._try_cookie_login(cookie, source="selenium"):
                self._save_cached_cookie(cookie)
                return True
        except Exception as ex:
            print(f"[note] Seleniumログイン失敗: {ex}")

        # === 4. API ログイン（緊急フォールバック） ===
        return self._try_api_login()

    def _load_cached_cookie(self) -> str:
        if not os.path.exists(COOKIE_CACHE):
            return ""
        try:
            with open(COOKIE_CACHE, encoding="utf-8") as f:
                d = json.load(f)
            # 14日以上前なら期限切れとみなす
            if time.time() - d.get("ts", 0) > 14 * 24 * 3600:
                return ""
            return d.get("cookie", "")
        except Exception:
            return ""

    def _save_cached_cookie(self, cookie: str):
        try:
            os.makedirs(os.path.dirname(COOKIE_CACHE), exist_ok=True)
            with open(COOKIE_CACHE, "w", encoding="utf-8") as f:
                json.dump({"cookie": cookie, "ts": time.time()}, f)
        except Exception:
            pass

    def _try_cookie_login(self, cookie: str, source: str = "?") -> bool:
        if not cookie:
            return False
        self.session.cookies.set("_note_session_v5", cookie, domain=".note.com", path="/")
        # 自プロフィールページの取得で認証を確認（200ならログイン成立）
        r = self.session.get(f"https://note.com/{NOTE_USER_ID}")
        if r.status_code == 200 and ("ログアウト" in r.text or "logout" in r.text.lower() or "user-status" in r.text or len(r.cookies) > 0):
            self._user_key = NOTE_USER_ID
            self._logged_in = True
            print(f"[note] ログイン成功 ({source}): {NOTE_USER_ID}")
            return True
        # API v3 確認
        r2 = self.session.get(f"https://note.com/api/v3/notes?kind=text&page=1")
        if r2.status_code == 200:
            self._user_key = NOTE_USER_ID
            self._logged_in = True
            print(f"[note] ログイン成功 ({source}, v3確認): {NOTE_USER_ID}")
            return True
        self.session.cookies.pop("_note_session_v5", None)
        print(f"[note] Cookie認証失敗 ({source}): /{NOTE_USER_ID}={r.status_code}, v3={r2.status_code}")
        return False

    def _selenium_login(self) -> str:
        """Seleniumでブラウザログイン → セッションCookie取得"""
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])

        print("[note] Selenium起動中...")
        driver = webdriver.Chrome(options=opts)
        try:
            driver.get("https://note.com/login")
            wait = WebDriverWait(driver, 20)
            email_input = wait.until(EC.presence_of_element_located((By.ID, "email")))
            email_input.send_keys(NOTE_EMAIL)
            pwd_input = driver.find_element(By.ID, "password")
            pwd_input.send_keys(NOTE_PASSWORD)
            # ログインボタン: data-type="primary" の <button>（disabledが解除されるまで待機）
            btn = None
            for _ in range(20):
                btns = driver.find_elements(By.CSS_SELECTOR, "button[data-type='primary']")
                for b in btns:
                    if b.is_enabled() and "ログイン" in (b.text or ""):
                        btn = b
                        break
                if btn:
                    break
                time.sleep(0.5)
            if not btn:
                # XPath fallback: テキストで探す
                btns = driver.find_elements(By.XPATH, "//button[contains(., 'ログイン') and not(@disabled)]")
                if btns:
                    btn = btns[0]
            if not btn:
                raise RuntimeError("ログインボタンが見つかりません")
            btn.click()
            # ログイン後のリダイレクト待ち（最大20秒）
            try:
                wait.until(lambda d: "/login" not in d.current_url)
            except Exception:
                pass
            time.sleep(3)
            # Cookie取得
            for c in driver.get_cookies():
                if c.get("name") == "_note_session_v5":
                    print(f"[note] Selenium → Cookie取得成功")
                    return c["value"]
            print(f"[note] Cookie 未取得 (URL: {driver.current_url})")
            return ""
        finally:
            driver.quit()

    def _try_api_login(self) -> bool:
        resp = self.session.get("https://note.com/login")
        csrf = self._extract_csrf(resp.text)
        if csrf:
            self.session.headers["X-CSRF-Token"] = csrf
        payload = {"login": NOTE_EMAIL, "password": NOTE_PASSWORD}
        for endpoint in [f"{NOTE_API}/sessions/sign_in", f"{NOTE_API}/sessions"]:
            resp = self.session.post(endpoint, json=payload)
            if resp.status_code in (200, 201):
                self._logged_in = True
                print(f"[note] ログイン成功 (API)")
                return True
        print(f"[note] ログイン全手段失敗")
        return False

    def create_paid_article(
        self,
        title: str,
        body: str,
        tags: list[str],
        price: int = 300,
        paid_body_start_marker: str = "👇 ここから有料公開部分",
    ) -> dict | None:
        """有料記事を Selenium UI 経由で作成・公開（永遠の自動化）"""
        if not self._logged_in:
            if not self.login():
                return None
        try:
            return self._selenium_publish(title, body, tags, price, paid_body_start_marker)
        except Exception as ex:
            print(f"[note] Selenium 投稿失敗: {ex}")
            return None

    def _selenium_publish(self, title, body, tags, price, paid_marker):
        """Selenium で editor.note.com を操作して記事を作成・公開"""
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1366,900")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36")

        driver = webdriver.Chrome(options=opts)
        try:
            # 1. Cookieを設定（ログイン状態の引き継ぎ）
            driver.get("https://note.com/")
            cookie_value = self.session.cookies.get("_note_session_v5")
            if cookie_value:
                driver.add_cookie({
                    "name": "_note_session_v5", "value": cookie_value,
                    "domain": ".note.com", "path": "/",
                })
            # 2. エディタを開く
            driver.get("https://editor.note.com/new")
            wait = WebDriverWait(driver, 30)

            # 3. タイトル入力
            title_in = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "textarea[placeholder*='タイトル'], textarea[aria-label*='タイトル'], input[placeholder*='タイトル']")
            ))
            title_in.click()
            title_in.send_keys(title)

            # 4. 本文エリアにフォーカス
            body_area = driver.find_element(By.CSS_SELECTOR, "[contenteditable='true']")
            body_area.click()
            time.sleep(0.5)
            # markdown を貼り付け（改行ごとに送信）
            for line in body.split("\n"):
                body_area.send_keys(line)
                body_area.send_keys(Keys.ENTER)
            time.sleep(2)

            # 5. 公開設定 → 有料設定 → 価格入力 → 公開ボタン
            # （UIの細かいセレクタは note.com 側で頻繁に変わるため、最低限の操作に絞る）
            # 公開ボタン押下
            publish_btn = None
            for txt in ["公開する", "公開設定", "次へ"]:
                els = driver.find_elements(By.XPATH, f"//button[contains(., '{txt}')]")
                if els:
                    publish_btn = els[0]
                    break
            if publish_btn:
                publish_btn.click()
                time.sleep(2)

            # 価格設定（あれば）
            price_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='number'], input[inputmode='numeric']")
            for pi in price_inputs:
                ph = pi.get_attribute("placeholder") or ""
                if "価格" in ph or "円" in ph or pi.get_attribute("aria-label", "") and "価格" in pi.get_attribute("aria-label"):
                    pi.clear()
                    pi.send_keys(str(price))
                    break

            # 最終的な公開ボタン
            for txt in ["公開する", "投稿"]:
                els = driver.find_elements(By.XPATH, f"//button[contains(., '{txt}') and not(@disabled)]")
                if els:
                    els[-1].click()
                    break
            time.sleep(5)

            # URL 取得
            url = driver.current_url
            if "/n/" in url:
                print(f"[note] 公開完了: {url}")
                return {"url": url, "title": title}
            print(f"[note] 公開URLが特定できず: {url}")
            return {"url": url, "title": title, "draft": True}
        finally:
            driver.quit()

    def _build_note_body(self, free_body: str, paid_body: str) -> str:
        """note.comのbody形式(Prose Mirror JSON)を生成"""
        # note.comはシンプルなMarkdown文字列も受け付ける場合がある
        # ここではMarkdownをそのまま渡す（note APIの挙動に依存）
        if paid_body:
            return free_body + "\n\n<!-- paid -->\n\n" + paid_body
        return free_body

    def _auth_headers(self) -> dict:
        return {
            "X-Note-User-Key": self._user_key or "",
        }

    def _extract_csrf(self, html: str) -> str | None:
        import re
        m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
        return m.group(1) if m else None

    def save_to_file(self, note_data: dict, output_dir: str):
        """ファイルに保存（テスト用・バックアップ）"""
        os.makedirs(output_dir, exist_ok=True)
        filename = note_data["title"].replace("/", "-").replace(" ", "_")[:80] + ".md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {note_data['title']}\n\n")
            f.write(f"**タグ**: {', '.join(note_data.get('tags', []))}\n")
            f.write(f"**価格**: {note_data.get('price', 0)}円\n\n")
            f.write("---\n\n")
            f.write(note_data["body"])
        print(f"[file] 保存: {filepath}")
        return filepath
