"""
メインパイプライン（完全統計版）
中央競馬の全レース（未勝利〜G1まで）を完全分析してnoteに自動投稿
"""
import time
import json
import os
import sys
import io
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# プロセス優先度を低に設定（PC負荷軽減）
try:
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
except Exception:
    pass

from src.scraper.jra_scraper import JRAScraper
from src.scraper.netkeiba_scraper import NetkeibaScraper
from src.scraper.history_scraper import HistoryScraper, build_stats
from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
from src.analyzer.race_context import analyze_race_context
from src.analyzer.recommendation import build_betting_plan_from_comprehensive
from src.content.note_formatter import format_race_note_v2, format_day_summary_note
from src.publisher.note_publisher import NotePublisher
from src.validator.performance_tracker import save_prediction, get_track_record_text
from config.settings import OUTPUT_DIR, CACHE_DIR


def run_pipeline(target_date: date, publish: bool = True, save_files: bool = True):
    """
    中央競馬全レースの完全分析 → note.com自動投稿
    未勝利〜G1まで全レース対応
    """
    print(f"\n{'='*60}")
    print(f"[START] {target_date} 全レース完全分析パイプライン")
    print(f"{'='*60}\n")

    jra         = JRAScraper()
    netkeiba    = NetkeibaScraper()
    hist_scraper= HistoryScraper()
    analyzer    = ComprehensiveAnalyzer()
    publisher   = NotePublisher()

    # 1. レース一覧（全会場・全クラス）
    print("[1/4] 全レース一覧取得...")
    race_ids = jra.get_race_list_for_date(target_date)
    if not race_ids:
        print(f"[WARN] {target_date} レース情報なし（開催なし or 取得失敗）")
        return []
    print(f"  -> {len(race_ids)}レース（未勝利〜G1 全対応）")

    # 2. 各レース完全分析
    print("[2/4] 全レース分析開始...")
    race_results = []

    for idx, raw in enumerate(race_ids):
        race_id = raw["race_id"]
        print(f"\n  [{idx+1}/{len(race_ids)}] {race_id}")

        race = jra.get_shutuba_table(race_id)
        if not race or not race.horses:
            print("  [SKIP] 出馬表取得失敗")
            continue
        print(f"  -> {race.venue}{race.race_no}R {race.race_name} ({race.num_horses}頭/{race.grade})")

        # オッズ取得
        odds_map = netkeiba.get_odds(race_id)
        for entry in race.horses:
            entry.odds = odds_map.get(entry.horse_no)

        # 全出走馬の全過去レース取得 + 統計構築
        histories = {}
        for entry in race.horses:
            if entry.horse_id:
                h = _cached_history(hist_scraper, entry.horse_id, entry.horse_name)
                if h and h.records:
                    histories[entry.horse_id] = h

        # 展開予測（脚質×先行馬数）
        ctx = analyze_race_context(race.horses, histories, race.distance, race.surface)

        # 総合スコアリング（全指標統合）
        scores = analyzer.analyze_all(
            entries=race.horses,
            histories=histories,
            race=race,
            context=ctx,
            use_training=False,
        )

        plan = build_betting_plan_from_comprehensive(
            race_id, race.race_name, scores, race.num_horses
        )
        save_prediction(race_id, race.race_name, scores, plan)
        race_results.append({"race": race, "scores": scores, "plan": plan, "context": ctx})
        time.sleep(1)   # レース間インターバル（CPU冷却）

    if not race_results:
        print("[WARN] 有効レースなし")
        return []

    # 3. note記事生成（全レース個別 + 全レースパック）
    print(f"\n[3/4] note記事生成 ({len(race_results)}レース)...")
    weekday   = target_date.weekday()
    venue_day = "日曜" if weekday == 6 else "土曜"

    notes = []
    for i, item in enumerate(race_results):
        note = format_race_note_v2(
            race=item["race"], scores=item["scores"],
            plan=item["plan"], context=item["context"],
            target_date=target_date, race_index=i,
        )
        notes.append(note)
        print(f"  [OK] {note['title'][:55]}...")

    # 全レースパック（割安セット価格）
    day_pack = format_day_summary_note(race_results, target_date, venue_day)
    notes.append(day_pack)
    print(f"  [OK] パック: {day_pack['title'][:55]}...")

    # 4. 投稿 / 保存
    print(f"\n[4/4] {'note.com投稿' if publish else 'ファイル保存のみ'}...")
    published = []
    for note in notes:
        if save_files:
            publisher.save_to_file(note, OUTPUT_DIR)
        if publish:
            result = publisher.create_paid_article(
                title=note["title"], body=note["body"],
                tags=note["tags"], price=note["price"],
            )
            if result:
                published.append(result)
            time.sleep(3)   # 連続投稿防止

    print(f"\n{'='*60}")
    print(f"[DONE] {len(published)}件投稿 / {len(notes)}件生成")
    if published:
        for p in published[:3]:
            print(f"  URL: {p.get('url', '')}")
    print(f"{'='*60}\n")
    return published


# ============================================================
# キャッシュ管理（3日間キャッシュ＋毎週月曜自動クリア）
# ============================================================

def _cached_history(scraper: HistoryScraper, horse_id: str, horse_name: str):
    cache_file = os.path.join(CACHE_DIR, f"{horse_id}_full.json")
    os.makedirs(CACHE_DIR, exist_ok=True)

    # 7日以内のキャッシュを使用（週次更新で十分）
    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < 86400 * 7:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                from src.scraper.history_scraper import FullHorseHistory, RaceRecord
                recs = [RaceRecord(**r) for r in data.get("records", [])]
                h = FullHorseHistory(
                    horse_id=data["horse_id"],
                    horse_name=data.get("horse_name", horse_name),
                    sire=data.get("sire", ""),
                    dam=data.get("dam", ""),
                    sex=data.get("sex", "牡"),
                    records=recs,
                )
                h.stats = build_stats(h)
                return h
            except Exception:
                pass   # キャッシュ破損は再取得

    h = scraper.get_full_history(horse_id)
    if h:
        try:
            from dataclasses import asdict
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(asdict(h), f, ensure_ascii=False)
        except Exception:
            pass
    return h


def invalidate_cache(horse_id: str = None):
    """キャッシュクリア（毎週月曜朝に自動実行）"""
    if horse_id:
        cf = os.path.join(CACHE_DIR, f"{horse_id}_full.json")
        if os.path.exists(cf):
            os.remove(cf)
    else:
        count = 0
        for f in os.listdir(CACHE_DIR):
            if f.endswith("_full.json"):
                os.remove(os.path.join(CACHE_DIR, f))
                count += 1
        print(f"[cache] {count}件クリア完了")
