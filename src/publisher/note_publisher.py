"""
note.com への記事自動投稿
note.com の非公式APIを使用してログイン・投稿を行う
"""
import json
import time
import requests
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.settings import NOTE_EMAIL, NOTE_PASSWORD, NOTE_USER_ID

NOTE_API = "https://note.com/api/v1"
NOTE_API_V2 = "https://note.com/api/v2"


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
        """note.comにログイン
        優先順:
          1. NOTE_SESSION_COOKIE 環境変数があればそれを使用（_note_session_v5 の値）
          2. なければAPIログイン（現在は不安定）
        """
        # === 優先1: 事前取得済みセッションCookieでログイン ===
        cookie = os.environ.get("NOTE_SESSION_COOKIE", "").strip()
        if cookie:
            self.session.cookies.set("_note_session_v5", cookie, domain=".note.com", path="/")
            # 認証確認
            r = self.session.get(f"{NOTE_API}/users/me")
            if r.status_code == 200:
                try:
                    data = r.json()
                    self._user_key = (data.get("data", {}).get("urlname", "") or
                                       data.get("data", {}).get("userKey", ""))
                except Exception:
                    pass
                self._logged_in = True
                print(f"[note] ログイン成功（Cookie）: {self._user_key or NOTE_USER_ID}")
                return True
            else:
                print(f"[note] Cookie認証失敗: {r.status_code}（Cookieが期限切れの可能性）")

        # === 優先2: API ログイン（フォールバック） ===
        resp = self.session.get("https://note.com/login")
        csrf = self._extract_csrf(resp.text)
        if csrf:
            self.session.headers["X-CSRF-Token"] = csrf

        payload = {"login": NOTE_EMAIL, "password": NOTE_PASSWORD}
        for endpoint in [
            f"{NOTE_API}/sessions/sign_in",
            f"{NOTE_API}/sessions",
        ]:
            resp = self.session.post(endpoint, json=payload)
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                    self._user_key = data.get("data", {}).get("userKey", "")
                except Exception:
                    pass
                self._logged_in = True
                print(f"[note] ログイン成功: {NOTE_EMAIL}")
                return True

        print(f"[note] ログイン失敗: API認証エラー。NOTE_SESSION_COOKIE を Secret に設定してください。")
        print(f"      → ブラウザで note.com にログイン後、DevTools の Application > Cookies > _note_session_v5 の値をコピー")
        return False

    def create_paid_article(
        self,
        title: str,
        body: str,
        tags: list[str],
        price: int = 300,
        paid_body_start_marker: str = "👇 ここから有料公開部分",
    ) -> dict | None:
        """有料記事を下書きとして作成し公開する"""
        if not self._logged_in:
            if not self.login():
                return None

        # 無料部分と有料部分を分割
        if paid_body_start_marker in body:
            split_idx = body.index(paid_body_start_marker)
            free_body = body[:split_idx].strip()
            paid_body = body[split_idx:].strip()
        else:
            free_body = body
            paid_body = ""

        # 記事作成（下書き）
        note_body_json = self._build_note_body(free_body, paid_body)

        payload = {
            "note": {
                "name": title,
                "status": "draft",
                "price": price,
                "note_type": "text",
                "hashtag_list": tags[:10],
                "eyecatch_key": "",
                "eyecatch_url": "",
                "body": note_body_json,
            }
        }

        resp = self.session.post(
            f"{NOTE_API_V2}/creator/notes",
            json=payload,
            headers=self._auth_headers(),
        )

        if resp.status_code not in (200, 201):
            print(f"[note] 記事作成失敗: {resp.status_code}")
            print(resp.text[:500])
            return None

        note_data = resp.json().get("data", {})
        note_key = note_data.get("key", "")
        print(f"[note] 下書き作成: {title} (key={note_key})")

        # 公開
        time.sleep(2)
        publish_resp = self.session.patch(
            f"{NOTE_API_V2}/creator/notes/{note_key}",
            json={"note": {"status": "published"}},
            headers=self._auth_headers(),
        )

        if publish_resp.status_code in (200, 201):
            pub_data = publish_resp.json().get("data", {})
            url = f"https://note.com/{NOTE_USER_ID}/n/{note_key}"
            print(f"[note] 公開完了: {url}")
            return {"key": note_key, "url": url, "title": title}
        else:
            print(f"[note] 公開失敗: {publish_resp.status_code}")
            return {"key": note_key, "url": "", "title": title, "draft": True}

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
