"""失敗した記事を新規作成→直ちに公開フローで再作成"""
import sys, os, json, time, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import date
from playwright.sync_api import sync_playwright

# 失敗記事の (note_id, title)
FAILED = json.load(open("data/failed_titles.json", encoding="utf-8"))

# 競馬場と race_no を title から推定
def parse_title(title: str):
    # パック（個別レース予想パック）は廃止
    if "全12R" in title or "予想パック" in title:
        return None
    # 一般レース 【05/16】場所NR｜
    m = re.search(r"【\d+/\d+】([東京京都新潟中山阪神中京福島小倉札幌函館]+)(\d+)R", title)
    if m:
        return (m.group(1), int(m.group(2)), None)
    # メインレース 【05/16】レース名｜本命公開
    m2 = re.search(r"【\d+/\d+】(.+?)｜", title)
    if m2:
        name = m2.group(1).replace("メインレース ", "").strip()
        return (None, None, name)
    return None

# 削除→再作成フロー
state = json.load(open("data/note_session.json", encoding="utf-8"))


def delete_drafts(page, ids):
    """note の API で下書きを削除"""
    deleted = 0
    for nid in ids:
        try:
            # 削除APIをPlaywright経由で叩く
            url = f"https://editor.note.com/notes/{nid}/edit"
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            # 削除ボタンを探す（編集画面の上部メニュー）
            # 「下書きを削除」など
            for sel in ['button:has-text("下書きを削除")', 'button:has-text("削除")', '[aria-label*="削除"]']:
                try:
                    btns = page.locator(sel).all()
                    if btns:
                        btns[0].click(timeout=3000, force=True)
                        time.sleep(2)
                        # 確認ダイアログ
                        for c in page.locator('button:has-text("削除")').all():
                            try:
                                if c.is_visible():
                                    c.click(timeout=2000, force=True)
                                    break
                            except: pass
                        time.sleep(3)
                        deleted += 1
                        print(f"  deleted: {nid}")
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"  delete fail {nid}: {e}")
    return deleted


# 削除 → 個別レース再作成
def main():
    # 個別レース対象
    targets = []
    for nid, title in FAILED.items():
        info = parse_title(title)
        if info is None:
            print(f"[skip] {nid}: {title} (pack)")
            continue
        targets.append((nid, title, info))
    print(f"再作成対象: {len(targets)}件")

    from src.scraper.jra_scraper import JRAScraper
    from src.scraper.history_scraper import HistoryScraper
    from src.analyzer.comprehensive_score import ComprehensiveAnalyzer
    from src.analyzer.race_context import analyze_race_context
    from src.analyzer.recommendation import build_betting_plan_from_comprehensive
    from src.content.note_formatter import format_race_note_v2
    from src.pipeline import _cached_history
    from src.publisher.note_publisher import NotePublisher

    target_date = date(2026, 5, 16)
    jra = JRAScraper()
    hist = HistoryScraper()
    analyzer = ComprehensiveAnalyzer()

    races = jra.get_race_list_for_date(target_date)
    info_by_key = {}
    info_by_name = {}
    for r in races:
        ri = jra.get_shutuba_table(r["race_id"])
        if not ri: continue
        key = (ri.venue, ri.race_no)
        info_by_key[key] = (r["race_id"], ri)
        info_by_name[ri.race_name] = (r["race_id"], ri)

    publisher = NotePublisher()
    success = 0
    for nid, title, info in targets:
        venue, race_no, race_name = info
        # 一致するレース
        race_id = None
        race_info = None
        if venue and race_no and (venue, race_no) in info_by_key:
            race_id, race_info = info_by_key[(venue, race_no)]
        elif race_name and race_name in info_by_name:
            race_id, race_info = info_by_name[race_name]
        else:
            # 部分一致
            for n, (rid, ri) in info_by_name.items():
                if race_name and (race_name in n or n in race_name):
                    race_id, race_info = rid, ri
                    break
        if not race_id:
            print(f"[NOT FOUND] {title}")
            continue
        print(f"[PROC] {race_info.venue}{race_info.race_no}R {race_info.race_name}")

        # 履歴+スコアリング
        histories = {}
        for e in race_info.horses:
            if e.horse_id:
                try:
                    h = _cached_history(hist, e.horse_id, e.horse_name)
                    if h and h.records:
                        histories[e.horse_id] = h
                except: pass
        try:
            ctx = analyze_race_context(race_info.horses, histories, race_info.distance, race_info.surface)
            scores = analyzer.analyze_all(entries=race_info.horses, histories=histories, race=race_info, context=ctx, use_training=False)
            plan = build_betting_plan_from_comprehensive(race_id, race_info.race_name, scores, race_info.num_horses)
            note = format_race_note_v2(race_info, scores, plan, ctx, target_date, 0)
        except Exception as e:
            print(f"  scoring fail: {e}")
            continue

        # 公開投稿
        try:
            r = publisher.create_paid_article(
                title=note["title"], body=note["body"],
                tags=note["tags"][:5], price=note["price"],
                draft_only=False,
            )
            if r and r.get("url"):
                print(f"  → 公開URL: {r['url']}")
                success += 1
            else:
                print(f"  → 結果None")
        except Exception as e:
            print(f"  publish fail: {e}")
        time.sleep(5)

    print(f"\n完了: {success}/{len(targets)}")


if __name__ == "__main__":
    main()
