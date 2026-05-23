"""
馬の全過去レースを取得して統計データを構築する
netkeiba /horse/result/{id}/ から全成績取得
列順: 日付,開催,天気,R,レース名,映像,頭数,枠番,馬番,オッズ,人気,
      着順,騎手,斤量,距離,水分量,馬場,馬場指数,タイム,着差,
      タイム指数,タイム指数M,スタート指数,追走指数,上がり指数,
      通過,ペース,上り,馬体重,厩舎コメント,備考,勝ち馬,賞金
"""
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from .base_scraper import BaseScraper

NETKEIBA_DB = "https://db.netkeiba.com"


@dataclass
class RaceRecord:
    date: str
    venue: str
    weather: str
    race_name: str
    grade: str
    surface: str
    distance: int
    direction: str
    condition: str          # 馬場状態
    num_horses: int
    frame_no: int
    horse_no: int
    order: int
    popularity: int
    odds: float
    jockey: str
    weight_carry: float
    time_str: str           # タイム文字列
    time_sec: float         # タイム（秒）
    margin: str             # 着差
    time_index: float       # タイム指数
    pace_up: float          # 上り3F
    horse_weight: int
    weight_diff: int
    corner_pass: str        # 通過順位


@dataclass
class FullHorseHistory:
    horse_id: str
    horse_name: str
    sire: str
    dam: str
    sex: str
    records: list[RaceRecord] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class HistoryScraper(BaseScraper):
    def get_full_history(self, horse_id: str) -> Optional[FullHorseHistory]:
        """プロフィール+成績を取得（fast モード時はリトライ抑制）"""
        import os as _os, time as _time
        fast = _os.environ.get("SCRAPE_MODE", "full").lower() == "fast"
        max_retries = 1 if fast else 3
        # プロフィール取得
        prof_soup = None
        for attempt in range(max_retries):
            prof_soup = self.get(f"{NETKEIBA_DB}/horse/{horse_id}/")
            if prof_soup and len(str(prof_soup)) > 2000:
                break
            if attempt < max_retries - 1:
                _time.sleep(3 + attempt * 2)
        horse_name = "不明"
        prof = {}
        if prof_soup:
            name_el = prof_soup.select_one(".horse_title h1")
            if name_el:
                horse_name = name_el.get_text(strip=True)
            prof = self._parse_profile(prof_soup)
            # 性齢補完
            if not prof.get("sex"):
                text = prof_soup.get_text()
                for sx in ["牡", "牝", "セ", "騸"]:
                    if sx in text:
                        prof["sex"] = sx
                        break

        # 父馬が取れなければ血統ページから
        if not prof.get("sire"):
            ped_soup = self.get(f"{NETKEIBA_DB}/horse/ped/{horse_id}/")
            if ped_soup:
                sire = self._parse_sire_from_ped(ped_soup)
                if sire:
                    prof["sire"] = sire

        # 成績取得
        records = []
        result_soup = None
        for attempt in range(max_retries):
            result_soup = self.get(f"{NETKEIBA_DB}/horse/result/{horse_id}/")
            if result_soup and len(str(result_soup)) > 3000:
                break
            if attempt < max_retries - 1:
                _time.sleep(3 + attempt * 2)
        if result_soup:
            records = self._parse_result_table(result_soup)
            # 成績ページから馬名を取れることも
            if horse_name == "不明":
                title = result_soup.select_one("h1, title")
                if title:
                    horse_name = title.get_text(strip=True)[:30]

        # プロフィール&成績の両方失敗ならNone返却
        if not prof and not records:
            return None

        history = FullHorseHistory(
            horse_id=horse_id,
            horse_name=horse_name,
            sire=prof.get("sire", ""),
            dam=prof.get("dam", ""),
            sex=prof.get("sex", "牡"),
            records=records,
        )
        history.stats = build_stats(history) if records else {}
        return history

    def _parse_sire_from_ped(self, soup) -> str:
        """血統ページから父馬名を取得"""
        # 血統表の最初のtd（父）を取得
        table = soup.select_one("table.blood_table")
        if not table:
            return ""
        # 最初のリンク = 父
        first_link = table.select_one("td a")
        return first_link.get_text(strip=True) if first_link else ""

    def _parse_profile(self, soup) -> dict:
        prof = {}
        for row in soup.select(".db_prof_table tr"):
            th = row.select_one("th")
            td = row.select_one("td")
            if not th or not td:
                continue
            key = th.get_text(strip=True)
            val = td.get_text(strip=True)
            if key == "父":
                prof["sire"] = val
            elif key == "母":
                prof["dam"] = val
            elif "性齢" in key:
                m = re.match(r"([牡牝セ騸])", val)
                prof["sex"] = m.group(1) if m else "牡"
        return prof

    def _parse_result_table(self, soup) -> list[RaceRecord]:
        records = []
        table = soup.select_one("table.db_h_race_results")
        if not table:
            return records
        rows = table.find_all("tr")[1:]   # ヘッダースキップ
        for row in rows:
            rec = self._parse_row(row)
            if rec:
                records.append(rec)
        return records

    def _parse_row(self, row) -> Optional[RaceRecord]:
        cells = row.find_all("td")
        if len(cells) < 20:
            return None
        try:
            # 列マッピング（実際のnetkeiba構造に準拠）
            date_str  = cells[0].get_text(strip=True)   # 日付
            venue_raw = cells[1].get_text(strip=True)   # 開催
            weather   = cells[2].get_text(strip=True)   # 天気
            race_name = cells[4].get_text(strip=True)   # レース名
            num_horses= _int(cells[6].get_text(strip=True))  # 頭数
            frame_no  = _int(cells[7].get_text(strip=True))  # 枠番
            horse_no  = _int(cells[8].get_text(strip=True))  # 馬番
            odds      = _float(cells[9].get_text(strip=True)) # オッズ
            popularity= _int(cells[10].get_text(strip=True)) # 人気
            order     = _order(cells[11].get_text(strip=True)) # 着順
            jockey    = cells[12].get_text(strip=True)  # 騎手
            weight_carry = _float(cells[13].get_text(strip=True))  # 斤量
            dist_text = cells[14].get_text(strip=True)  # 距離（例: 芝1600, ダ1400）
            condition = cells[16].get_text(strip=True)  # 馬場
            time_str  = cells[18].get_text(strip=True)  # タイム
            margin    = cells[19].get_text(strip=True)  # 着差
            time_idx  = _float(cells[20].get_text(strip=True)) if len(cells) > 20 else 0.0
            pace_up   = _float(cells[27].get_text(strip=True)) if len(cells) > 27 else 0.0
            hw_text   = cells[28].get_text(strip=True) if len(cells) > 28 else "0(0)"
            corner    = cells[25].get_text(strip=True) if len(cells) > 25 else ""

            surface, distance, direction = _parse_dist(dist_text)
            horse_weight, weight_diff = _parse_hw(hw_text)
            time_sec = _parse_time_str(time_str)
            venue = _parse_venue(venue_raw)
            grade = _extract_grade(race_name)

            return RaceRecord(
                date=date_str, venue=venue, weather=weather,
                race_name=race_name, grade=grade,
                surface=surface, distance=distance, direction=direction,
                condition=condition, num_horses=num_horses,
                frame_no=frame_no, horse_no=horse_no,
                order=order, popularity=popularity, odds=odds,
                jockey=jockey, weight_carry=weight_carry,
                time_str=time_str, time_sec=time_sec,
                margin=margin, time_index=time_idx, pace_up=pace_up,
                horse_weight=horse_weight, weight_diff=weight_diff,
                corner_pass=corner,
            )
        except Exception:
            return None


