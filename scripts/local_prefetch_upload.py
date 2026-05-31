"""
ローカル(自宅IP=netkeiba非ブロック)で対象日の全レース全頭の過去成績を取得し、
GitHub Release にzipで配信するスクリプト。

netkeiba は GitHub Actions の全IP(Ubuntu/macOS)を403ブロックするため、
CI上では過去データが取れない。唯一ブロックされない自宅PCのIPで先に取得して
Release経由でCIへ届ける、という恒久対策の取得側。

使い方:
    python scripts/local_prefetch_upload.py saturday   # 直近の土曜分
    python scripts/local_prefetch_upload.py sunday     # 直近の日曜分
    python scripts/local_prefetch_upload.py tomorrow   # 翌日分
    python scripts/local_prefetch_upload.py 20260531   # 日付指定

Windowsタスクスケジューラから自動実行する想定（register_prefetch_task.ps1 参照）。
"""
import os
import sys
import io
import time
import zipfile
import tempfile
import subprocess
from datetime import date, datetime, timedelta

# --- netkeiba 取得を速くする設定（自宅IPなので攻めて良い）---
os.environ.setdefault("REQUEST_DELAY", "0.3")
os.environ.setdefault("DISABLE_PLAYWRIGHT_FETCH", "1")
os.environ.setdefault("SCRAPE_MODE", "full")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO = "harypary/keiba-auto-post"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(ROOT, "data", "cache")
MAX_WORKERS = 8


def _resolve_target(arg: str) -> date:
    today = date.today()
    if not arg or arg == "tomorrow":
        return today + timedelta(days=1)
    if arg == "saturday":
        return today + timedelta(days=(5 - today.weekday()) % 7)
    if arg == "sunday":
        return today + timedelta(days=(6 - today.weekday()) % 7)
    # YYYYMMDD / YYYY-MM-DD
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(arg, fmt).date()
        except ValueError:
            continue
    raise SystemExit(f"日付を解釈できません: {arg}")


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def collect_horse_ids(target: date):
    from src.scraper.jra_scraper import JRAScraper
    jra = JRAScraper()
    races = jra.get_race_list_for_date(target)
    if not races:
        _log(f"{target} レースなし（開催なし or 一覧取得失敗）")
        return []
    _log(f"{target} {len(races)}レース。出馬表から全頭の馬IDを収集中...")
    seen, horse_ids = set(), []
    for raw in races:
        rid = raw["race_id"]
        try:
            race = jra.get_shutuba_table(rid)
        except Exception as ex:
            _log(f"  [warn] {rid} 出馬表失敗: {ex}")
            continue
        if not race or not race.horses:
            continue
        for e in race.horses:
            if e.horse_id and e.horse_id not in seen:
                seen.add(e.horse_id)
                horse_ids.append((e.horse_id, e.horse_name or "?"))
    _log(f"対象馬 {len(horse_ids)}頭")
    return horse_ids


def fetch_all(horse_ids):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from src.scraper.history_scraper import HistoryScraper
    from src.pipeline import _cached_history
    hist = HistoryScraper()

    def one(item):
        hid, name = item
        try:
            h = _cached_history(hist, hid, name)
            return hid, name, (len(h.records) if h and h.records else 0)
        except Exception as ex:
            return hid, name, -1

    ok = ng = 0
    done = 0
    total = len(horse_ids)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(one, it) for it in horse_ids]
        for fut in as_completed(futs):
            hid, name, n = fut.result()
            done += 1
            if n > 0:
                ok += 1
            else:
                ng += 1
            if done % 25 == 0 or done == total:
                _log(f"  進捗 {done}/{total}  成功{ok} / 失敗{ng}")
    return ok, ng


def build_zip(horse_ids, target: date) -> str:
    """その日の対象馬のキャッシュだけをzip化（資産を小さく保つ）。"""
    tmp = os.path.join(tempfile.gettempdir(), f"horse_cache_{target:%Y%m%d}.zip")
    n = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for hid, _ in horse_ids:
            p = os.path.join(CACHE_DIR, f"{hid}_full.json")
            if os.path.exists(p):
                zf.write(p, arcname=f"{hid}_full.json")
                n += 1
    _log(f"zip作成: {tmp}（{n}ファイル / {os.path.getsize(tmp)//1024}KB）")
    return tmp


def upload_release(zip_path: str, target: date):
    tag = f"horse-cache-{target:%Y%m%d}"
    title = f"馬データキャッシュ {target:%Y-%m-%d}"
    notes = (f"自宅IPでローカル取得した {target:%Y-%m-%d} 出走全頭の過去成績キャッシュ。"
             f"auto_post ジョブが download して使用。生成: {datetime.now():%Y-%m-%d %H:%M}")
    # 既存リリースがあれば資産を上書き、なければ新規作成
    exists = subprocess.run(["gh", "release", "view", tag, "--repo", REPO],
                            capture_output=True, text=True).returncode == 0
    if exists:
        _log(f"既存リリース {tag} に資産を上書きアップロード")
        cmd = ["gh", "release", "upload", tag, zip_path, "--repo", REPO, "--clobber"]
    else:
        _log(f"新規リリース {tag} を作成しアップロード")
        cmd = ["gh", "release", "create", tag, zip_path, "--repo", REPO,
               "--title", title, "--notes", notes]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        _log(f"[ERROR] gh release 失敗: {r.stderr.strip()}")
        raise SystemExit(1)
    _log(f"アップロード完了: {tag}")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "tomorrow"
    target = _resolve_target(arg)
    _log(f"=== ローカル事前取得 開始: target={target} (arg={arg}) ===")
    t0 = time.time()

    horse_ids = collect_horse_ids(target)
    if not horse_ids:
        _log("対象馬なし。終了。")
        return
    ok, ng = fetch_all(horse_ids)
    _log(f"取得完了: 成功 {ok}頭 / 失敗 {ng}頭 / 経過 {int(time.time()-t0)}秒")
    if ok == 0:
        _log("[ERROR] 1頭も取得できませんでした。自宅IPもブロックされた可能性。中止。")
        raise SystemExit(1)

    zip_path = build_zip(horse_ids, target)
    upload_release(zip_path, target)
    _log(f"=== 完了: target={target} 総経過 {int(time.time()-t0)}秒 ===")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
