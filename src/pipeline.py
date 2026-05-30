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


def _interleave_races(race_ids: list) -> list:
    """会場順に並んだレース一覧を「メイン優先＋会場ラウンドロビン」に並べ替える。
    途中終了しても各会場が満遍なく投稿されるようにするための処置。
    race_id 形式: YYYY + 会場(2) + 開催(2) + 日(2) + R番号(2)
    """
    from collections import OrderedDict
    by_venue = OrderedDict()
    for r in race_ids:
        rid = r.get("race_id", "")
        venue = rid[4:6] if len(rid) >= 6 else "00"
        try:
            rno = int(rid[-2:])
        except Exception:
            rno = 0
        r["_rno"] = rno
        by_venue.setdefault(venue, []).append(r)
    for lst in by_venue.values():
        lst.sort(key=lambda x: x.get("_rno", 0))

    # 1) 各会場のメイン（11R）を先頭に（看板の有料記事を確実に出す）
    mains, rest_by_venue = [], OrderedDict()
    for venue, lst in by_venue.items():
        for r in lst:
            if r.get("_rno") == 11:
                mains.append(r)
            else:
                rest_by_venue.setdefault(venue, []).append(r)

    # 2) 残りを会場ラウンドロビン（1R→各会場、2R→各会場…の順で交互に）
    ordered = list(mains)
    queues = [iter(lst) for lst in rest_by_venue.values()]
    while queues:
        nxt = []
        for q in queues:
            try:
                ordered.append(next(q))
                nxt.append(q)
            except StopIteration:
                pass
        queues = nxt
    return ordered


