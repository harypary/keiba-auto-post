"""
指定日のレース全頭の馬個別ページを事前取得してキャッシュ化。
macOS runner で実行（Ubuntu と異なる IP 帯で netkeiba 突破を狙う）。
"""
import sys, os
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scraper.jra_scraper import JRAScraper
from src.scraper.history_scraper import HistoryScraper
from src.pipeline import _cached_history


def main():
    target_str = sys.argv[1] if len(sys.argv) > 1 else None
    if not target_str:
        print("usage: prefetch_horse_cache.py YYYY-MM-DD")
        sys.exit(1)
    target = datetime.strptime(target_str, "%Y-%m-%d").date()

    jra = JRAScraper()
    hist = HistoryScraper()
    races = jra.get_race_list_for_date(target)
    if not races:
        print(f"[prefetch] {target} レースなし")
        return
    print(f"[prefetch] {target} {len(races)}レース取得開始")

    all_horse_ids = []
    seen = set()
    for raw in races:
        race_id = raw["race_id"]
        try:
            race = jra.get_shutuba_table(race_id)
        except Exception as ex:
            print(f"  [warn] {race_id} 出馬表失敗: {ex}")
            continue
        if not race or not race.horses:
            continue
        for e in race.horses:
            if e.horse_id and e.horse_id not in seen:
                seen.add(e.horse_id)
                all_horse_ids.append((e.horse_id, e.horse_name or "?"))
    print(f"[prefetch] 対象馬 {len(all_horse_ids)}頭、事前キャッシュ取得開始")

    ok, ng = 0, 0
    for i, (hid, name) in enumerate(all_horse_ids):
        try:
            h = _cached_history(hist, hid, name)
            if h and h.records:
                ok += 1
                if i % 10 == 0:
                    print(f"  [{i+1}/{len(all_horse_ids)}] {name} {len(h.records)}走 ✓")
            else:
                ng += 1
                if i % 10 == 0:
                    print(f"  [{i+1}/{len(all_horse_ids)}] {name} ✗")
        except Exception as ex:
            ng += 1
            print(f"  [{i+1}/{len(all_horse_ids)}] {name} 例外: {ex}")

    print(f"\n[prefetch] 完了: 成功 {ok}頭 / 失敗 {ng}頭")


if __name__ == "__main__":
    main()
