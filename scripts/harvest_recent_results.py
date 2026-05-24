"""
直近のレース結果から出走馬データを取得してキャッシュ拡充。
- 過去1週間のレース結果ページを取得
- 各レースの出走馬IDを抽出
- 未キャッシュの馬のみ history を取得（次週予測に備える）
"""
import os, sys, time
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.scraper.jra_scraper import JRAScraper
from src.scraper.history_scraper import HistoryScraper
from src.pipeline import _cached_history

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")


def already_cached(horse_id: str) -> bool:
    p = os.path.join(CACHE_DIR, f"{horse_id}_full.json")
    if not os.path.exists(p): return False
    age = time.time() - os.path.getmtime(p)
    return age < 86400 * 14   # 14日以内なら新鮮扱い


def main():
    today = date.today()
    jra = JRAScraper()
    hist = HistoryScraper()

    horse_ids = set()
    # 過去7日 + 翌週末分のレースをスキャン
    for delta in range(-7, 8):
        d = today + timedelta(days=delta)
        try:
            races = jra.get_race_list_for_date(d)
        except Exception as e:
            print(f"  {d} レース一覧失敗: {e}")
            continue
        if not races:
            continue
        print(f"  {d}: {len(races)} レース")
        for raw in races[:36]:
            try:
                race = jra.get_shutuba_table(raw["race_id"])
                if not race or not race.horses: continue
                for h in race.horses:
                    if h.horse_id:
                        horse_ids.add((h.horse_id, h.horse_name or "?"))
            except Exception:
                continue

    print(f"\n対象馬合計: {len(horse_ids)}頭")
    uncached = [(hid, hn) for hid, hn in horse_ids if not already_cached(hid)]
    print(f"うち未キャッシュ: {len(uncached)}頭、取得開始")

    ok, ng = 0, 0
    for i, (hid, hn) in enumerate(uncached):
        try:
            h = _cached_history(hist, hid, hn)
            if h and h.records:
                ok += 1
            else:
                ng += 1
        except Exception:
            ng += 1
        if (i+1) % 20 == 0:
            print(f"  [{i+1}/{len(uncached)}] OK={ok} NG={ng}")
        time.sleep(0.5)

    print(f"\n[完了] 取得成功 {ok} / 失敗 {ng}")


if __name__ == "__main__":
    main()
