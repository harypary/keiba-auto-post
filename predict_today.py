"""今日の全レース予想（投稿しない、結果テキストのみ出力）"""
import sys, os, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
from src.scraper.jra_scraper import JRAScraper
from src.scraper.history_scraper import HistoryScraper
from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
from src.analyzer.race_context import analyze_race_context
from src.analyzer.recommendation import build_betting_plan_from_comprehensive
from src.pipeline import _cached_history

def main():
    target = date(2026, 5, 9)
    jra = JRAScraper()
    hist = HistoryScraper()
    analyzer = ComprehensiveAnalyzer()

    races = jra.get_race_list_for_date(target)
    out = []
    for r in races:
        race_id = r["race_id"]
        race = jra.get_shutuba_table(race_id)
        if not race or not race.horses:
            continue
        histories = {}
        for entry in race.horses:
            if entry.horse_id:
                h = _cached_history(hist, entry.horse_id, entry.horse_name)
                if h and h.records:
                    histories[entry.horse_id] = h
        ctx = analyze_race_context(race.horses, histories, race.distance, race.surface)
        scores = analyzer.analyze_all(
            entries=race.horses, histories=histories,
            race=race, context=ctx, use_training=False,
        )
        plan = build_betting_plan_from_comprehensive(race_id, race.race_name, scores, race.num_horses)

        def name_of(no):
            for s in scores:
                if s.horse_no == no: return s.horse_name
            return str(no)

        ranked = sorted(scores, key=lambda x: x.recommendation_rank)[:6]
        line = {
            "venue": race.venue, "no": race.race_no, "name": race.race_name,
            "surface": race.surface, "dist": race.distance, "n": race.num_horses,
            "grade": race.grade, "pace": getattr(ctx, "pace_prediction", "-"),
            "honmei": [(n, name_of(n)) for n in plan.honmei],
            "taikou": [(n, name_of(n)) for n in plan.taikou],
            "tanana": [(n, name_of(n)) for n in plan.tanana],
            "renka":  [(n, name_of(n)) for n in plan.renka],
            "value": (plan.value_horse, name_of(plan.value_horse)) if plan.value_horse else None,
            "top6": [(s.horse_no, s.horse_name, round(getattr(s, "final_score", 0),1)) for s in ranked],
        }
        out.append(line)
        print(f"[OK] {race.venue}{race.race_no}R {race.race_name}")

    with open("today_predictions.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSAVED: {len(out)} races")

if __name__ == "__main__":
    main()
