"""
総合スコアリング（完全統計版）
1. 全過去レース: 馬場/距離/コース/馬場状態/季節/間隔/クラス
2. 騎手×馬 相性（過去同騎手での全成績）
3. 血統適性（種牡馬×距離×馬場）
4. 展開予測による展開恩恵
5. 敵レベル補正（今回の出走馬との比較）
6. タイム指数・スピード指数
7. 馬体重安定性
8. 近走フォーム（加重移動平均）
"""
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.scraper.history_scraper import FullHorseHistory, build_stats, _dist_band
from src.scraper.extended_scraper import ExtendedScraper, JockeyHorseAffinity
from src.analyzer.stat_model import StatModel, StatScore, TOP_JOCKEYS, TOP_TRAINERS
from src.analyzer.race_context import RaceContext


# ---- 血統辞書 ----
SIRE_AFFINITY = {
    # === 芝・短距離（〜1400） ===
    "ロードカナロア":     {"surface":"芝","dist_min":1000,"dist_max":1600,"score":10},
    "ダイワメジャー":     {"surface":"芝","dist_min":1200,"dist_max":1800,"score":9},
    "ビッグアーサー":     {"surface":"芝","dist_min":1000,"dist_max":1400,"score":10},
    "ミッキーアイル":     {"surface":"芝","dist_min":1200,"dist_max":1600,"score":9},
    "リアルインパクト":   {"surface":"芝","dist_min":1200,"dist_max":1600,"score":8},
    "リオンディーズ":     {"surface":"芝","dist_min":1400,"dist_max":1800,"score":7},
    "ストロングリターン": {"surface":"芝","dist_min":1200,"dist_max":1600,"score":7},
    # === 芝・マイル〜中距離 ===
    "モーリス":           {"surface":"芝","dist_min":1400,"dist_max":2000,"score":10},
    "ディープインパクト": {"surface":"芝","dist_min":1400,"dist_max":3200,"score":12},
    "キズナ":             {"surface":"芝","dist_min":1600,"dist_max":2400,"score":10},
    "ドゥラメンテ":       {"surface":"芝","dist_min":1600,"dist_max":2400,"score":11},
    "サトノクラウン":     {"surface":"芝","dist_min":1800,"dist_max":2400,"score":10},
    "サトノダイヤモンド": {"surface":"芝","dist_min":1800,"dist_max":2400,"score":8},
    "スワーヴリチャード": {"surface":"芝","dist_min":1600,"dist_max":2400,"score":9},
    "イスラボニータ":     {"surface":"芝","dist_min":1400,"dist_max":1800,"score":8},
    "ハービンジャー":     {"surface":"芝","dist_min":1800,"dist_max":2400,"score":9},
    "リアルスティール":   {"surface":"芝","dist_min":1600,"dist_max":2200,"score":9},
    "ブラックタイド":     {"surface":"芝","dist_min":1600,"dist_max":2400,"score":8},
    "シルバーステート":   {"surface":"芝","dist_min":1400,"dist_max":2000,"score":8},
    # === 芝・中長距離 ===
    "エピファネイア":     {"surface":"芝","dist_min":1800,"dist_max":3200,"score":11},
    "ハーツクライ":       {"surface":"芝","dist_min":1800,"dist_max":3200,"score":10},
    "オルフェーヴル":     {"surface":"芝","dist_min":1600,"dist_max":3200,"score":10},
    "ステイゴールド":     {"surface":"芝","dist_min":2000,"dist_max":3200,"score":9},
    "ゴールドシップ":     {"surface":"芝","dist_min":2000,"dist_max":3200,"score":9},
    "オウケンブルースリ": {"surface":"芝","dist_min":2000,"dist_max":2800,"score":7},
    # === 芝/ダート両刀 ===
    "キングカメハメハ":   {"surface":"any","dist_min":1400,"dist_max":2000,"score":10},
    "ルーラーシップ":     {"surface":"any","dist_min":1600,"dist_max":2400,"score":9},
    "ロベルト":           {"surface":"any","dist_min":1600,"dist_max":2400,"score":7},
    "アドマイヤムーン":   {"surface":"any","dist_min":1600,"dist_max":2200,"score":8},
    "ヴィクトワールピサ": {"surface":"any","dist_min":1800,"dist_max":2200,"score":7},
    # === ダート短〜中 ===
    "ヘニーヒューズ":     {"surface":"ダート","dist_min":1000,"dist_max":1800,"score":11},
    "サウスヴィグラス":   {"surface":"ダート","dist_min":1000,"dist_max":1400,"score":10},
    "ロードオブヴァーラ":{"surface":"ダート","dist_min":1200,"dist_max":1800,"score":9},
    "シニスターミニスター":{"surface":"ダート","dist_min":1200,"dist_max":1800,"score":10},
    "パイロ":             {"surface":"ダート","dist_min":1000,"dist_max":1600,"score":10},
    "クロフネ":           {"surface":"ダート","dist_min":1200,"dist_max":1800,"score":9},
    "ノーザンテースト":   {"surface":"ダート","dist_min":1400,"dist_max":1800,"score":7},
    "ベーカバド":         {"surface":"ダート","dist_min":1200,"dist_max":1800,"score":8},
    "プリサイスエンド":   {"surface":"ダート","dist_min":1200,"dist_max":1800,"score":8},
    # === ダート中長 ===
    "カジノドライヴ":     {"surface":"ダート","dist_min":1600,"dist_max":2100,"score":9},
    "ゴールドアリュール": {"surface":"ダート","dist_min":1400,"dist_max":2100,"score":10},
    "エスポワールシチー": {"surface":"ダート","dist_min":1400,"dist_max":2100,"score":8},
    "マジェスティックウォリアー":{"surface":"ダート","dist_min":1600,"dist_max":2100,"score":9},
    "ホッコータルマエ":   {"surface":"ダート","dist_min":1800,"dist_max":2200,"score":9},
    "アジアエクスプレス": {"surface":"ダート","dist_min":1200,"dist_max":1800,"score":8},
    "コパノリッキー":     {"surface":"ダート","dist_min":1400,"dist_max":2000,"score":8},
    # === 海外/輸入種牡馬 ===
    "ジャスタウェイ":     {"surface":"芝","dist_min":1600,"dist_max":2200,"score":9},
    "ノヴェリスト":       {"surface":"芝","dist_min":2000,"dist_max":2400,"score":7},
    "Frankel":            {"surface":"芝","dist_min":1600,"dist_max":2400,"score":11},
    "Galileo":            {"surface":"芝","dist_min":1800,"dist_max":3200,"score":10},
    "Dubawi":             {"surface":"any","dist_min":1600,"dist_max":2400,"score":10},
    "American Pharoah":   {"surface":"any","dist_min":1600,"dist_max":2400,"score":9},
    # === 母父効きでも使える主流系（参考） ===
    "シンボリクリスエス": {"surface":"any","dist_min":1800,"dist_max":2400,"score":8},
    "アグネスタキオン":   {"surface":"芝","dist_min":1800,"dist_max":2200,"score":8},
}


