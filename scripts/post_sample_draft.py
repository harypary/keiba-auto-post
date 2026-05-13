"""先週レースのサンプル記事を新フォーマットで生成 → noteに下書き投稿"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
from src.scraper.jra_scraper import JRAScraper
from src.scraper.history_scraper import HistoryScraper
from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
from src.analyzer.race_context import analyze_race_context
from src.analyzer.recommendation import build_betting_plan_from_comprehensive
from src.content.note_formatter import format_race_note_v2
from src.pipeline import _cached_history

# 5/10 東京11R NHKマイルC を対象
target = date(2026, 5, 10)
TARGET_RACE_NO = 11
TARGET_VENUE = "東京"

print(f"[1] レース一覧取得 {target}")
jra = JRAScraper()
race_list = jra.get_race_list_for_date(target)

# 該当レースを探す
target_race_id = None
for r in race_list:
    info = jra.get_shutuba_table(r["race_id"])
    if info and info.venue == TARGET_VENUE and info.race_no == TARGET_RACE_NO:
        target_race_id = r["race_id"]
        break

if not target_race_id:
    print(f"対象レース見つからず")
    sys.exit(1)

print(f"[2] {target_race_id} 取得開始")
race = jra.get_shutuba_table(target_race_id)
print(f"  → {race.venue}{race.race_no}R {race.race_name}")

hist = HistoryScraper()
analyzer = ComprehensiveAnalyzer()

histories = {}
for e in race.horses:
    if e.horse_id:
        try:
            h = _cached_history(hist, e.horse_id, e.horse_name)
            if h and h.records:
                histories[e.horse_id] = h
        except Exception:
            pass

print(f"[3] スコアリング")
ctx = analyze_race_context(race.horses, histories, race.distance, race.surface)
scores = analyzer.analyze_all(entries=race.horses, histories=histories, race=race, context=ctx, use_training=False)
plan = build_betting_plan_from_comprehensive(target_race_id, race.race_name, scores, race.num_horses)

print(f"[4] 記事生成（新フォーマット）")
note = format_race_note_v2(race, scores, plan, ctx, target, 0)

# ファイル保存
os.makedirs("data/output/sample", exist_ok=True)
sample_path = f"data/output/sample/sample_{target.strftime('%Y%m%d')}_{race.venue}{race.race_no}.md"
with open(sample_path, "w", encoding="utf-8") as f:
    f.write(f"# {note['title']}\n\n{note['body']}")
print(f"  → 保存: {sample_path}")

print(f"\n[5] note 下書き投稿")
from src.publisher.note_publisher import NotePublisher
p = NotePublisher()
# 下書きモード: 投稿フローを途中で止める形にする（後で実装）
# 当面は通常投稿
result = p.create_paid_article(
    title=f"[サンプル] {note['title']}",
    body=note['body'],
    tags=note['tags'][:5],
    price=note['price'],
    draft_only=False,
)
print(f"\nResult: {result}")
