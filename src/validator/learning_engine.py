"""
学習エンジン：週次レビュー結果を「次回投稿に効かせる学び」へ変換する。

入力: バックテスト/週次レビューのレコード
出力:
  1. data/learnings.json
     - factor_adjustments: スコア要素ごとの倍率（敗因頻度ベース）
     - venue_adjustments: 競馬場別の信頼度倍率（精度低い場は本命確信度を下げる）
     - bet_type_roi: 直近の券種別ROI（投資配分の参考）
     - top_lessons: 次回投稿のナラティブで言及できる学び3点
     - generated_at: 生成日時

note_formatter / recommendation がこれを読んで適用する。
"""
import os, json
from datetime import datetime
from collections import Counter, defaultdict

LEARNINGS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "learnings.json"
)

# 敗因要因 → スコア重みキーへのマッピング
REASON_TO_WEIGHT = {
    "近走フォーム": "recent_form",
    "馬場適性":   "surface",
    "距離適性":   "distance",
    "スピード指数": "speed_index",
    "クラス実績":  "class_change",
    "コース適性":  "venue",
    "馬場状態":   "condition",
    "休養間隔":   "rest",
    "上がり適性":  "pace",
    "馬体重安定":  "weight_stab",
}


def build_learnings(records: list[dict], roi_by_kind: dict | None = None) -> dict:
    """
    records: [{venue, grade, honmei_win, honmei_place, defeat_reason, ...}, ...]
    roi_by_kind: {"単勝": {"stake":..., "return":...}, ...} (任意)
    """
    n = len(records)
    if n == 0:
        return {}

    # === 1. 敗因頻度 → 要素別倍率 ===
    miss_reasons = Counter(
        r.get("defeat_reason", "") for r in records
        if not r.get("honmei_win") and r.get("defeat_reason")
    )
    factor_adjust = {}
    if miss_reasons:
        total_miss = sum(miss_reasons.values()) or 1
        for reason, cnt in miss_reasons.items():
            key = REASON_TO_WEIGHT.get(reason)
            if not key:
                continue
            # 敗因比率20%超なら +10%、10〜20%なら +5%、それ以下は据え置き
            ratio = cnt / total_miss
            if ratio >= 0.20:
                factor_adjust[key] = 1.10
            elif ratio >= 0.10:
                factor_adjust[key] = 1.05

    # === 2. 競馬場別精度 → 信頼度倍率 ===
    venue_stats = defaultdict(lambda: {"total": 0, "wins": 0, "places": 0})
    for r in records:
        v = r.get("venue") or ""
        if not v:
            continue
        venue_stats[v]["total"] += 1
        if r.get("honmei_win"):   venue_stats[v]["wins"] += 1
        if r.get("honmei_place"): venue_stats[v]["places"] += 1

    venue_adjust = {}
    for v, d in venue_stats.items():
        if d["total"] < 5:
            continue
        wr = d["wins"] / d["total"]
        pr = d["places"] / d["total"]
        # 全体平均より明らかに低い場：信頼度を下げる（=他の馬への流し本数を増やす推奨）
        if wr < 0.15 and pr < 0.30:
            venue_adjust[v] = {"confidence": 0.85, "expand_picks": True, "win_rate": round(wr*100,1), "place_rate": round(pr*100,1)}
        elif wr >= 0.30 and pr >= 0.55:
            venue_adjust[v] = {"confidence": 1.10, "expand_picks": False, "win_rate": round(wr*100,1), "place_rate": round(pr*100,1)}

    # === 3. クラス別精度 ===
    grade_stats = defaultdict(lambda: {"total": 0, "wins": 0})
    for r in records:
        g = r.get("grade") or ""
        grade_stats[g]["total"] += 1
        if r.get("honmei_win"): grade_stats[g]["wins"] += 1

    weak_grades = [
        g for g, d in grade_stats.items()
        if d["total"] >= 3 and d["wins"]/d["total"] < 0.15
    ]

    # === 4. 券種別ROI（任意） ===
    bet_roi = {}
    if roi_by_kind:
        for kind, d in roi_by_kind.items():
            stake = d.get("stake", 0)
            ret   = d.get("return", 0)
            if stake > 0:
                bet_roi[kind] = {
                    "stake": stake, "return": ret,
                    "roi": round(ret / stake * 100, 1),
                    "hits": d.get("hits", 0), "n": d.get("n", 0),
                }

    # === 5. 次回投稿で言及する「学び」3点 ===
    lessons = []
    if miss_reasons:
        top_reason, cnt = miss_reasons.most_common(1)[0]
        lessons.append(
            f"先週の最大の外れ要因は『{top_reason}』（{cnt}件）。今週は当該要素の重みを引き上げて再評価しています。"
        )
    if venue_adjust:
        weak = [v for v, d in venue_adjust.items() if d["confidence"] < 1.0]
        if weak:
            lessons.append(
                f"先週は{','.join(weak)}での精度が低調でした。今週はそれら開催で穴目を厚めにケアします。"
            )
    if bet_roi:
        best_kind = max(bet_roi.items(), key=lambda x: x[1]["roi"])
        if best_kind[1]["roi"] >= 100:
            lessons.append(
                f"先週は{best_kind[0]}が回収率{best_kind[1]['roi']}%と好調。今週も同戦略を継続します。"
            )
        else:
            worst = min(bet_roi.items(), key=lambda x: x[1]["roi"])
            lessons.append(
                f"先週の券種別ROIで最も損したのは{worst[0]}（{worst[1]['roi']}%）。今週はEVベースで投資配分を厳選しています。"
            )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_races": n,
        "factor_adjustments": factor_adjust,
        "venue_adjustments": venue_adjust,
        "weak_grades": weak_grades,
        "bet_type_roi": bet_roi,
        "top_lessons": lessons[:3],
    }