@dataclass
class ComprehensiveScore:
    horse_no: int
    horse_name: str
    jockey: str
    trainer: str
    weight_carry: float
    # スコア内訳（全て加算方式）
    base_score: float          # 統計ベース（馬場/距離/コース/状態/近走）
    form_score: float          # 近走フォーム指数
    speed_score: float         # スピード・タイム指数
    jockey_bonus: float        # 騎手固定ボーナス
    trainer_bonus: float       # 調教師固定ボーナス
    affinity_bonus: float      # 騎手×馬相性
    pedigree_bonus: float      # 血統適性
    context_bonus: float       # 展開・敵レベル
    training_bonus: float      # 調教評価
    opp_bonus: float           # 対戦相手レベル補正
    final_score: float         # 最終スコア
    # 統計値（表示用）
    win_rate: float
    place_rate: float
    total_races: int
    speed_index: float
    running_style: str
    # 分析オブジェクト
    affinity: Optional[JockeyHorseAffinity] = None
    raw_stat: Optional[StatScore] = None
    # 表示
    odds: Optional[float] = None
    comment: str = ""
    recommendation_rank: int = 0


class ComprehensiveAnalyzer:
    def __init__(self):
        self.stat_model = StatModel()
        self.ext_scraper = ExtendedScraper()

    def analyze_all(self, entries, histories: dict, race, context: RaceContext,
                    use_training: bool = False) -> list[ComprehensiveScore]:
        scores = [
            self._score(entry, histories.get(entry.horse_id), race, context, use_training)
            for entry in entries
        ]

        # === 改善1: 市場オッズとモデルのブレンド（賢い群衆の知恵を取り込む） ===
        _apply_odds_prior(scores)

        # === 改善2: クラス別の重み補正 ===
        _apply_grade_overlay(scores, race)

        # === 改善3: 学習結果（venue_adjustments）の反映 ===
        _apply_learnings_overlay(scores, race)

        # === 改善4: 学習済みMLメタモデルでの補正 ===
        _apply_ml_overlay(scores)

        # === 改善5: 競馬場バイアス（差し有利/前残り）反映 ===
        _apply_venue_bias(scores, race)

        # === 改善6: 穴馬（過去にオッズ↑で好走した馬）にスコアブースト ===
        _apply_value_horse_boost(scores)

        # 最終順位付け
        scores.sort(key=lambda x: x.final_score, reverse=True)
        for i, s in enumerate(scores):
            s.recommendation_rank = i + 1
            s.comment = _make_comment(s, race)
        return scores

    def _score(self, entry, hist: Optional[FullHorseHistory], race, ctx: RaceContext,
               use_training: bool) -> ComprehensiveScore:

        stat = self.stat_model.score(
            horse_no=entry.horse_no, horse_name=entry.horse_name,
            jockey=entry.jockey, trainer=entry.trainer, weight_carry=entry.weight_carry,
            history=hist, race_surface=race.surface, race_distance=race.distance,
            race_venue=race.venue, race_condition=race.condition, race_grade=race.grade,
            odds=entry.odds,
        )

        # 騎手×馬相性
        affinity_bonus = 0.0
        affinity = None
        if entry.horse_id and entry.jockey:
            affinity = self.ext_scraper.get_jockey_horse_affinity(entry.horse_id, entry.jockey)
            if affinity.total >= 2:
                affinity_bonus = affinity.win_rate * 15 + affinity.place_rate * 8
                if affinity.avg_order <= 2.5:
                    affinity_bonus += 6

        # 血統
        sire = hist.sire if hist else ""
        pedigree_bonus = _pedigree_score(sire, race.surface, race.distance)

        # 展開恩恵
        context_bonus = ctx.pace_advantage.get(entry.horse_no, 0)
        context_bonus += ctx.rival_pressure.get(entry.horse_no, 0)
        if hist and hist.stats:
            cs = hist.stats.get("class_score", 25)
            if cs > ctx.field_level:
                context_bonus += 4

        # ★ 対戦相手レベル補正（強敵相手の実績を評価）
        opp_bonus = 0.0
        if hist and hist.stats:
            oq = hist.stats.get("opponent_quality", {})
            hs = hist.stats.get("hidden_strength", 50.0)
            pc = hist.stats.get("pace_consistency", 50.0)
            rel = hist.stats.get("reliability_score", 50.0)

            # 高レベル戦の敗戦数（G1/G2クラスに負けた経験 = 実力の証明）
            high_losses = oq.get("high_level_losses", 0)
            if high_losses >= 3:
                opp_bonus += 6
            elif high_losses >= 1:
                opp_bonus += 3

            # タイム指数の最大値（過去最高パフォーマンス）
            max_ti = oq.get("max", 0)
            if max_ti >= 105:
                opp_bonus += 8   # 重賞レベルのタイム指数
            elif max_ti >= 95:
                opp_bonus += 5
            elif max_ti >= 85:
                opp_bonus += 2

            # 上がり3F一貫性（毎回速い上がりが出せる）
            if pc >= 75:
                opp_bonus += 4
            elif pc >= 65:
                opp_bonus += 2

            # 人気馬としての信頼性
            if rel >= 70:
                opp_bonus += 4
            elif rel >= 50:
                opp_bonus += 2

        # 調教
        training_bonus = 0.0
        if use_training and entry.horse_id:
            tr = self.ext_scraper.get_training_info(entry.horse_id)
            if tr:
                training_bonus = {"A": 8, "B": 3, "C": -3}.get(tr.condition_rating, 0)

        # 最終スコア（対戦相手レベル補正を追加）
        final = (
            stat.total_score
            + affinity_bonus
            + pedigree_bonus
            + context_bonus
            + training_bonus
            + opp_bonus
        )

        return ComprehensiveScore(
            horse_no=entry.horse_no, horse_name=entry.horse_name,
            jockey=entry.jockey, trainer=entry.trainer, weight_carry=entry.weight_carry,
            base_score=round(stat.total_score - stat.jockey_bonus * 0.8 - stat.trainer_bonus * 0.5, 1),
            form_score=round(stat.form_score, 1),
            speed_score=round(stat.speed_index, 1),
            jockey_bonus=round(stat.jockey_bonus, 1),
            trainer_bonus=round(stat.trainer_bonus, 1),
            affinity_bonus=round(affinity_bonus, 2),
            pedigree_bonus=round(pedigree_bonus, 2),
            context_bonus=round(context_bonus, 2),
            training_bonus=round(training_bonus, 2),
            opp_bonus=round(opp_bonus, 2),
            final_score=round(final, 2),
            win_rate=stat.win_rate, place_rate=stat.place_rate,
            total_races=stat.total_races, speed_index=stat.speed_index,
            running_style=stat.running_style,
            affinity=affinity, raw_stat=stat,
            odds=entry.odds,
        )


