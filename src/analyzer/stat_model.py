"""
統計スコアリングモデル（的中特化版）
日本の競馬データ研究に基づいた重み付け：
  直近3走 > 距離/馬場適性 > スピード指数 > クラス変化 > 騎手 > コース > 間隔
"""
import math
import re
from dataclasses import dataclass
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.scraper.history_scraper import FullHorseHistory, build_stats, _dist_band

# 有力騎手スコア（JRA成績・勝率上位）
TOP_JOCKEYS = {
    "Cルメール": 14, "レーン": 12, "モレイラ": 12, "ムルザバエフ": 10,
    "川田将雅": 13, "武豊": 10, "横山武史": 10, "戸崎圭太": 9,
    "松山弘平": 9, "岩田望来": 9, "坂井瑠星": 9,
    "池添謙一": 7, "幸英明": 7, "岩田康誠": 8, "三浦皇成": 7,
    "横山典弘": 8, "内田博幸": 7, "北村友一": 8, "浜中俊": 7,
    "田辺裕信": 7, "和田竜二": 6, "西村淳也": 8, "津村明秀": 7,
    "藤岡佑介": 7, "藤岡康太": 7, "菱田裕二": 6, "松若風馬": 7,
    "斎藤新": 6, "原優介": 6,
}

TOP_TRAINERS = {
    "友道康夫": 8, "矢作芳人": 9, "中内田充正": 10, "堀宣行": 9,
    "藤原英昭": 8, "池江泰寿": 9, "高野友和": 8, "斉藤崇史": 8,
    "国枝栄": 8, "須貝尚介": 8, "安田隆行": 8, "音無秀孝": 7,
    "手塚貴久": 8, "木村哲也": 8, "大竹正博": 7, "奥村武": 7,
    "西村真幸": 7, "清水久詞": 7,
}

GRADE_ORDER = ["G1", "G2", "G3", "OP", "3勝", "2勝", "1勝", "条件", "未勝利", "新馬"]


@dataclass
class StatScore:
    horse_no: int
    horse_name: str
    jockey: str
    trainer: str
    weight_carry: float
    # スコア内訳
    surface_score: float
    distance_score: float
    venue_score: float
    condition_score: float
    form_score: float
    pace_score: float
    weight_score: float
    jockey_bonus: float
    trainer_bonus: float
    rest_score: float
    roi_score: float
    grade_score: float
    # 統計値
    win_rate: float
    place_rate: float
    total_races: int
    speed_index: float
    # デフォルトあり
    pace_advantage: float = 0
    rival_score: float = 0
    running_style: str = "不明"
    total_score: float = 0
    odds: Optional[float] = None
    comment: str = ""
    recommendation_rank: int = 0