def _fetch_live_published_keys(target_date: date) -> set:
    """note.com の公開済み記事を全ページ走査し、本日(target_date)分の race_key 集合を返す。
    HTML の先頭だけを見る簡易スキャンと違い、API をページングして「実際に公開されている」
    レースを漏れなく把握する。これを“真実の情報源”として重複判定する。
    """
    import requests as _req
    from src.publisher.article_log import title_to_race_key
    md_variants = {
        f"{target_date.month:02d}/{target_date.day:02d}",  # 05/30
        f"{target_date.month}/{target_date.day}",          # 5/30
    }
    live_all = set()
    live_today = set()
    try:
        for page in range(1, 25):  # 最大24ページ（=最大480記事）まで
            url = (f"https://note.com/api/v2/creators/_almanddd/contents"
                   f"?kind=note&page={page}")
            r = _req.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
            if r.status_code != 200:
                break
            data = r.json()
            contents = (data.get("data", {}) or {}).get("contents", []) or []
            if not contents:
                break
            for c in contents:
                if c.get("status") != "published":
                    continue
                name = c.get("name", "")
                key = title_to_race_key(name)
                live_all.add(key)
                if any(name.find(f"【{v}") >= 0 or key.startswith(f"{v}_") for v in md_variants):
                    live_today.add(key)
            if (data.get("data", {}) or {}).get("isLastPage", False):
                break
    except Exception as ex:
        print(f"  [warn] note.com 公開記事の全走査に失敗（簡易スキャンにフォールバック）: {ex}")
        return None  # None = 走査失敗。呼び出し側でローカルログを信頼する
    return {"all": live_all, "today": live_today}


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
    # 途中で時間切れになっても全会場が満遍なく投稿されるよう、会場を交互に並べ替える。
    # （会場順のままだと cutoff 時に後ろの会場が丸ごと未投稿になる事象を防ぐ）
    race_ids = _interleave_races(race_ids)
    print(f"  -> {len(race_ids)}レース（未勝利〜G1 全対応・会場交互 / メイン優先）")

    # 2. 各レース完全分析（解析しながら即時投稿）
    print("[2/4] 全レース分析開始（解析→即投稿）...")
    race_results = []
    published = []
    failed_notes = []

    # === 重複防止: 既存記事スキャン（投稿前に1度だけ）===
    existing_titles = set()
    existing_keys = set()
    from src.publisher.article_log import (
        load_log as load_article_log, title_to_race_key,
        record_post as record_article,
    )
    log = load_article_log()

    # 本日分の race_key を算出（ローカルログの今日のエントリを切り分けるため）
    _md_variants = {
        f"{target_date.month:02d}/{target_date.day:02d}",
        f"{target_date.month}/{target_date.day}",
    }
    def _is_today_key(k: str) -> bool:
        return any(k.startswith(f"{v}_") for v in _md_variants)

    # まず note.com の“実際に公開済み”を全ページ走査（真実の情報源）
    live = _fetch_live_published_keys(target_date) if publish else None

    if live is not None:
        # === ライブ走査成功: 公開済み実体を最優先で信頼する ===
        # ・本日分: note.com に「公開済み」で存在するものだけを重複扱い
        #   → ログに残っているが実際は未公開のレース（例: 前runが記録だけして失敗）は
        #     重複とみなさず“再投稿”できる。これがユーザー要望「全部投稿される」の肝。
        # ・過去日分: 深掘り走査しないのでローカルログ（verified）で保護
        existing_keys.update(live["all"])
        for k, v in log.get("by_race_key", {}).items():
            if _is_today_key(k):
                continue  # 本日分はライブ状態のみを信頼（ログは無視）
            existing_keys.add(k)  # 過去日分はログで二重投稿防止
        print(f"  note.com公開済み(全走査): 全{len(live['all'])}件 / 本日{len(live['today'])}件")
        print(f"  重複判定キー: {len(existing_keys)}件（本日はライブ状態が真実）")
    else:
        # === ライブ走査失敗: 安全側に倒してローカルログ＋簡易スキャンを信頼 ===
        existing_keys.update(log.get("by_race_key", {}).keys())
        print(f"  [fallback] ローカル投稿ログ: {len(existing_keys)}件をロード")
        if publish:
            try:
                import requests as _req
                for u in [f"https://note.com/_almanddd?status=published", f"https://note.com/_almanddd"]:
                    r = _req.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    if r.status_code == 200:
                        import re as _re
                        for m in _re.finditer(r'"name":"([^"]{8,120})"', r.text):
                            existing_titles.add(m.group(1))
                            existing_keys.add(title_to_race_key(m.group(1)))
            except Exception as ex:
                print(f"  [warn] 既存記事スキャン失敗: {ex}")
            print(f"  既存記事タイトル: {len(existing_titles)}件")

    def _is_dup(t):
        return title_to_race_key(t) in existing_keys or t in existing_titles

    def _is_main(item):
        race = item["race"]
        if race.grade in ("G1", "G2", "G3", "OP"):
            return True
        if race.race_no == 11:
            return True
        return False

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

            item = {"race": race, "scores": scores, "plan": plan, "context": ctx}
            race_results.append(item)

            # === 解析直後に即投稿（バッチ投稿だと最後まで何も公開されない問題を解消）===
            if main_only and not _is_main(item):
                pass   # main_only モードで非メインはスキップ
            else:
                try:
                    note = format_race_note_v2(
                        race=race, scores=scores, plan=plan, context=ctx,
                        target_date=target_date, race_index=idx,
                    )
                    note["_race_id"] = race_id
                    if publish:
                        # 最終重複チェック: 投稿直前に note.com を再スキャン
                        try:
                            import requests as _req2
                            _r = _req2.get(f"https://note.com/_almanddd", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                            if _r.status_code == 200:
                                import re as _re2
                                for _m in _re2.finditer(r'"name":"([^"]{8,120})"', _r.text):
                                    existing_titles.add(_m.group(1))
                                    existing_keys.add(title_to_race_key(_m.group(1)))
                        except Exception:
                            pass

                        if _is_dup(note["title"]):
                            print(f"  [SKIP重複] {note['title'][:50]}")
                        else:
                            try:
                                result = publisher.create_paid_article(
                                    title=note["title"], body=note["body"],
                                    tags=note["tags"], price=note["price"],
                                )
                                if isinstance(result, dict) and result.get("draft"):
                                    failed_notes.append(note)
                                    existing_keys.add(title_to_race_key(note["title"]))
                                    print(f"  [DRAFT] {note['title'][:50]}")
                                elif result:
                                    published.append(result)
                                    url = result if isinstance(result, str) else result.get("url", "")
                                    note_id = ""
                                    if isinstance(result, dict):
                                        note_id = result.get("note_id", "")
                                    else:
                                        import re as _re
                                        mm = _re.search(r"/n/(n[a-f0-9]+)", str(result))
                                        if mm: note_id = mm.group(1)
                                    try:
                                        record_article(note["title"], race_id, note_id, url, verified=True)
                                    except Exception:
                                        pass
                                    existing_keys.add(title_to_race_key(note["title"]))
                                    print(f"  [PUBLISHED] {note['title'][:50]} → {url[:60]}")
                                else:
                                    failed_notes.append(note)
                            except Exception as ex2:
                                failed_notes.append(note)
                                print(f"  [EXCEPTION投稿] {ex2}")
                            time.sleep(2)
                    else:
                        if save_files:
                            try:
                                publisher.save_to_file(note, OUTPUT_DIR)
                            except Exception:
                                pass
                except Exception as ex:
                    print(f"  [warn] 記事生成失敗: {ex}")

            time.sleep(1)
        except Exception as ex:
            print(f"  [ERROR] レース{race_id} 処理中に例外（次レースへ）: {ex}")
            import traceback
            traceback.print_exc()
            continue

    if not race_results:
        print("[WARN] 有効レースなし")
        return []

    print(f"\n{'='*60}")
    print(f"[DONE] {len(published)}件公開 / {len(race_results)}件分析 / 失敗{len(failed_notes)}件")
    if published:
        for p in published[:3]:
            url = p if isinstance(p, str) else p.get('url', '')
            print(f"  URL: {url}")
    print(f"{'='*60}\n")
    return published


# ============================================================
# キャッシュ管理（3日間キャッシュ＋毎週月曜自動クリア）
# ============================================================

def _cached_history(scraper: HistoryScraper, horse_id: str, horse_name: str):
    """馬の過去成績を取得。SCRAPE_MODE=fast で CI 高速化、未設定/full は本格分析"""
    cache_file = os.path.join(CACHE_DIR, f"{horse_id}_full.json")
    os.makedirs(CACHE_DIR, exist_ok=True)
    # 既定は本格分析。SCRAPE_MODE=fast の場合のみ高速モード
    scrape_mode = os.environ.get("SCRAPE_MODE", "full").lower()
    is_ci = (scrape_mode == "fast")

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

    # 投稿用 playwright と競合する馬データ playwright_fetcher は本処理では使わない
    # (DISABLE_PLAYWRIGHT_FETCH=1 を base_scraper が読む)
    # fast モード or ブロック確定 + キャッシュ無し → 即 None で投稿優先
    try:
        from src.scraper.base_scraper import is_netkeiba_blocked
        if (is_ci or is_netkeiba_blocked()) and not cached:
            return None
    except Exception:
        pass

    # 取得を試行（キャッシュあれば1回だけ、なければ2回）
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