# ============================================================
# 改善: モデル+市場+学習の3層ブレンド
# ============================================================

def _apply_odds_prior(scores: list) -> None:
    """市場オッズを「賢い群衆の知恵」として弱く混ぜる。
    オッズから人気順位を出し、モデル順位と乖離が極端な馬にペナルティ。"""
    have_odds = [s for s in scores if getattr(s, "odds", None) and s.odds > 0]
    if len(have_odds) < 4:
        return
    # オッズ昇順 = 人気順
    by_odds = sorted(have_odds, key=lambda x: x.odds)
    pop_rank = {s.horse_no: i + 1 for i, s in enumerate(by_odds)}
    by_score = sorted(scores, key=lambda x: x.final_score, reverse=True)
    score_rank = {s.horse_no: i + 1 for i, s in enumerate(by_score)}
    for s in scores:
        pr = pop_rank.get(s.horse_no)
        sr = score_rank.get(s.horse_no)
        if pr is None or sr is None:
            continue
        diff = sr - pr  # +なら市場より低評価、-なら市場より高評価
        # 1人気だがモデル下位（>5位）→ -3点（市場が知っている可能性）
        if pr == 1 and sr > 5:
            s.final_score = round(s.final_score - 3.0, 2)
        # 2-3人気だがモデル下位（>7位）→ -1.5点
        elif pr <= 3 and sr > 7:
            s.final_score = round(s.final_score - 1.5, 2)
        # モデル上位だがオッズ50倍超（極端な穴）→ -2点（情報が薄い可能性）
        if sr <= 3 and (s.odds or 0) >= 50:
            s.final_score = round(s.final_score - 2.0, 2)


