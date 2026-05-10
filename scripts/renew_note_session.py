"""note.com セッション自動更新（毎月実行で永遠の自動化）

GitHub Actions（renew_session.yml）から月1回自動実行され、
NOTE_SESSION_B64 Secret を GitHub APIで自動更新します。

必要な環境変数:
  NOTE_EMAIL, NOTE_PASSWORD, GH_PAT (repo+secrets書き込み権限のPAT), GITHUB_REPO
"""

import os, sys, json, base64, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SESSION_FILE = Path(__file__).parent.parent / "data" / "note_session.json"
NOTE_EMAIL = os.getenv("NOTE_EMAIL", "")
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "")
GH_PAT = os.getenv("GH_PAT", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "harypary/keiba-auto-post")


def login_and_save():
    from playwright.sync_api import sync_playwright
    print("[1/3] note.com 自動ログイン...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        )
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page.goto("https://note.com/login", wait_until="networkidle")
        time.sleep(2)
        for sel in ['input[name="email"]', 'input[type="email"]', '#email']:
            try:
                page.fill(sel, NOTE_EMAIL); break
            except Exception:
                continue
        for sel in ['input[name="password"]', 'input[type="password"]', '#password']:
            try:
                page.fill(sel, NOTE_PASSWORD); break
            except Exception:
                continue
        time.sleep(0.5)
        for sel in ['button[type="submit"]', 'button:has-text("ログイン")', 'button[data-type="primary"]']:
            try:
                page.click(sel); break
            except Exception:
                continue
        time.sleep(5)
        if "login" in page.url:
            raise RuntimeError(f"ログイン失敗: {page.url}")
        print(f"    OK: {page.url}")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        state = ctx.storage_state()
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        browser.close()
    print(f"    保存: cookies={len(state.get('cookies', []))}")


def encode_b64() -> str:
    return base64.b64encode(open(SESSION_FILE, "rb").read()).decode()


def update_secret(value: str):
    if not GH_PAT or not GITHUB_REPO:
        print("[3/3] GH_PAT/GITHUB_REPO 未設定 → 手動更新してください:")
        print(f"値: {value[:60]}...")
        return
    print(f"[3/3] GitHub Secret 更新: {GITHUB_REPO}/NOTE_SESSION_B64")
    import urllib.request, urllib.error
    headers = {"Authorization": f"token {GH_PAT}", "Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/public-key", headers=headers)
    pk = json.loads(urllib.request.urlopen(req).read())
    from nacl import public as nacl_public
    box = nacl_public.SealedBox(nacl_public.PublicKey(base64.b64decode(pk["key"])))
    enc = base64.b64encode(box.encrypt(value.encode())).decode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/NOTE_SESSION_B64",
        data=json.dumps({"encrypted_value": enc, "key_id": pk["key_id"]}).encode(),
        headers={**headers, "Content-Type": "application/json"}, method="PUT",
    )
    try:
        urllib.request.urlopen(req)
        print("    OK ✅")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API: {e.code} {e.read().decode()}")


def main():
    if not NOTE_EMAIL or not NOTE_PASSWORD:
        print("ERROR: NOTE_EMAIL/NOTE_PASSWORD 未設定")
        sys.exit(1)
    login_and_save()
    b64 = encode_b64()
    print(f"[2/3] Base64: {len(b64)} chars")
    update_secret(b64)
    print("\n✅ 完了。セッション有効期限まで自動投稿継続。")


if __name__ == "__main__":
    main()
