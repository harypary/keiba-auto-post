"""
レース条件と馬の適性を分析してスコアリングする
"""
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.scraper.jra_scraper import RaceInfo, HorseEntry
from src.scraper.netkeiba_scraper import HorseStats


@dataclass
class HorseScore:
    horse_no: int
    frame_no: int
    horse_name: str
    jockey: str
    trainer: str
    weight_carry: float
    total_score: float
    surface_score: float
    distance_score: float
    track_score: float
    condition_score: float
    form_score: float         # 近走成績
    jockey_score: float
    speed_figure: float
    win_rate: float
    place_rate: float
    odds: Optional[float]
    popularity: Optional[int]
    recommendation_rank: int = 0
    comment: str = ""
    stats: Optional[HorseStats] = None


# 有力騎手ボーナス（JRAトップジョッキー）
TOP_JOCKEYS = {
    "川田将雅": 10, "福永祐一": 8, "戸崎圭太": 8, "横山武史": 8,
    "岩田望来": 7, "松山弘平": 7, "坂井瑠星": 7, "武豊": 9,
    "Cルメール": 12, "Mデムーロ": 10, "浜中俊": 6, "幸英明": 6,
    "和田竜二": 6, "池添謙一": 6, "岩田康誠": 7, "三浦皇成": 6,
    "横山典弘": 7, "内田博幸": 6, "北村友一": 6, "田辺裕信": 6,
    "レーン": 11, "ムルザバエフ": 9, "モレイラ": 12,
}

# 有力調教師ボーナス
TOP_TRAINERS = {
    "友道康夫": 8, "矢作芳人": 8, "国枝栄": 7, "須貝尚介": 7,
    "高野友和": 7, "中内田充正": 8, "斉藤崇史": 7, "堀宣行": 8,
    "藤原英昭": 8, "池江泰寿": 8, "音無秀孝": 7, "安田隆行": 7,
}

# 距離帯マッピング
def distance_band(d: int) -> str:
    if d <= 1200:
        return "短距離"
    elif d <= 1400:
        return "マイル前"
    elif d <= 1800:
        return "マイル"
    elif d <= 2200:
        return "中距離"
    elif d <= 2600:
        return "長距離"
    else:
        return "超長距離"


class RaceAnalyzer:
    def analyze(self, race: RaceInfo, horse_stats_map: dict[str, HorseStats]) -> list[HorseScore]:
        scores = []
        for entry in race.horses:
            stats = horse_stats_map.get(entry.horse_id)
            score = self._score_horse(entry, stats, race)
            scores.append(score)

        # ランキング付け
        scores.sort(key=lambda x: x.total_score, reverse=True)
        for i, s in enumerate(scores):
            s.recommendation_rank = i + 1
            s.comment = self._generate_comment(s, race)

        return scores

    def _score_horse(self, entry: HorseEntry, stats: Optional[HorseStats], race: RaceInfo) -> HorseScore:
        surface_score = self._surface_score(stats, race.surface)
        distance_score = self._distance_score(stats, race.distance)
        track_score = self._track_score(stats, race.venue)
        condition_score = self._condition_score(stats, race.condition)
        form_score = self._form_score(stats)
        jockey_score = TOP_JOCKEYS.get(entry.jockey, 0) + TOP_TRAINERS.get(entry.trainer, 0)
        speed_fig = stats.speed_figure if stats else 50.0

        total = (
            surface_score * 0.20 +
            distance_score * 0.20 +
            track_score * 0.10 +
            condition_score * 0.10 +
            form_score * 0.25 +
            speed_fig * 0.15 +
            jockey_score
        )

        return HorseScore(
            horse_no=entry.horse_no,
            frame_no=entry.frame_no,
            horse_name=entry.horse_name,
            jockey=entry.jockey,
            trainer=entry.trainer,
            weight_carry=entry.weight_carry,
            total_score=round(total, 2),
            surface_score=surface_score,
            distance_score=distance_score,
            track_score=track_score,
            condition_score=condition_score,
            form_score=form_score,
            jockey_score=jockey_score,
            speed_figure=speed_fig,
            win_rate=stats.win_rate if stats else 0.0,
            place_rate=stats.place_rate if stats else 0.0,
            odds=entry.odds,
            popularity=entry.popularity,
            stats=stats,
        )

    def _surface_score(self, stats: Optional[HorseStats], surface: str) -> float:
        if not stats:
            return 50.0
        rec = stats.turf_record if surface == "芝" else stats.dirt_record
        if not rec or rec.get("total", 0) == 0:
            return 40.0
        return min(100, rec.get("place_rate", 0) * 150 + rec.get("win_rate", 0) * 50)

    def _distance_score(self, stats: Optional[HorseStats], distance: int) -> float:
        if not stats or not stats.distance_records:
            return 50.0
        best_score = 40.0
        for label, rec in stats.distance_records.items():
            import re
            m = re.search(r"(\d+)", label)
            if not m:
                continue
            center = int(m.group(1))
            diff = abs(center - distance)
            if diff <= 200 and rec.get("total", 0) >= 1:
                score = rec.get("place_rate", 0) * 150 + rec.get("win_rate", 0) * 50
                score = max(0, score - diff * 0.05)
                best_score = max(best_score, score)
        return min(100, best_score)

    def _track_score(self, stats: Optional[HorseStats], venue: str) -> float:
        if not stats or not stats.track_records:
            return 50.0
        rec = stats.track_records.get(venue, {})
        if not rec or rec.get("total", 0) == 0:
            return 50.0
        return min(100, rec.get("place_rate", 0) * 150 + rec.get("win_rate", 0) * 50)

    def _condition_score(self, stats: Optional[HorseStats], condition: str) -> float:
        if not stats or not stats.condition_records:
            return 60.0
        rec = stats.condition_records.get(condition, {})
        if not rec or rec.get("total", 0) == 0:
            return 55.0
        return min(100, rec.get("place_rate", 0) * 150 + rec.get("win_rate", 0) * 50)

    def _form_score(self, stats: Optional[HorseStats]) -> float:
        if not stats or not stats.recent_results:
            return 50.0
        scores = []
        for i, r in enumerate(stats.recent_results[:5]):
            try:
                order_str = r.get("order", "99")
                order = int("".join(filter(str.isdigit, order_str)) or "99")
                num_str = r.get("num_horses", "1")
                num = int("".join(filter(str.isdigit, num_str)) or "1")
                weight = 1.0 - i * 0.15   # 直近ほど重み大
                score = max(0, (1 - (order - 1) / max(num - 1, 1))) * 100 * weight
                scores.append(score)
            except Exception:
                scores.append(50.0)
        return round(sum(scores) / len(scores), 1) if scores else 50.0

    def _generate_comment(self, score: HorseScore, race: RaceInfo) -> str:
        parts = []
        if score.surface_score >= 70:
            parts.append(f"{race.surface}適性◎")
        elif score.surface_score >= 55:
            parts.append(f"{race.surface}適性○")

        if score.distance_score >= 70:
            parts.append("距離ベスト")
        elif score.distance_score >= 55:
            parts.append("距離○")

        if score.track_score >= 70:
            parts.append(f"{race.venue}巧者")

        if score.form_score >= 75:
            parts.append("近走好調")
        elif score.form_score < 40:
            parts.append("近走不振")

        if score.jockey_score >= 10:
            parts.append(f"{score.jockey}騎乗で期待")

        if score.place_rate >= 0.5:
            parts.append(f"複勝率{score.place_rate*100:.0f}%")

        return "・".join(parts) if parts else "データ不足"