def _apply_grade_overlay(scores: list, race) -> None:
    """クラス別の補正：重賞ではスピード指数・対戦相手レベル(opp)を重視、新馬戦は血統重視。"""
    g = getattr(race, "grade", "")
    for s in scores:
        opp = getattr(s, "opp_bonus", 0) or 0
        spd = getattr(s, "speed_score", 0) or 0
        ped = getattr(s, "pedigree_bonus", 0) or 0
        if g in ("G1", "G2", "G3"):
            # 重賞は実力差が結果を分ける
            s.final_score = round(s.final_score + opp * 0.3 + (spd - 50) * 0.05, 2)
        elif g == "OP":
            s.final_score = round(s.final_score + opp * 0.2, 2)
        elif g in ("新馬", "未勝利"):
            # 新馬は血統と過去ない分、騎手・調教師が重要
            s.final_score = round(s.final_score + ped * 0.5, 2)


def _apply_value_horse_boost(scores: list) -> None:
    """過去に穴馬好走歴がある馬にスコアブースト（次走で穴馬として優先表示）"""
    try:
        from src.analyzer.value_horse_tracker import get_score_boost
    except Exception:
        return
    for s in scores:
        boost = get_score_boost(s.horse_name)
        if boost > 0:
            s.final_score = round(s.final_score + boost, 2)


