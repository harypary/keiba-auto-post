"""失敗記事を再試行：境界選択モードで段落5番目あたりにラインを設定してから公開"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright

FAILED_IDS = [
    "n76e2bf8afe19", "n802995f2b4ea", "n82f788f0188c", "n8474782e60d7",
    "n8fb3a261fb25", "n9148c8b30ca1", "n9294a94a9591", "n94b6f44090b2",
    "n972a15544099", "n979d13a1bd99", "n983d9121d0af", "n9cd997ad0cc5",
    "nbe90883e9fba", "nc1dcd0ec1cd3", "nc83b17cb8b13", "nc8c6e88cc229",
    "nd1f16786befd", "nddf04d4f8d4c", "nf0edc9a40f4d",
]

state = json.load(open("data/note_session.json", encoding="utf-8"))


def publish(page, note_id):
    page.goto(f"https://editor.note.com/notes/{note_id}/publish/", wait_until="networkidle", timeout=30000)
    time.sleep(5)
    # 有料エリア設定
    try:
        page.click('button:has-text("有料エリア設定")', timeout=5000, force=True)
        time.sleep(6)
    except Exception:
        pass

    # 「ラインをこの場所に変更」ボタンを取得し、5番目を選ぶ（無料部分が ~5段落になる）
    line_btns = page.locator('button:has-text("ラインをこの場所に変更")').all()
    print(f"  line buttons: {len(line_btns)}")
    if line_btns:
        # 全体の 25% の位置（無料部分を25%にする）
        idx = max(1, min(len(line_btns) - 1, len(line_btns) // 4))
        try:
            target = line_btns[idx]
            target.scroll_into_view_if_needed(timeout=2000)
            time.sleep(0.3)
            target.click(timeout=3000, force=True)
            print(f"  clicked line button [{idx}]")
            time.sleep(3)
        except Exception as e:
            print(f"  line click fail: {e}")

    # このラインより先を有料にする
    try:
        page.click('button:has-text("このラインより先を有料にする")', timeout=4000, force=True)
        time.sleep(4)
    except Exception:
        pass

    # 投稿する
    for attempt in range(5):
        time.sleep(2)
        for b in page.locator('button:has-text("投稿する")').all():
            try:
                if b.is_visible() and (b.text_content() or "").strip() == "投稿する":
                    b.scroll_into_view_if_needed(timeout=2000)
                    b.click(timeout=3000, force=True)
                    time.sleep(10)
                    return True
            except Exception:
                continue
    return False


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(
        storage_state=state,
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    )
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())

    success = 0
    for i, nid in enumerate(FAILED_IDS, 1):
        try:
            publish(page, nid)
            import requests
            r = requests.get(f"https://note.com/_almanddd/n/{nid}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            ok = r.status_code == 200
            if ok:
                success += 1
            mark = "✓" if ok else "✗"
            print(f"[{i:2d}/{len(FAILED_IDS)}] {mark} {nid}", flush=True)
            time.sleep(3)
        except Exception as e:
            print(f"[{i:2d}/{len(FAILED_IDS)}] ✗ {nid}: {e}", flush=True)

    print(f"\n完了: {success}/{len(FAILED_IDS)}")
    browser.close()