# ============================================================
# 統計構築
# ============================================================

def build_stats(history: FullHorseHistory) -> dict:
    """全過去レースから多次元統計を構築"""
    recs = history.records
    if not recs:
        return {}

    total = len(recs)
    wins  = sum(1 for r in recs if r.order == 1)
    top3  = sum(1 for r in recs if 1 <= r.order <= 3)

    # JRAのみ（地方・海外を除く）
    jra_recs = [r for r in recs if _is_jra(r.venue)]

    return {
        "total": total,
        "wins": wins,
        "top3": top3,
        "win_rate": wins / total,
        "place_rate": top3 / total,
        "jra_total": len(jra_recs),
        # 条件別
        "by_surface":    _group(recs, lambda r: r.surface),
        "by_distance":   _group(recs, lambda r: _dist_band(r.distance)),
        "by_venue":      _group(recs, lambda r: r.venue),
        "by_condition":  _group(recs, lambda r: r.condition),
        "by_grade":      _group(recs, lambda r: r.grade),
        "by_direction":  _group(recs, lambda r: r.direction),
        "by_season":     _group(recs, lambda r: _season(r.date)),
        "by_popularity": _group(recs, lambda r: _pop_band(r.popularity)),
        # ペース・タイム指数
        "avg_pace_up":       _avg([r.pace_up for r in recs if r.pace_up > 0]),
        "avg_pace_up_win":   _avg([r.pace_up for r in recs if r.order == 1 and r.pace_up > 0]),
        "avg_time_index":    _avg([r.time_index for r in recs if r.time_index > 0]),
        "max_time_index":    max((r.time_index for r in recs if r.time_index > 0), default=0),
        # 馬体重
        "weight_trend":  _weight_trend(recs),
        "avg_weight":    _avg([r.horse_weight for r in recs if r.horse_weight > 0]),
        # 近走指数
        "form_index":    _form_index(recs),
        # 回収率
        "roi":           _roi(recs),
        # 休養別
        "by_rest":       _rest_analysis(recs),
        # 脚質推定
        "running_style": _running_style(recs),
        # 敵レベル補正スコア
        "class_score":   _class_score(recs),
        # スピード指数
        "speed_index":   _speed_index(recs),
        # ★ 対戦相手レベル分析（負けた時の相手の強さを評価）
        "opponent_quality": _opponent_quality(recs),
        # ★ 隠れた強さ指標（高レベル戦での敗戦に価値あり）
        "hidden_strength":  _hidden_strength(recs),
        # ★ 上がり3F一貫性
        "pace_consistency": _pace_consistency(recs),
        # ★ 人気vs着順の一貫性（信頼度）
        "reliability_score": _reliability_score(recs),
    }


