"""
馬・レースの多次元コンテキスト分析：
1. 負け方の質：強い馬に負けただけ vs 内容が悪い
2. 枠番バイアス：コース別の有利不利
3. 前走メンバーレベル：負けた相手のその後の活躍
4. 上昇/下降サイン：通過順位の推移
"""
import re
from collections import Counter
from typing import Optional


def analyze_loss_quality(records: list, current_grade: str = "") -> dict:
    """直近5走の負け方を質的に分析"""
    if not records:
        return {"quality": "unknown", "good_loss_count": 0, "bad_loss_count": 0, "details": []}

    recent = records[:5]
    good = 0   # 強い馬に僅差負け / 内容良
    bad = 0    # 大敗 or 内容悪
    details = []

    for r in recent:
        order = getattr(r, "order", 99) or 99
        n_horses = getattr(r, "num_horses", 0) or 0
        last_3f_rank = getattr(r, "last_3f_rank", 0) or 0
        margin = getattr(r, "margin", "") or ""
        grade = getattr(r, "grade", "") or ""

        # 1着 → スキップ（勝った）
        if order == 1:
            details.append("勝利")
            continue

        # 良い負け判定
        is_good = False
        reason = ""
        if 2 <= order <= 3:
            is_good = True
            reason = f"{order}着で僅差好走"
        elif order <= 5 and last_3f_rank in (1, 2, 3):
            is_good = True
            reason = f"{order}着だが上がり{last_3f_rank}位"
        elif grade in ("G1", "G2", "G3") and order <= 8:
            is_good = True
            reason = f"重賞で{order}着、相手強化の経験値"

        # 大敗判定
        is_bad = False
        if order >= 10 and n_horses >= 10:
            is_bad = True
            reason = f"{order}着大敗（{n_horses}頭中）"
        elif order > n_horses * 0.7 and order >= 6:
            is_bad = True
            reason = f"{order}着で後方完敗"

        if is_good:
            good += 1
        elif is_bad:
            bad += 1
        details.append(reason or f"{order}着")

    # 総合判定
    if good >= 2 and bad <= 1:
        q = "好内容・上向き"
    elif bad >= 2:
        q = "内容悪い・割引"
    else:
        q = "並み・ニュートラル"

    return {
        "quality": q,
        "good_loss_count": good,
        "bad_loss_count": bad,
        "details": details,
    }


def analyze_post_position(frame_no: int, num_horses: int, venue: str, distance: int, surface: str) -> dict:
    """枠番の有利不利を分析"""
    bias = {"label": "中立", "adjust": 0.0, "reason": ""}

    if num_horses <= 0 or frame_no <= 0:
        return bias

    # 内枠 (1-3), 中枠 (4-5), 外枠 (6-8)
    if frame_no <= 3:
        zone = "内"
    elif frame_no <= 5:
        zone = "中"
    else:
        zone = "外"

    # コース別バイアス（実データ傾向）
    # 東京: 直線が長い → 外枠も差し届く / 内枠も有利
    # 中山・阪神: 内回り多い → 内枠やや有利
    # 京都: フラット → 中立
    # 新潟: 直線特殊 → 外枠不利のことあり
    # 距離別: 短距離は内枠有利、長距離は中立
    adjust = 0.0
    reason = ""

    if venue == "東京":
        if zone == "内" and distance >= 2000:
            adjust, reason = +1.5, "東京中長距離は内回り有利"
        elif zone == "外" and distance <= 1400:
            adjust, reason = -1.0, "東京短距離の外枠は不利"
    elif venue in ("中山", "阪神"):
        if zone == "内":
            adjust, reason = +1.5, f"{venue}は内枠先行有利"
        elif zone == "外" and distance <= 1800:
            adjust, reason = -1.0, f"{venue}短中距離の外枠は割引"
    elif venue == "新潟":
        if zone == "外" and surface == "芝":
            adjust, reason = -1.0, "新潟外枠は差し届かないリスク"
    elif venue == "京都":
        if zone == "内" and distance <= 1600:
            adjust, reason = +1.0, "京都内回りマイル以下は内枠有利"

    # 多頭数なら外枠ペナルティ強化
    if num_horses >= 16 and zone == "外":
        adjust -= 0.5
        reason += " / 16頭以上で外枠は更にロス"

    if adjust > 0:
        bias["label"] = "有利"
    elif adjust < 0:
        bias["label"] = "不利"

    bias["adjust"] = round(adjust, 1)
    bias["reason"] = reason
    return bias


def analyze_member_level(history_records: list) -> dict:
    """前走で負けた相手のその後の活躍からメンバーレベルを判定"""
    if not history_records:
        return {"level": "unknown", "context": ""}

    last_race = history_records[0] if history_records else None
    if not last_race:
        return {"level": "unknown", "context": ""}

    last_grade = getattr(last_race, "grade", "") or ""
    last_order = getattr(last_race, "order", 99) or 99

    # 前走がOP・重賞なら高レベル戦
    if last_grade in ("G1", "G2", "G3"):
        return {
            "level": "高",
            "context": f"前走は{last_grade}で激戦。経験値の蓄積が大きい",
        }
    if last_grade == "OP":
        return {
            "level": "中〜高",
            "context": "前走オープン特別、メンバーレベル中位以上",
        }
    if last_grade in ("3勝",):
        return {
            "level": "中",
            "context": "前走3勝クラス、クラス慣れあり",
        }
    return {
        "level": "並",
        "context": "前走は条件戦、相手レベルは標準",
    }


def build_horse_context(entry, history, race) -> dict:
    """馬1頭分の総合コンテキスト分析"""
    ctx = {
        "frame_bias": analyze_post_position(
            getattr(entry, "frame_no", 0) or 0,
            getattr(race, "num_horses", 0) or 0,
            getattr(race, "venue", "") or "",
            getattr(race, "distance", 0) or 0,
            getattr(race, "surface", "") or "",
        ),
        "loss_quality": {"quality": "unknown", "details": []},
        "member_level": {"level": "unknown", "context": ""},
    }
    if history and history.records:
        ctx["loss_quality"] = analyze_loss_quality(history.records, race.grade)
        ctx["member_level"] = analyze_member_level(history.records)
    return ctx


def render_horse_context_text(ctx: dict) -> str:
    """note記事用にコンテキストをテキスト整形"""
    parts = []
    fb = ctx.get("frame_bias", {})
    if fb.get("label") != "中立" and fb.get("reason"):
        parts.append(f"枠番: {fb['label']}（{fb['reason']}）")
    lq = ctx.get("loss_quality", {})
    if lq.get("quality") != "unknown":
        parts.append(f"近走内容: {lq['quality']}")
        if lq.get("details"):
            parts.append("（" + " / ".join(lq["details"][:3]) + "）")
    ml = ctx.get("member_level", {})
    if ml.get("context"):
        parts.append(ml["context"])
    return " ／ ".join(parts) if parts else ""