def save_learnings(learnings: dict):
    os.makedirs(os.path.dirname(LEARNINGS_PATH), exist_ok=True)
    with open(LEARNINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(learnings, f, ensure_ascii=False, indent=2)


def load_learnings() -> dict:
    if not os.path.exists(LEARNINGS_PATH):
        return {}
    try:
        with open(LEARNINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# === 週次トレンドトラッカー（精度推移を記録） ===
TREND_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "weekly_trend.json"
)


def record_weekly_metrics(week_label: str, metrics: dict):
    """毎週の的中率/回収率/学習結果を時系列で蓄積"""
    history = []
    if os.path.exists(TREND_PATH):
        try:
            with open(TREND_PATH, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append({"week": week_label, "metrics": metrics})
    history = history[-52:]  # 直近1年分のみ保持
    os.makedirs(os.path.dirname(TREND_PATH), exist_ok=True)
    with open(TREND_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_trend_summary() -> dict:
    """直近の精度推移を返す（投稿のアピール文用）"""
    if not os.path.exists(TREND_PATH):
        return {}
    try:
        with open(TREND_PATH, encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        return {}
    if len(history) < 2:
        return {"weeks": len(history), "history": history}

    last = history[-1]["metrics"]
    prev = history[-2]["metrics"]
    return {
        "weeks": len(history),
        "current_win_rate": last.get("honmei_win_rate", 0),
        "current_place_rate": last.get("honmei_place_rate", 0),
        "current_exacta": last.get("exacta_hit_rate", 0),
        "current_trio": last.get("trifecta_hit_rate", 0),
        "delta_win": last.get("honmei_win_rate", 0) - prev.get("honmei_win_rate", 0),
        "delta_place": last.get("honmei_place_rate", 0) - prev.get("honmei_place_rate", 0),
        "improving": last.get("honmei_place_rate", 0) > prev.get("honmei_place_rate", 0),
    }


def auto_tune_lr(trend: dict) -> float:
    """
    トレンド改善状況に応じて次回の学習率（重み調整の積極性）を決定。
    悪化していたら積極的に調整、改善していたら現状維持寄りに。
    """
    if not trend or trend.get("weeks", 0) < 2:
        return 0.020  # デフォルト
    delta = trend.get("delta_place", 0)
    if delta < -3:    # 複勝率3%以上低下 → 緊急調整
        return 0.040
    if delta < 0:     # 微減
        return 0.025
    if delta > 3:     # 大幅改善 → 維持
        return 0.010
    return 0.015      # 標準


def apply_factor_adjustments(weights: dict, learnings: dict) -> dict:
    """学習結果のfactor_adjustmentsを既存重みに掛ける（保存はしない、戻り値で渡す）"""
    adj = learnings.get("factor_adjustments", {})
    if not adj:
        return weights
    new = dict(weights)
    for k, mult in adj.items():
        if k in new:
            new[k] = round(new[k] * mult, 4)
    # 正規化
    s = sum(new.values()) or 1.0
    return {k: round(v / s, 4) for k, v in new.items()}