class StatModel:
    def score(
        self,
        horse_no: int,
        horse_name: str,
        jockey: str,
        trainer: str,
        weight_carry: float,
        history: Optional[FullHorseHistory],
        race_surface: str,
        race_distance: int,
        race_venue: str,
        race_condition: str,
        race_grade: str,
        last_rest_weeks: int = 4,
        odds: Optional[float] = None,
    ) -> StatScore:

        if history is None or not history.records:
            return self._default_score(horse_no, horse_name, jockey, trainer, weight_carry, odds)

        recs = history.records
        stats = history.stats if history.stats else build_stats(history)

        # ① 直近3走スコア（最重要・指数関数的重み付け）
        recent_score    = _recent_form_score(recs)

        # ② 距離・馬場適性
        surface_score   = self._surface(stats, race_surface)
        distance_score  = self._distance(stats, race_distance)

        # ③ スピード指数（タイム指数ベース）
        speed_score     = _speed_score_from_index(recs, race_distance, race_surface)

        # ④ クラス変化ボーナス（降級 = 強力な武器）
        class_bonus     = _class_change_bonus(recs, race_grade)

        # ⑤ 騎手・調教師
        jockey_bonus    = TOP_JOCKEYS.get(jockey, 0)
        trainer_bonus   = TOP_TRAINERS.get(trainer, 0)

        # ⑥ コース・馬場状態・間隔
        venue_score     = self._venue(stats, race_venue)
        condition_score = self._condition(stats, race_condition)
        rest_score      = self._rest(stats, recs, race_grade)

        # ⑦ 上がり3F適性（ペース）
        pace_score      = self._pace(stats)

        # ⑧ 馬体重安定性
        weight_score    = self._weight_stability(recs[:6])

        # ⑨ ROI実績（穴馬評価補正）
        roi_score       = min(20, max(0, (stats.get("roi", 0) - 60) / 8))

        # ⑩ クラス実績
        grade_score     = self._grade(stats, race_grade)

        # ---- 最終スコア（バックテストで自動調整された重みを使用）----
        from src.validator.weight_optimizer import get_weights
        w = get_weights()
        total = (
            recent_score    * w.get("recent_form",  0.30) +
            surface_score   * w.get("surface",      0.15) +
            distance_score  * w.get("distance",     0.15) +
            speed_score     * w.get("speed_index",  0.12) +
            class_bonus     * w.get("class_change", 0.08) +
            venue_score     * w.get("venue",        0.06) +
            condition_score * w.get("condition",    0.04) +
            rest_score      * w.get("rest",         0.05) +
            pace_score      * w.get("pace",         0.03) +
            weight_score    * w.get("weight_stab",  0.02)
        ) + jockey_bonus * 0.9 + trainer_bonus * 0.5

        speed_index   = stats.get("speed_index", 50.0)
        running_style = stats.get("running_style", "不明")

        return StatScore(
            horse_no=horse_no, horse_name=horse_name,
            jockey=jockey, trainer=trainer, weight_carry=weight_carry,
            surface_score=round(surface_score, 1),
            distance_score=round(distance_score, 1),
            venue_score=round(venue_score, 1),
            condition_score=round(condition_score, 1),
            form_score=round(recent_score, 1),
            pace_score=round(pace_score, 1),
            weight_score=round(weight_score, 1),
            jockey_bonus=jockey_bonus,
            trainer_bonus=trainer_bonus,
            rest_score=round(rest_score, 1),
            roi_score=round(roi_score, 1),
            grade_score=round(grade_score, 1),
            total_score=round(total, 2),
            win_rate=stats.get("win_rate", 0.0),
            place_rate=stats.get("place_rate", 0.0),
            total_races=stats.get("total", 0),
            speed_index=round(speed_index, 1),
            running_style=running_style,
            odds=odds,
        )

    # ---- 各スコア計算 ----

    def _surface(self, stats: dict, surface: str) -> float:
        rec = stats.get("by_surface", {}).get(surface, {})
        return _rate_to_score(rec)

    def _distance(self, stats: dict, distance: int) -> float:
        band = _dist_band(distance)
        by_d = stats.get("by_distance", {})
        score = _rate_to_score(by_d.get(band, {}))
        # 隣接距離帯も加味（最大300m差まで）
        for k, v in by_d.items():
            try:
                center = _band_center(k)
                diff = abs(center - distance)
                if diff <= 300 and v.get("n", 0) >= 2:
                    adj = _rate_to_score(v) * max(0, 1 - diff / 600)
                    score = max(score, adj)
            except Exception:
                pass
        return score

    def _venue(self, stats: dict, venue: str) -> float:
        rec = stats.get("by_venue", {}).get(venue, {})
        return _rate_to_score(rec)

    def _condition(self, stats: dict, condition: str) -> float:
        rec = stats.get("by_condition", {}).get(condition, {})
        if rec.get("n", 0) == 0:
            return 55.0
        return _rate_to_score(rec)

    def _pace(self, stats: dict) -> float:
        avg = stats.get("avg_pace_up", 0)
        win = stats.get("avg_pace_up_win", 0)
        if avg <= 0:
            return 50.0
        if win > 0 and abs(avg - win) < 0.5:
            return 75.0  # 上がり3Fが安定して速い
        return 50.0 + min(25, max(-25, (36 - avg) * 5))  # 36秒基準

    def _weight_stability(self, recent_recs: list) -> float:
        diffs = [abs(r.weight_diff) for r in recent_recs if r.horse_weight > 0]
        if not diffs:
            return 60.0
        avg_diff = sum(diffs) / len(diffs)
        return max(0, min(100, 100 - avg_diff * 4))

    def _rest(self, stats: dict, recs: list, grade: str) -> float:
        """実際の前走日からの間隔で計算"""
        if not recs:
            return 55.0
        try:
            from src.scraper.history_scraper import _parse_date
            from datetime import date
            last_date = _parse_date(recs[0].date)
            if last_date:
                weeks = (date.today() - last_date).days // 7
                # 最適間隔: 3-6週（日本のトレーニング体系）
                if 3 <= weeks <= 6:
                    return 75.0
                elif 1 <= weeks <= 8:
                    return 62.0
                elif weeks <= 1:
                    return 45.0  # 連闘
                else:
                    return 50.0  # 長期休養
        except Exception:
            pass
        # フォールバック: 過去の間隔別成績
        by_rest = stats.get("by_rest", {})
        best = max((v.get("win_rate", 0) for v in by_rest.values()), default=0)
        return 50 + min(25, best * 100)

    def _grade(self, stats: dict, current_grade: str) -> float:
        by_g = stats.get("by_grade", {})
        current_idx = GRADE_ORDER.index(current_grade) if current_grade in GRADE_ORDER else 7
        score = 50.0
        for g, rec in by_g.items():
            g_idx = GRADE_ORDER.index(g) if g in GRADE_ORDER else 7
            if g_idx <= current_idx and rec.get("n", 0) >= 2:
                s = _rate_to_score(rec)
                if g_idx < current_idx:
                    s = min(100, s * 1.2)  # 上クラス実績ボーナス
                score = max(score, s)
        return score

    def _default_score(self, horse_no, horse_name, jockey, trainer, weight_carry, odds) -> StatScore:
        j = TOP_JOCKEYS.get(jockey, 0)
        t = TOP_TRAINERS.get(trainer, 0)
        return StatScore(
            horse_no=horse_no, horse_name=horse_name,
            jockey=jockey, trainer=trainer, weight_carry=weight_carry,
            surface_score=50, distance_score=50, venue_score=50,
            condition_score=50, form_score=50, pace_score=50,
            weight_score=50, jockey_bonus=j, trainer_bonus=t,
            rest_score=50, roi_score=0, grade_score=50,
            total_score=round(50 + j * 0.9 + t * 0.5, 2),
            win_rate=0, place_rate=0, total_races=0, speed_index=50, odds=odds,
        )


