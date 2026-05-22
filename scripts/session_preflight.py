"""
セッション事前検証: data/note_session.json をロードしてnote.comに接続を試行。
失敗時は exit 1（呼び出し側がセッション再生成を起動）。
"""
import sys, os, json
from datetime import datetime

SESSION_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "note_session.json")


def check_session_file() -> bool:
    """セッションファイルの形式・有効期限を簡易チェック"""
    if not os.path.exists(SESSION_PATH):
        print("[PREFLIGHT] セッションファイルが存在しません", file=sys.stderr)
        return False
    try:
        with open(SESSION_PATH, encoding="utf-8") as f:
            session = json.load(f)
    except Exception as ex:
        print(f"[PREFLIGHT] セッションJSON破損: {ex}", file=sys.stderr)
        return False
    cookies = session.get("cookies", [])
    if not cookies:
        print("[PREFLIGHT] cookie が空", file=sys.stderr)
        return False
    # note.com 認証関連 cookie の有効期限確認
    now_ts = datetime.now().timestamp()
    auth_keys = ("_note_session_v5", "note_gql_auth_token", "_session_id")
    auth_alive = False
    for c in cookies:
        if c.get("name") in auth_keys:
            exp = c.get("expires", -1)
            if exp == -1 or exp > now_ts:
                auth_alive = True
                break
    if not auth_alive:
        print("[PREFLIGHT] 認証 cookie 期限切れ", file=sys.stderr)
        return False
    print(f"[PREFLIGHT] セッション形式OK / cookie数 {len(cookies)}")
    return True


def check_live_login() -> bool:
    """playwright で実際に note.com にログイン状態でアクセスできるか確認"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[PREFLIGHT] playwright未インストール、ライブチェックをスキップ")
        return True
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=SESSION_PATH)
            page = ctx.new_page()
            page.goto("https://note.com/notes/new", wait_until="domcontentloaded", timeout=20000)
            # ログインしていればエディタへ、未ログインだとログインページへ
            url = page.url
            browser.close()
            if "login" in url or "signin" in url:
                print(f"[PREFLIGHT] ライブログイン失敗 (リダイレクト先: {url})", file=sys.stderr)
                return False
            print(f"[PREFLIGHT] ライブログインOK ({url})")
            return True
    except Exception as ex:
        print(f"[PREFLIGHT] ライブチェック例外: {ex}", file=sys.stderr)
        # 例外は判定不能扱いで成功にしておく（ネットワーク問題と区別）
        return True


def main():
    if not check_session_file():
        return 1
    if not check_live_login():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
