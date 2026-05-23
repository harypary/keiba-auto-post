"""
超ミニマル投稿スクリプト。
分析なし・履歴なし、出馬表だけで note 記事を生成して即投稿。
全レース投稿を最優先する非常用。
"""
import os, sys, time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.scraper.jra_scraper import JRAScraper
from src.scraper.netkeiba_scraper import NetkeibaScraper
from src.publisher.note_publisher import NotePublisher
from src.publisher.article_log import load_log, title_to_race_key, record_post


def build_minimal_note(race, odds_map):
    date_str = race.race_date if hasattr(race, 'race_date') else ""
    if date_str and len(date_str) == 8:
        date_str = f"{date_str[4:6]}/{date_str[6:8]}"
    title = f"【{date_str}】{race.venue}{race.race_no}R｜{race.race_name}｜本命予想"

    # オッズの低い順でランキング
    horses = list(race.horses)
    horses.sort(key=lambda h: odds_map.get(h.horse_no, 999.9))
    ranks = horses[:5]
    body = f"""## {race.race_name}

**{race.venue}競馬場　第{race.race_no}レース**

- 距離: {getattr(race, 'surface', '?')}{getattr(race, 'distance', '?')}m
- 馬場: {getattr(race, 'condition', '?')}
- 頭数: {race.num_horses}頭

## 印 (オッズベース速報版)

| 印 | 馬番 | 馬名 | 単勝オッズ |
|---|---|---|---|
"""
    marks = ["◎", "○", "▲", "△", "△"]
    for mk, h in zip(marks, ranks):
        o = odds_map.get(h.horse_no, 0)
        body += f"| {mk} | {h.horse_no} | {h.horse_name} | {o:.1f}倍 |\n"
    body += "\n## 投稿時注記\n\n本記事はオッズ速報ベースの簡易予想です。詳細データ分析は来週から再開予定。\n"
    return {"title": title, "body": body, "tags": ["競馬", "予想", race.venue], "price": 100}


def main():
    target_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if not target_arg:
        # 翌日
        target = date.today() + timedelta(days=1)
    else:
        target = datetime.strptime(target_arg, "%Y-%m-%d").date()

    print(f"[quick_post] 対象日: {target}")

    jra = JRAScraper()
    netkeiba = NetkeibaScraper()
    publisher = NotePublisher()

    races = jra.get_race_list_for_date(target)
    if not races:
        print("レースなし")
        return
    print(f"全 {len(races)} レース")

    log_data = load_log()
    existing_keys = set(log_data.get("by_race_key", {}).keys())

    ok, ng = 0, 0
    for i, raw in enumerate(races):
        race_id = raw["race_id"]
        print(f"\n[{i+1}/{len(races)}] {race_id}")
        try:
            race = jra.get_shutuba_table(race_id)
            if not race or not race.horses:
                print("  出馬表取得失敗、スキップ")
                continue
            odds_map = {}
            try:
                odds_map = netkeiba.get_odds(race_id) or {}
            except Exception:
                pass
            for e in race.horses:
                e.odds = odds_map.get(e.horse_no, 0)

            note = build_minimal_note(race, odds_map)
            key = title_to_race_key(note["title"])
            if key in existing_keys:
                print(f"  既投稿: {note['title'][:50]}")
                continue

            print(f"  投稿: {note['title'][:50]}")
            result = publisher.create_paid_article(
                title=note["title"], body=note["body"],
                tags=note["tags"], price=note["price"],
            )
            if isinstance(result, dict) and result.get("draft"):
                ng += 1
                print(f"  → 下書きで止まった")
            elif result:
                ok += 1
                url = result if isinstance(result, str) else result.get("url", "")
                note_id = ""
                if isinstance(result, dict):
                    note_id = result.get("note_id", "")
                else:
                    import re
                    mm = re.search(r"/n/(n[a-f0-9]+)", str(result))
                    if mm: note_id = mm.group(1)
                try:
                    record_post(note["title"], race_id, note_id, url, verified=True)
                except Exception:
                    pass
                existing_keys.add(key)
                print(f"  ✓ {url}")
            else:
                ng += 1
                print(f"  → 結果None")
            time.sleep(2)
        except Exception as ex:
            ng += 1
            print(f"  例外: {ex}")
            import traceback; traceback.print_exc()
            continue

    print(f"\n[quick_post] 完了 / 成功 {ok} / 失敗 {ng}")


if __name__ == "__main__":
    main()