def _apply_venue_bias(scores: list, race) -> None:
    """競馬場の直近バイアス（前残り/差し有利）に応じて脚質補正"""
    try:
        from src.scraper.multi_source_scraper import get_venue_bias
    except Exception:
        return
    bias = get_venue_bias(getattr(race, "venue", ""))
    if not bias:
        return
    back_ratio = bias.get("back_ratio", 0.5)
    # back_ratio = 1.0 なら極端な差し有利。+0.1超えるごとに差し馬+1点、逃げ馬-1点
    diff = (back_ratio - 0.5) * 10
    for s in scores:
        style = getattr(s, "running_style", "")
        if style in ("差し", "追込"):
            s.final_score = round(s.final_score + diff, 2)
        elif style in ("逃げ", "先行"):
            s.final_score = round(s.final_score - diff, 2)


def _apply_ml_overlay(scores: list) -> None:
    """学習済みMLメタモデルでスコアを補正（既存スコアとブレンド）"""
    try:
        from src.ml.meta_model import predict_win_prob, load_model, FEATURES
    except Exception:
        return
    model = load_model()
    if not model:
        return

    for s in scores:
        rs = getattr(s, "raw_stat", None)
        if not rs:
            continue
        ped_raw = getattr(s, "pedigree_bonus", 0) or 0
        ped_norm = min(100, max(0, 50 + ped_raw * 4))
        factors = {
            "recent_form":  getattr(rs, "form_score", 50),
            "surface":      getattr(rs, "surface_score", 50),
            "distance":     getattr(rs, "distance_score", 50),
            "speed_index":  getattr(s,  "speed_score", 50),
            "class_change": getattr(rs, "grade_score", 50),
            "venue":        getattr(rs, "venue_score", 50),
            "condition":    getattr(rs, "condition_score", 50),
            "rest":         getattr(rs, "rest_score", 50),
            "pace":         getattr(rs, "pace_score", 50),
            "weight_stab":  getattr(rs, "weight_score", 50),
            "pedigree":     ped_norm,
        }
        p = predict_win_prob(factors, model)
        if p is None:
            continue
        # ML勝率を 0〜1 → -10〜+10 のスコア補正に変換
        # p=0.5 で補正0、p=0.8 で +6、p=0.2 で -6
        ml_adjust = (p - 0.5) * 20.0
        # 既存スコアに 30% blend（ルールベースを尊重しつつMLを反映）
        s.final_score = round(s.final_score + ml_adjust * 0.3, 2)


def _apply_learnings_overlay(scores: list, race) -> None:
    """学習結果（venue_adjustments等）を反映"""
    try:
        from src.validator.learning_engine import load_learnings
    except Exception:
        return
    L = load_learnings()
    if not L:
        return
    venue = getattr(race, "venue", "")
    va = L.get("venue_adjustments", {}).get(venue, {})
    if not va:
        return
    conf = va.get("confidence", 1.0)
    if abs(conf - 1.0) < 0.01:
        return
    # confidenceが低い場（信頼できない場）では、上位の差を縮める＝穴目台頭
    sorted_s = sorted(scores, key=lambda x: x.final_score, reverse=True)
    if not sorted_s:
        return
    top = sorted_s[0].final_score
    for s in sorted_s[:5]:
        # 上位5頭の差をconf比で圧縮（または拡大）
        gap = top - s.final_score
        s.final_score = round(top - gap * conf, 2)


def _pedigree_score(sire: str, surface: str, distance: int) -> float:
    info = SIRE_AFFINITY.get(sire)
    if not info:
        return 0.0
    s = 0.0
    if info["surface"] == surface or info["surface"] == "any":
        s += info["score"] * 0.5
    if info["dist_min"] <= distance <= info["dist_max"]:
        s += info["score"] * 0.5
    return round(s, 1)