# ---- 統計ヘルパー ----

def _group(recs: list, key_fn) -> dict:
    groups: dict = {}
    for r in recs:
        k = key_fn(r)
        groups.setdefault(k, []).append(r)
    return {k: _rec_stat(v) for k, v in groups.items()}


def _rec_stat(rs: list) -> dict:
    n = len(rs)
    w = sum(1 for r in rs if r.order == 1)
    t = sum(1 for r in rs if 1 <= r.order <= 3)
    return {"n": n, "wins": w, "top3": t,
            "win_rate": w/n, "place_rate": t/n}


def _form_index(recs: list) -> float:
    """直近8走加重平均（新しいほど重み大）"""
    if not recs:
        return 50.0
    scores = []
    for i, r in enumerate(recs[:8]):
        if r.order >= 99 or r.num_horses <= 1:
            continue
        base = max(0, 1 - (r.order - 1) / (r.num_horses - 1)) * 100
        if r.order < r.popularity:
            base = min(100, base + 8)   # 人気より上の着順
        if r.time_index > 0:
            base = (base + r.time_index) / 2
        w = 1.0 - i * 0.10
        scores.append(base * w)
    return round(sum(scores) / len(scores), 2) if scores else 50.0


def _speed_index(recs: list) -> float:
    """タイム指数の最高値・平均から算出"""
    idxs = [r.time_index for r in recs[:10] if r.time_index > 0]
    if not idxs:
        return 50.0
    return round((max(idxs) * 0.6 + sum(idxs)/len(idxs) * 0.4), 1)


def _class_score(recs: list) -> float:
    """出走クラスレベルの実績スコア"""
    grade_val = {"G1": 100, "G2": 85, "G3": 75, "OP": 65,
                 "3勝": 55, "2勝": 45, "1勝": 35, "条件": 25, "未勝利": 15, "新馬": 10}
    vals = [grade_val.get(r.grade, 25) for r in recs if r.order <= 3]
    return _avg(vals) if vals else 25.0


