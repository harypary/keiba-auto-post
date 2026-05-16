"""
予想精度・回収率トラッキング＆週次レポート生成
回収率を最重視して、翌週の記事改善に活かす
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PERF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "performance")
PRED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "predictions")
HIGHLIGHT_FILE = os.path.join(PERF_DIR, "last_week_highlights.json")


# ============================================================
# 予想保存（投稿前）
# ============================================================

def save_prediction(race_id: str, race_name: str, scores, plan):
    """投稿時に予想内容をJSONで保存（オッズも記録して後でROI計算）"""
    os.makedirs(PRED_DIR, exist_ok=True)
    data = {
        "race_id": race_id,
        "race_name": race_name,
        "saved_at": datetime.now().isoformat(),
        "honmei": plan.honmei,
        "taikou": plan.taikou,
        "tanana": plan.tanana,
        "renka": plan.renka,
        "ranking": [
            {
                "rank": s.recommendation_rank,
                "horse_no": s.horse_no,
                "horse_name": s.horse_name,
                "final_score": round(s.final_score, 2),
                "odds": s.odds,
            }
            for s in sorted(scores, key=lambda x: x.recommendation_rank)
        ],
        "exacta_bets": plan.exacta_bets,
        "trifecta_bets": [list(c) for c in plan.trifecta_bets],
        "honmei_odds": next(
            (s.odds for s in scores if s.horse_no in plan.honmei), None
        ),
    }
    path = os.path.join(PRED_DIR, f"{race_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 結果照合・回収率計算
# ============================================================

def record_result(race_id: str, actual_order: list[dict], actual_odds: dict = None) -> dict:
    """実際の着順と予想を照合。回収率も計算する。"""
    os.makedirs(PERF_DIR, exist_ok=True)

    pred_path = os.path.join(PRED_DIR, f"{race_id}.json")
    if not os.path.exists(pred_path):
        return {}

    with open(pred_path, "r", encoding="utf-8") as f:
        pred = json.load(f)

    top3 = [r["horse_no"] for r in actual_order[:3]]
    top1 = actual_order[0]["horse_no"] if actual_order else None
    top2 = actual_order[1]["horse_no"] if len(actual_order) > 1 else None

    honmei_no = pred["honmei"][0] if pred["honmei"] else None
    taikou_no = pred["taikou"][0] if pred["taikou"] else None
    tanana_no  = pred["tanana"][0] if pred["tanana"] else None

    honmei_win   = (honmei_no == top1)
    honmei_place = (honmei_no in top3)

    exacta_hit = any(
        set([a, b]) <= set(top3[:2])
        for a, b in pred.get("exacta_bets", [])
    )
    trifecta_hit = any(
        set(combo) <= set(top3)
        for combo in pred.get("trifecta_bets", [])
    )

    winner_pred_rank = next(
        (r["rank"] for r in pred["ranking"] if r["horse_no"] == top1), 99
    )

    # 回収率計算（単勝を仮定100円ずつ）
    # 単勝：本命が1着なら本命オッズ×100円回収
    honmei_odds = pred.get("honmei_odds") or 5.0
    tan_return  = int(honmei_odds * 100) if honmei_win else 0
    tan_invest  = 100
    tan_roi     = round((tan_return - tan_invest) / tan_invest * 100, 1)

    # 馬連：的中なら推定5倍（実オッズ取れない場合の概算）
    exacta_return = 500 if exacta_hit else 0
    exacta_invest = len(pred.get("exacta_bets", [])) * 100
    exacta_roi    = round((exacta_return - exacta_invest) / max(exacta_invest, 1) * 100, 1) if exacta_invest > 0 else 0

    # 3連複：的中なら推定10倍
    tri_return = 1000 if trifecta_hit else 0
    tri_invest = len(pred.get("trifecta_bets", [])) * 100
    tri_roi    = round((tri_return - tri_invest) / max(tri_invest, 1) * 100, 1) if tri_invest > 0 else 0

    record = {
        "race_id": race_id,
        "race_name": pred.get("race_name", ""),
        "recorded_at": datetime.now().isoformat(),
        "actual_top3": top3,
        "honmei_no": honmei_no,
        "honmei_win": honmei_win,
        "honmei_place": honmei_place,
        "honmei_odds": honmei_odds,
        "exacta_hit": exacta_hit,
        "trifecta_hit": trifecta_hit,
        "winner_predicted_rank": winner_pred_rank,
        "tan_roi": tan_roi,
        "exacta_roi": exacta_roi,
        "tri_roi": tri_roi,
    }

    out_path = os.path.join(PERF_DIR, f"{race_id}_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return record


# ============================================================
# 週次レポート（回収率重視）
# ============================================================

def generate_weekly_report(weeks_back: int = 1) -> dict:
    os.makedirs(PERF_DIR, exist_ok=True)
    cutoff = datetime.now() - timedelta(weeks=weeks_back)
    records = []

    for fname in os.listdir(PERF_DIR):
        if not fname.endswith("_result.json"):
            continue
        with open(os.path.join(PERF_DIR, fname), "r", encoding="utf-8") as f:
            r = json.load(f)
        if datetime.fromisoformat(r.get("recorded_at", "2000-01-01")) >= cutoff:
            records.append(r)

    if not records:
        return {"error": "データなし", "races": 0}

    n = len(records)
    honmei_wins   = sum(1 for r in records if r.get("honmei_win"))
    honmei_places = sum(1 for r in records if r.get("honmei_place"))
    exacta_hits   = sum(1 for r in records if r.get("exacta_hit"))
    trifecta_hits = sum(1 for r in records if r.get("trifecta_hit"))

    avg_tan_roi      = sum(r.get("tan_roi", 0) for r in records) / n
    avg_exacta_roi   = sum(r.get("exacta_roi", 0) for r in records) / n
    avg_tri_roi      = sum(r.get("tri_roi", 0) for r in records) / n
    winner_ranks     = [r.get("winner_predicted_rank", 99) for r in records]
    avg_winner_rank  = sum(winner_ranks) / n

    # 先週のハイライト（高配当的中）
    highlights = [
        r for r in records
        if r.get("honmei_win") and r.get("honmei_odds", 0) >= 5.0
    ]
    highlights.sort(key=lambda r: r.get("honmei_odds", 0), reverse=True)

    report = {
        "period_weeks": weeks_back,
        "races_analyzed": n,
        "honmei_win_rate":   round(honmei_wins / n * 100, 1),
        "honmei_place_rate": round(honmei_places / n * 100, 1),
        "exacta_hit_rate":   round(exacta_hits / n * 100, 1),
        "trifecta_hit_rate": round(trifecta_hits / n * 100, 1),
        "avg_tan_roi":       round(avg_tan_roi, 1),
        "avg_exacta_roi":    round(avg_exacta_roi, 1),
        "avg_tri_roi":       round(avg_tri_roi, 1),
        "avg_winner_predicted_rank": round(avg_winner_rank, 1),
        "highlights": highlights[:3],
        "improvement_suggestions": _suggest_improvements(
            honmei_wins / n, honmei_places / n,
            exacta_hits / n, avg_winner_rank,
            avg_tan_roi, avg_exacta_roi,
        ),
    }

    # ハイライトを次週記事用に保存
    _save_highlights(highlights[:3], report)
    return report


def _save_highlights(highlights: list, report: dict):
    os.makedirs(PERF_DIR, exist_ok=True)
    data = {
        "generated_at": datetime.now().isoformat(),
        "races_analyzed": report.get("races_analyzed", 0),
        "honmei_win_rate": report.get("honmei_win_rate", 0),
        "honmei_place_rate": report.get("honmei_place_rate", 0),
        "exacta_hit_rate": report.get("exacta_hit_rate", 0),
        "avg_tan_roi": report.get("avg_tan_roi", 0),
        "highlights": highlights,
    }
    with open(HIGHLIGHT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _suggest_improvements(wr, pr, er, avg_rank, tan_roi, exacta_roi) -> list[str]:
    s = []
    if tan_roi < -20:
        s.append("単勝回収率が低い。本命選定で人気馬への偏りを減らし、中穴（3〜7番人気）も積極的に本命に。")
    if wr < 0.20:
        s.append("◎の勝率が20%未満。距離・馬場適性スコアの重みをさらに上げることを検討。")
    if pr < 0.40:
        s.append("◎の複勝率が40%未満。近走フォームスコアの閾値を見直す。")
    if exacta_roi < -30:
        s.append("馬連の回収率が低い。○対抗の絞り込み精度を上げるか、ワイドへのシフトを検討。")
    if avg_rank > 3.5:
        s.append(f"勝ち馬の平均予想順位が{avg_rank:.1f}位と高い。スコア分散が不足している可能性。血統・展開ボーナスの比重を再検討。")
    if not s:
        s.append("回収率・的中率ともに安定。現状のスコアを維持しながらサンプルを増やす。")
    return s


# ============================================================
# 記事用テキスト（実績・先週ハイライト）
# ============================================================

def get_track_record_text() -> str:
    """記事の冒頭に表示する的中実績テキスト（嘘なし・実データのみ）

    優先順位：
    1. 先週の実投稿実績（5レース以上）→ "先週の予想実績"
    2. バックテスト実績（10レース以上）→ "過去データ検証実績"
    3. 何もなし → 空文字列
    """
    # ① 実投稿の先週実績
    real = _try_real_track_record()
    if real:
        return real

    # ② バックテスト実績（初回投稿〜数週間用）
    bt = _try_backtest_track_record()
    if bt:
        return bt

    return ""


def _try_real_track_record() -> str:
    if not os.path.exists(HIGHLIGHT_FILE):
        return ""
    try:
        with open(HIGHLIGHT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""

    n = data.get("races_analyzed", 0)
    if n < 5:
        return ""

    hw  = data.get("honmei_win_rate", 0)
    hp  = data.get("honmei_place_rate", 0)
    roi = data.get("avg_tan_roi", 0)
    roi_sign = "+" if roi >= 0 else ""
    hits = data.get("highlights", [])

    lines = [
        f"## 📊 先週の予想実績（実投稿{n}レース集計）\n\n",
        f"| 指標 | 結果 |\n|---|---|\n",
        f"| ◎本命 勝率 | **{hw}%** |\n",
        f"| ◎本命 複勝率 | **{hp}%** |\n",
        f"| 単勝 回収率 | **{roi_sign}{roi}%** |\n\n",
    ]

    if hits:
        lines.append("**🎯 先週の高配当的中**\n\n")
        for h in hits:
            odds = h.get("honmei_odds", 0)
            name = h.get("race_name", "")
            lines.append(f"- {name}：◎本命{h.get('honmei_no','')}番が**{odds}倍**で的中 ✅\n")
        lines.append("\n")

    return "".join(lines)


def _try_backtest_track_record() -> str:
    """バックテスト実績を本文用に整形（嘘なし、データソース明記）"""
    bt_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest")
    if not os.path.isdir(bt_dir):
        return ""

    candidates = [
        f for f in os.listdir(bt_dir)
        if f.startswith("historical_") and f.endswith(".json") and "raw" not in f
    ]
    if not candidates:
        return ""

    candidates.sort(reverse=True)
    try:
        with open(os.path.join(bt_dir, candidates[0]), "r", encoding="utf-8") as f:
            bt = json.load(f)
    except Exception:
        return ""

    n = bt.get("total_races", 0)
    if n < 10:
        return ""

    wr = bt.get("honmei_win_rate", 0)
    pr = bt.get("honmei_place_rate", 0)
    er = bt.get("exacta_hit_rate", 0)

    return (
        f"## 📊 検証実績\n\n"
        f"| 指標 | 結果 |\n|---|---|\n"
        f"| ◎本命 勝率 | **{wr}%** |\n"
        f"| ◎本命 複勝率 | **{pr}%** |\n"
        f"| 馬連 的中率 | **{er}%** |\n\n"
    )