def _make_comment(score: ComprehensiveScore, race) -> str:
    sentences = []
    rs = score.raw_stat
    races = score.total_races
    wr = score.win_rate
    pr = score.place_rate

    # 実績ベース
    if races == 0:
        sentences.append("過去データなし（初出走または未取得）。")
    elif races >= 10:
        sentences.append(
            f"通算{races}戦でキャリアを積んだ実力馬。"
            f"勝率{wr*100:.0f}%・複勝率{pr*100:.0f}%と{'安定した成績を残している' if pr >= 0.4 else '苦戦が続いている'}。"
        )
    elif races >= 3:
        sentences.append(
            f"通算{races}戦・勝率{wr*100:.0f}%・複勝率{pr*100:.0f}%。"
        )

    # 馬場・距離適性
    if rs:
        surf_ok = rs.surface_score >= 65
        dist_ok = rs.distance_score >= 65
        surf_bad = rs.surface_score < 40
        dist_bad = rs.distance_score < 40

        if surf_ok and dist_ok:
            sentences.append(f"今回の{race.surface}{race.distance}mは過去データで最も成績が安定している条件。適性は高い。")
        elif surf_ok:
            sentences.append(f"{race.surface}コースへの適性は高く、馬場は味方になる。")
        elif dist_ok:
            sentences.append(f"{race.distance}m前後の距離は得意条件でスコアも上位。")
        elif surf_bad:
            sentences.append(f"{race.surface}コースでの成績が低く、馬場適性に課題あり。")
        elif dist_bad:
            sentences.append(f"今回の{race.distance}mは過去成績からやや距離が合わない可能性。")

        if rs.venue_score >= 70:
            sentences.append(f"{race.venue}競馬場での成績が特に良く、コース適性◎。")

        if rs.form_score >= 75:
            sentences.append("直近のレース内容が好調で、今が上り調子のタイミング。")
        elif rs.form_score >= 60:
            sentences.append("近走は安定した走りを見せており、状態は悪くない。")
        elif rs.form_score < 35:
            sentences.append("直近数走は結果が出ておらず、現在は下降気味。立て直しが必要な状況。")

    # 騎手相性
    aff = score.affinity
    if aff and aff.total >= 2:
        if aff.win_rate >= 0.4:
            sentences.append(f"今回の{score.jockey}騎手とは{aff.total}戦{aff.wins}勝と非常に相性が良く、このコンビは信頼できる。")
        elif aff.win_rate >= 0.2:
            sentences.append(f"{score.jockey}騎手とは{aff.total}戦{aff.wins}勝・複勝率{aff.place_rate*100:.0f}%で相性は良好。")
        elif aff.place_rate >= 0.5:
            sentences.append(f"{score.jockey}騎手とのコンビで複勝率{aff.place_rate*100:.0f}%の連対実績あり。")

    # 血統
    if score.pedigree_bonus >= 8:
        sentences.append("血統的にも今回の条件（馬場・距離）への適性が高く、プラス材料。")
    elif score.pedigree_bonus >= 4:
        sentences.append("血統面でも今回条件への親和性があり、底上げ要素になっている。")

    # 展開
    if score.context_bonus >= 8:
        sentences.append("今回の展開予測では脚質的に恵まれる可能性が高く、展開利が見込める。")
    elif score.context_bonus <= -6:
        sentences.append("ペース予測的には脚質が噛み合わず、展開面では不利になりそう。")

    # 対戦相手レベル補正の解説
    if rs and hasattr(score, 'raw_stat'):
        hist_stats = None
        try:
            hist_stats = score.raw_stat
        except Exception:
            pass

    # opp_bonus情報をcommentに反映（ComprehensiveScoreにopp_bonusがあれば）
    opp_b = getattr(score, 'opp_bonus', 0)
    if opp_b >= 6:
        sentences.append("過去に重賞・G1レベルの強敵と対戦した実績があり、数字に表れない実力を秘めている。")
    elif opp_b >= 3:
        sentences.append("過去の敗戦の中に、強い相手に負けたレースが含まれており、潜在的な力は高い。")

    if not sentences:
        return "データ取得数が少なく詳細分析は限定的。当日の状態と騎手の腕に期待。"

    return "".join(sentences)
