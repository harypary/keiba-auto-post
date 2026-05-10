"""note.com セッション初期化（一度だけ実行）

【実行方法】
  cd C:\\Users\\haryp\\game\\21.kiba
  pip install playwright
  playwright install chromium
  python scripts/setup_note_session.py

ブラウザが開くので note.com にログインしてください。完了後ターミナルで Enter。
保存された data/note_session.json を Base64化して GitHub Secret NOTE_SESSION_B64 に設定すれば永遠に自動投稿されます。
"""

import json, sys, base64
from pathlib import Path

SESSION_FILE = Path(__file__).parent.parent / "data" / "note_session.json"


def main():
    print("=" * 60)
    print("note.com セッション初期化")
    print("=" * 60)

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, args=["--no-sandbox"])
            print("[INFO] システムChromeを使用")
        except Exception:
            browser = p.chromium.launch(headless=False, args=["--no-sandbox"])
            print("[INFO] Playwright Chromiumを使用")

        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto("https://note.com/login")
        print(f"\nブラウザが開きました。note.com にログインしてください。\n")
        input("ログイン完了後、Enter キーを押してください >>> ")

        state = ctx.storage_state()
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"\n✅ セッション保存: {SESSION_FILE}")
        print(f"   Cookie数: {len(state.get('cookies', []))}")
        browser.close()

    # Base64 出力（GitHub Secret 設定用）
    print("\n" + "=" * 60)
    print("GitHub Secret 用 Base64 値（NOTE_SESSION_B64）")
    print("=" * 60)
    b64 = base64.b64encode(open(SESSION_FILE, "rb").read()).decode()
    print(b64)
    print("\n上の長い文字列をすべてコピーして、")
    print("https://github.com/harypary/keiba-auto-post/settings/secrets/actions")
    print("で 'NOTE_SESSION_B64' という名前のSecretを新規作成して値を貼り付けてください。")


if __name__ == "__main__":
    main()
