"""失敗した記事を再試行（待機時間長め）"""
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
    for i, note_id in enumerate(FAILED_IDS, 1):
        try:
            page.goto(f"https://editor.note.com/notes/{note_id}/publish/", wait_until="networkidle", timeout=30000)
            time.sleep(6)

            # 有料エリア設定
            try:
                page.click('button:has-text("有料エリア設定")', timeout=6000, force=True)
                time.sleep(7)
            except Exception:
                pass

            # このラインより先を有料にする
            try:
                page.click('button:has-text("このラインより先を有料にする")', timeout=5000, force=True)
                time.sleep(5)
            except Exception:
                pass

            # 投稿する（粘り強く）
            clicked = False
            for attempt in range(6):
                time.sleep(3)
                for b in page.locator('button:has-text("投稿する")').all():
                    try:
                        if b.is_visible() and (b.text_content() or "").strip() == "投稿する":
                            b.scroll_into_view_if_needed(timeout=2000)
                            b.click(timeout=4000, force=True)
                            clicked = True
                            time.sleep(12)
                            break
                    except Exception:
                        continue
                if clicked:
                    break

            import requests
            r = requests.get(f"https://note.com/_almanddd/n/{note_id}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            ok = r.status_code == 200
            if ok:
                success += 1
            mark = "✓" if ok else "✗"
            print(f"[{i:2d}/{len(FAILED_IDS)}] {mark} {note_id}", flush=True)
            time.sleep(4)
        except Exception as e:
            print(f"[{i:2d}/{len(FAILED_IDS)}] ✗ {note_id}: {e}", flush=True)

    print(f"\n再試行完了: {success}/{len(FAILED_IDS)}")
    browser.close()