# ============================================================
# 的中特化スコア計算関数
# ============================================================

def _recent_form_score(recs: list) -> float:
    """
    直近3走の加重平均（指数関数的重み付け）
    - 着順/頭数の相対評価
    - タイム指数を直接反映
    - 人気より上の着順は上乗せ
    - 着差も考慮（大差勝ちは高評価）
    """
    if not recs:
        return 45.0

    weights = [0.55, 0.30, 0.15]  # 前走 55%、2走前 30%、3走前 15%
    scores  = []

    for i, r in enumerate(recs[:3]):
        if r.order >= 99 or r.num_horses <= 1:
            scores.append(40.0)
            continue

        # 相対着順スコア (1着=100, 最下位=0)
        rank_score = max(0, 1 - (r.order - 1) / (r.num_horses - 1)) * 100

        # タイム指数があれば優先的に使う（より客観的）
        if r.time_index > 0:
            rank_score = (rank_score * 0.4 + r.time_index * 0.6)

        # 人気より上の着順 = 能力を発揮した証拠
        if r.order < r.popularity:
            rank_score = min(100, rank_score + 10)
        elif r.popularity <= 3 and r.order > 5:
            rank_score = max(0, rank_score - 8)  # 人気裏切り

        # 大差勝ちボーナス（着差テキストから）
        if r.order == 1:
            margin_bonus = _margin_bonus(r.margin)
            rank_score = min(100, rank_score + margin_bonus)

        scores.append(rank_score)

    # 加重平均
    total_w = sum(weights[:len(scores)])
    result   = sum(s * w for s, w in zip(scores, weights[:len(scores)])) / total_w
    return round(result, 1)


