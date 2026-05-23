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


def run_pipeline(target_date: date, publish: bool = True, save_files: bool = True, main_only: bool = False):
    """
    中央競馬全レースの完全分析 → note.com自動投稿
    main_only=True: 投稿は重賞・OP特別・メインレース（11R）のみ。他は予測のみ実施し学習に使う。
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

        # 各レースは独立して try でくくる（1レース失敗で全体停止しない）
        try:
            race = jra.get_shutuba_table(race_id)
            if not race or not race.horses:
                print("  [SKIP] 出馬表取得失敗")
                continue
            print(f"  -> {race.venue}{race.race_no}R {race.race_name} ({race.num_horses}頭/{race.grade})")

            # オッズ取得（失敗しても続行）
            try:
                odds_map = netkeiba.get_odds(race_id)
                for entry in race.horses:
                    entry.odds = odds_map.get(entry.horse_no)
            except Exception as ex:
                print(f"  [warn] オッズ取得失敗（続行）: {ex}")

            # 全出走馬の過去レース取得（個別失敗を許容）
            from src.scraper.base_scraper import is_netkeiba_blocked
            histories = {}
            if is_netkeiba_blocked():
                for e in race.horses:
                    if not e.horse_id: continue
                    try:
                        h = _cached_history(hist_scraper, e.horse_id, e.horse_name)
                        if h and h.records:
                            histories[e.horse_id] = h
                    except Exception as ex:
                        print(f"  [warn] {e.horse_name} 履歴取得失敗（続行）: {ex}")
            else:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                def _fetch_one(e):
                    try:
                        if e.horse_id:
                            return e.horse_id, _cached_history(hist_scraper, e.horse_id, e.horse_name)
                    except Exception:
                        pass
                    return None, None
                with ThreadPoolExecutor(max_workers=4) as ex:
                    futures = [ex.submit(_fetch_one, e) for e in race.horses if e.horse_id]
                    for f in as_completed(futures):
                        try:
                            hid, h = f.result()
                            if hid and h and h.records:
                                histories[hid] = h
                        except Exception:
                            pass

            # 展開予測（失敗時はデフォルト）
            try:
                ctx = analyze_race_context(race.horses, histories, race.distance, race.surface)
            except Exception as ex:
                print(f"  [warn] 展開予測失敗（デフォルト使用）: {ex}")
                from src.analyzer.race_context import RaceContext
                ctx = RaceContext()

            # 総合スコアリング（失敗時もデフォルトスコアで進める）
            try:
                scores = analyzer.analyze_all(
                    entries=race.horses,
                    histories=histories,
                    race=race,
                    context=ctx,
                    use_training=False,
                )
            except Exception as ex:
                print(f"  [warn] 総合分析失敗、ベース評価のみで継続: {ex}")
                scores = analyzer.analyze_all(
                    entries=race.horses, histories={}, race=race, context=ctx, use_training=False,
                ) if False else []   # 最低限のフォールバック
                if not scores:
                    print(f"  [SKIP] 分析完全失敗")
                    continue

            try:
                plan = build_betting_plan_from_comprehensive(
                    race_id, race.race_name, scores, race.num_horses
                )
            except Exception as ex:
                print(f"  [warn] 買い目生成失敗（空計画で続行）: {ex}")
                from src.analyzer.recommendation import BettingPlan
                plan = BettingPlan(race_id=race_id, race_name=race.race_name,
                                   honmei=[], taikou=[], tanana=[], renka=[], omakase=[],
                                   win_bets=[], place_bets=[], exacta_bets=[],
                                   quinella_bets=[], trifecta_bets=[], trio_bets=[])

            try:
                save_prediction(race_id, race.race_name, scores, plan)
            except Exception as ex:
                print(f"  [warn] 予測保存失敗（続行）: {ex}")

            race_results.append({"race": race, "scores": scores, "plan": plan, "context": ctx})
            time.sleep(1)
        except Exception as ex:
            print(f"  [ERROR] レース{race_id} 処理中に例外（次レースへ）: {ex}")
            import traceback
            traceback.print_exc()
            continue

    if not race_results:
        print("[WARN] 有効レースなし")
        return []

    # 3. note記事生成（全レース個別 + 全レースパック）
    print(f"\n[3/4] note記事生成 ({len(race_results)}レース)...")
    weekday   = target_date.weekday()
    venue_day = "日曜" if weekday == 6 else "土曜"

    # main_only モード: 投稿対象は重賞 / OP / メイン(11R)のみ。他はnote生成スキップ。
    def _is_main(item):
        race = item["race"]
        if race.grade in ("G1", "G2", "G3", "OP"):
            return True
        if race.race_no == 11:
            return True
        return False

    notes = []
    for i, item in enumerate(race_results):
        if main_only and not _is_main(item):
            continue
        try:
            note = format_race_note_v2(
                race=item["race"], scores=item["scores"],
                plan=item["plan"], context=item["context"],
                target_date=target_date, race_index=i,
            )
            note["_race_id"] = getattr(item["race"], "race_id", "")
            notes.append(note)
            print(f"  [OK] {note['title'][:55]}...")
        except Exception as ex:
            print(f"  [warn] レース{item['race'].race_id} 記事生成失敗（スキップ）: {ex}")
            import traceback
            traceback.print_exc()

    # 競馬場別パックは廃止（個別レース記事のみ投稿）

    # 4. 投稿 / 保存
    if main_only:
        skipped = len(race_results) - sum(1 for it in race_results if _is_main(it))
        print(f"  ※ メインのみモード: 投稿対象{len(notes)}件 / {skipped}レースは予測のみ（学習データ蓄積）")
    print(f"\n[4/4] {'note.com投稿' if publish else 'ファイル保存のみ'}...")
    published = []
    failed_notes = []  # 投稿失敗した記事を別途記録

    # === レース単位の重複防止: 公開済み + 下書き + 永続ログ三重チェック ===
    existing_titles = set()
    existing_keys = set()
    from src.publisher.article_log import (
        load_log as load_article_log, title_to_race_key,
        record_post as record_article, is_already_posted,
    )

    # (1) 永続ローカルログを最優先
    log = load_article_log()
    existing_keys.update(log.get("by_race_key", {}).keys())
    print(f"  ローカル投稿ログ: {len(existing_keys)}件をロード")

    if publish:
        try:
            import requests
            # (2) 公開済み記事
            r = requests.get(f"https://note.com/_almanddd?status=published",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code == 200:
                import re
                for m in re.finditer(r'"name":"([^"]{8,120})"', r.text):
                    existing_titles.add(m.group(1))
                    existing_keys.add(title_to_race_key(m.group(1)))
            # (3) 下書き含む全記事（管理ページから取得を試みる）
            #     APIアクセスは認証必要なので公開プロフィールページのみで補完
            r2 = requests.get(f"https://note.com/_almanddd",
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r2.status_code == 200:
                import re
                for m in re.finditer(r'"name":"([^"]{8,120})"', r2.text):
                    existing_titles.add(m.group(1))
                    existing_keys.add(title_to_race_key(m.group(1)))
            print(f"  既存記事タイトル: {len(existing_titles)}件 / race_key {len(existing_keys)}件")
        except Exception as ex:
            print(f"  [warn] 既存記事スキャン失敗: {ex}（ローカルログで判定）")

    def _is_duplicate(title: str) -> bool:
        """ローカルログ + リモートタイトル両方で重複判定"""
        key = title_to_race_key(title)
        if key in existing_keys:
            return True
        # タイトル完全一致もチェック
        if title in existing_titles:
            return True
        return False

    for note in notes:
        if save_files:
            try:
                publisher.save_to_file(note, OUTPUT_DIR)
            except Exception as ex:
                print(f"  [warn] ファイル保存失敗: {ex}")
        if publish:
            # 重複チェック：同レースの記事が既に存在ならスキップ
            if _is_duplicate(note["title"]):
                print(f"  [SKIP重複] {note['title'][:50]}")
                continue
            try:
                result = publisher.create_paid_article(
                    title=note["title"], body=note["body"],
                    tags=note["tags"], price=note["price"],
                )
                if result:
                    # draft フラグが付いていれば失敗扱い、それ以外は成功
                    if isinstance(result, dict) and result.get("draft"):
                        failed_notes.append(note)
                        # 下書きも一応キーを覚えておく（次のリトライrunで重複新規生成しない）
                        try:
                            existing_keys.add(title_to_race_key(note["title"]))
                        except Exception:
                            pass
                        print(f"  [DRAFT] 公開未達成: {note['title'][:50]}")
                    else:
                        published.append(result)
                        # === 永続ログに記録（race_id ベースで二重投稿を完全防止）===
                        try:
                            url = result if isinstance(result, str) else result.get("url", "")
                            note_id = ""
                            if isinstance(result, dict):
                                note_id = result.get("note_id", "")
                            elif isinstance(result, str):
                                import re
                                mm = re.search(r"/n/(n[a-f0-9]+)", result)
                                if mm: note_id = mm.group(1)
                            race_id = note.get("_race_id", "")
                            record_article(note["title"], race_id, note_id, url, verified=True)
                            existing_keys.add(title_to_race_key(note["title"]))
                        except Exception as ex:
                            print(f"  [warn] 永続ログ記録失敗: {ex}")
                else:
                    failed_notes.append(note)
                    print(f"  [FAIL] 投稿結果None: {note['title'][:50]}")
            except Exception as ex:
                failed_notes.append(note)
                print(f"  [EXCEPTION] {note['title'][:50]} - {ex}")
            time.sleep(3)   # 連続投稿防止

    print(f"\n{'='*60}")
    print(f"[DONE] {len(published)}件公開 / {len(notes)}件生成 / 失敗{len(failed_notes)}件")
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

    def _load_cache_any_age():
        """キャッシュがあれば年齢問わずロード（ネット失敗時のフォールバック用）"""
        if not os.path.exists(cache_file):
            return None
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
            return None

    # 7日以内のキャッシュは新鮮として即返す
    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < 86400 * 7:
            h = _load_cache_any_age()
            if h: return h

    # キャッシュ取得を先に
    cached = _load_cache_any_age()

    # netkeiba ブロック中で キャッシュも無い場合は即諦めて None 返却
    # （robust_fetch を全馬ごとに30秒待つと36レース完了不可能になるため）
    try:
        from src.scraper.base_scraper import is_netkeiba_blocked
        if is_netkeiba_blocked() and not cached:
            # 既に1回キャッシュ無しで取得失敗確定の馬はスキップ
            return None
    except Exception:
        pass

    # 取得を試行（ブロックされていなければ通常通り、ブロック後でもキャッシュあれば1回だけ試す）
    h = None
    max_retries = 1 if (cached or _is_blocked_safe()) else 2
    for attempt in range(max_retries):
        try:
            h = scraper.get_full_history(horse_id)
            if h and h.records:
                break
        except Exception as ex:
            print(f"  [retry {attempt+1}] {horse_name} 例外: {ex}")
        if attempt < max_retries - 1:
            import time as _t
            _t.sleep(2)

    if h:
        try:
            from dataclasses import asdict
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(asdict(h), f, ensure_ascii=False)
        except Exception:
            pass
        return h

    if cached:
        return cached
    return None


def _is_blocked_safe() -> bool:
    try:
        from src.scraper.base_scraper import is_netkeiba_blocked
        return is_netkeiba_blocked()
    except Exception:
        return False


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