def _running_style(recs: list) -> str:
    """通過順位から脚質を推定"""
    styles = []
    for r in recs[:8]:
        if not r.corner_pass:
            continue
        corners = [_int(x) for x in r.corner_pass.split("-") if x.strip().isdigit()]
        if not corners or r.num_horses <= 0:
            continue
        first = corners[0] / r.num_horses
        if first <= 0.2:
            styles.append("逃げ")
        elif first <= 0.4:
            styles.append("先行")
        elif first <= 0.65:
            styles.append("差し")
        else:
            styles.append("追込")
    if not styles:
        return "不明"
    return max(set(styles), key=styles.count)


def _weight_trend(recs: list) -> str:
    ws = [r.horse_weight for r in recs[:5] if r.horse_weight > 0]
    if len(ws) < 2:
        return "不明"
    diff = ws[0] - ws[-1]
    if diff >= 8: return "増加傾向"
    if diff <= -8: return "減少傾向"
    return "安定"


def _roi(recs: list) -> float:
    total_bet = len(recs) * 100
    total_ret = sum(r.odds * 100 for r in recs if r.order == 1)
    return round(total_ret / total_bet * 100, 1) if total_bet > 0 else 0.0


def _rest_analysis(recs: list) -> dict:
    result = {}
    for i in range(1, len(recs)):
        try:
            d1 = _parse_date(recs[i-1].date)
            d2 = _parse_date(recs[i].date)
            if not d1 or not d2:
                continue
            weeks = (d1 - d2).days // 7
            band = ("連闘" if weeks <= 1 else "中1-2週" if weeks <= 3
                    else "中3-8週" if weeks <= 8 else "長期休養明け")
            result.setdefault(band, []).append(recs[i-1])
        except Exception:
            pass
    return {k: _rec_stat(v) for k, v in result.items()}


def _opponent_quality(recs: list) -> dict:
    """
    過去の対戦相手レベルを分析
    タイム指数が高いレースで負けた = 強い相手に負けた（隠れた強さ）
    """
    if not recs:
        return {"avg": 0, "max": 0, "high_level_losses": 0}

    time_indices = [r.time_index for r in recs if r.time_index > 0]
    # 負けたレースのタイム指数（強い相手に負けたほど高い）
    loss_indices = [r.time_index for r in recs if r.order > 1 and r.time_index > 0]
    high_level_losses = sum(1 for idx in loss_indices if idx >= 90)  # 重賞レベル

    return {
        "avg": round(sum(time_indices)/len(time_indices), 1) if time_indices else 0,
        "max": round(max(time_indices), 1) if time_indices else 0,
        "high_level_losses": high_level_losses,  # 重賞レベルの敗戦数
        "avg_loss_quality": round(sum(loss_indices)/len(loss_indices), 1) if loss_indices else 0,
    }


def _hidden_strength(recs: list) -> float:
    """
    隠れた強さ指標
    高クラスの敗戦・高タイム指数の敗戦 = 実力が隠れている可能性
    """
    if not recs:
        return 50.0

    scores = []
    grade_val = {"G1": 100, "G2": 88, "G3": 78, "OP": 68, "3勝": 58,
                 "2勝": 48, "1勝": 38, "条件": 28, "未勝利": 18, "新馬": 10}

    for r in recs[:10]:
        if r.order <= 3:
            continue  # 好走は除外、負けだけを分析
        gv = grade_val.get(r.grade, 28)
        # タイム指数が高い敗戦 = 強い相手に負けた
        ti = r.time_index if r.time_index > 0 else gv
        combined = (gv * 0.5 + ti * 0.5)
        # 僅差の敗戦は特に評価（着差が少ない）
        margin_score = 0
        if r.margin in ["クビ", "ハナ", "アタマ", "1/2"]:
            margin_score = 15
        elif r.margin in ["3/4", "1"]:
            margin_score = 8
        scores.append(combined + margin_score)

    return round(sum(scores)/len(scores), 1) if scores else 50.0


def _pace_consistency(recs: list) -> float:
    """上がり3Fの一貫性（安定して速い上がりが出せる馬）"""
    paces = [r.pace_up for r in recs[:8] if r.pace_up > 0]
    if len(paces) < 3:
        return 50.0
    avg = sum(paces) / len(paces)
    variance = sum((p - avg)**2 for p in paces) / len(paces)
    std = variance ** 0.5
    # 平均が速く、標準偏差が小さいほど高スコア
    speed_score = max(0, 100 - (avg - 33) * 10)  # 33秒基準
    consistency_score = max(0, 100 - std * 20)
    return round((speed_score * 0.6 + consistency_score * 0.4), 1)