def _margin_bonus(margin: str) -> float:
    """着差テキストからボーナスポイントを計算"""
    if not margin:
        return 0
    margin_map = {
        "大差": 15, "10": 12, "8": 10, "7": 9, "6": 8,
        "5": 7, "4": 6, "3": 5, "2": 4,
        "1 1/2": 3, "1": 2.5, "3/4": 1.5,
        "1/2": 1, "アタマ": 0.5, "ハナ": 0.3, "クビ": 0.5,
    }
    for k, v in sorted(margin_map.items(), key=lambda x: -x[1]):
        if k in margin:
            return v
    return 0


def _speed_score_from_index(recs: list, distance: int, surface: str) -> float:
    """
    タイム指数から条件別スピードスコアを算出
    同距離・同馬場の実績タイム指数を優先的に使用
    """
    # 同条件のタイム指数
    same_cond = [
        r.time_index for r in recs[:15]
        if r.time_index > 0 and r.surface == surface and abs(r.distance - distance) <= 200
    ]
    if same_cond:
        # 最高値60% + 平均40%
        return round(max(same_cond) * 0.6 + (sum(same_cond)/len(same_cond)) * 0.4, 1)

    # 全レースのタイム指数
    all_idx = [r.time_index for r in recs[:15] if r.time_index > 0]
    if all_idx:
        return round(max(all_idx) * 0.5 + (sum(all_idx)/len(all_idx)) * 0.5, 1)

    # タイム指数がなければ着順ベース
    relevant = [r for r in recs[:10] if r.surface == surface and abs(r.distance - distance) <= 200]
    if not relevant:
        relevant = recs[:8]
    if not relevant:
        return 50.0

    scores = []
    for r in relevant:
        if r.num_horses > 1 and r.order < 99:
            scores.append(max(0, (1 - (r.order-1)/(r.num_horses-1)) * 100))
    return round(sum(scores)/len(scores), 1) if scores else 50.0


def _class_change_bonus(recs: list, current_grade: str) -> float:
    """
    クラス変化ボーナス（的中に大きく寄与する要素）
    - 降級馬（上のクラスで複数回走った実績あり）は大きなボーナス
    - 上昇馬（初めて上のクラスへ）は慎重に
    """
    if not recs:
        return 50.0

    current_idx = GRADE_ORDER.index(current_grade) if current_grade in GRADE_ORDER else 7

    # 直近3走のクラス
    recent_grades = [r.grade for r in recs[:3] if r.grade in GRADE_ORDER]
    if not recent_grades:
        return 50.0

    recent_idxs = [GRADE_ORDER.index(g) for g in recent_grades]
    avg_recent_idx = sum(recent_idxs) / len(recent_idxs)

    # 降級（前走より今回が下のクラス）= 大きなプラス
    if avg_recent_idx < current_idx:
        drop = current_idx - avg_recent_idx
        bonus = min(95, 65 + drop * 10)
        # 降級馬で直近に複数回3着以内なら特大ボーナス
        recent_places = sum(1 for r in recs[:3] if 1 <= r.order <= 3)
        if recent_places >= 2:
            bonus = min(100, bonus + 10)
        return bonus

    # 同クラス継続
    if abs(avg_recent_idx - current_idx) <= 0.5:
        return 55.0

    # 昇級（今回が上のクラス）= やや不利
    rise = avg_recent_idx - current_idx
    return max(35, 50 - rise * 8)


def _rate_to_score(rec: dict) -> float:
    n  = rec.get("n", 0)
    if n == 0:
        return 48.0
    wr = rec.get("win_rate", 0)
    pr = rec.get("place_rate", 0)
    # サンプル数補正（少ないほど平均に引き寄せる）
    shrink = min(1.0, n / 6)
    raw = wr * 65 + pr * 35
    return round(50 + (raw - 20) * shrink, 1)


def _band_center(band: str) -> int:
    nums = re.findall(r"\d+", band)
    if len(nums) >= 2:
        return (int(nums[0]) + int(nums[1])) // 2
    elif len(nums) == 1:
        return int(nums[0])
    return 1600