def _reliability_score(recs: list) -> float:
    """
    人気に応じた着順の信頼性
    1〜3番人気で安定して3着以内に来られる馬は信頼できる
    """
    if not recs:
        return 50.0
    popular_recs = [r for r in recs[:15] if r.popularity <= 3 and r.order < 99]
    if not popular_recs:
        return 50.0
    hit = sum(1 for r in popular_recs if r.order <= 3)
    return round(hit / len(popular_recs) * 100, 1)


def _avg(lst) -> float:
    return round(sum(lst)/len(lst), 2) if lst else 0.0


def _dist_band(d: int) -> str:
    if d <= 1200: return "~1200m"
    if d <= 1400: return "1201~1400m"
    if d <= 1600: return "1401~1600m"
    if d <= 1800: return "1601~1800m"
    if d <= 2000: return "1801~2000m"
    if d <= 2400: return "2001~2400m"
    return "2401m以上"


def _pop_band(p: int) -> str:
    if p <= 3: return "1~3人気"
    if p <= 6: return "4~6人気"
    if p <= 9: return "7~9人気"
    return "10人気以下"


def _season(date_str: str) -> str:
    try:
        m = int(re.search(r"[-/](\d{2})[-/]", date_str).group(1))
        return {1:"冬",2:"冬",3:"春",4:"春",5:"春",6:"夏",
                7:"夏",8:"夏",9:"秋",10:"秋",11:"秋",12:"冬"}.get(m, "不明")
    except Exception:
        return "不明"


def _is_jra(venue: str) -> bool:
    jra = ["札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉"]
    return any(v in venue for v in jra)


def _parse_dist(text: str):
    m = re.search(r"([芝ダ障])([右左直])?(\d+)", text)
    if m:
        s = {"芝":"芝","ダ":"ダート","障":"障害"}.get(m.group(1),"芝")
        d = m.group(2) or "右"
        return s, int(m.group(3)), d
    return "芝", 1600, "右"


def _parse_hw(text: str):
    m = re.match(r"(\d+)\(([+-]?\d+)\)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r"(\d+)", text)
    return (int(m2.group(1)), 0) if m2 else (0, 0)


def _parse_time_str(text: str) -> float:
    m = re.match(r"(\d+):(\d+\.\d+)", text)
    if m:
        return int(m.group(1))*60 + float(m.group(2))
    m2 = re.match(r"(\d+\.\d+)", text)
    return float(m2.group(1)) if m2 else 0.0


def _parse_venue(raw: str) -> str:
    for v in ["札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉",
              "門別","盛岡","水沢","浦和","船橋","大井","川崎","金沢","笠松","名古屋",
              "園田","姫路","高知","佐賀"]:
        if v in raw:
            return v
    return raw


def _parse_date(date_str: str):
    try:
        from datetime import datetime
        for fmt in ["%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"]:
            try:
                return datetime.strptime(date_str, fmt).date()
            except Exception:
                pass
    except Exception:
        pass
    return None


def _int(s: str) -> int:
    try:
        return int(re.search(r"\d+", s).group())
    except Exception:
        return 0


def _float(s: str) -> float:
    try:
        return float(re.search(r"[\d.]+", s).group())
    except Exception:
        return 0.0


def _order(s: str) -> int:
    if any(c in s for c in ["除","取","失","中","降"]):
        return 99
    try:
        return int(re.search(r"\d+", s).group())
    except Exception:
        return 99


def _extract_grade(race_name: str) -> str:
    for g in ["G1","G2","G3","GⅠ","GⅡ","GⅢ"]:
        if g in race_name:
            return g.replace("Ⅰ","1").replace("Ⅱ","2").replace("Ⅲ","3")
    if any(x in race_name for x in ["オープン","OP","Listed"]):
        return "OP"
    for x in ["3勝","1600万"]:
        if x in race_name: return "3勝"
    for x in ["2勝","1000万"]:
        if x in race_name: return "2勝"
    for x in ["1勝","500万"]:
        if x in race_name: return "1勝"
    if "未勝利" in race_name: return "未勝利"
    if "新馬" in race_name: return "新馬"
    return "条件"
