"""
過去5年データを多次元で深掘りし、レース別の「勝ち馬の特徴」を抽出する。
- 競馬場 × 距離 × 馬場状態 ごとの「勝ち馬の脚質パターン」
- 通過順位パターン（先行/差し有利の数値化）
- スピード指数の必要水準
- 血統適性の傾向

note記事に「このコースのこの距離なら〇〇タイプが勝ちやすい」と明示する。
"""
import os, json
from glob import glob
from collections import defaultdict, Counter

PATTERN_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "deep_patterns.json")
TRAINING_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest", "all_horses_training.jsonl")


def _dist_band(d: int) -> str:
    if d <= 1200: return "短距離"
    if d <= 1600: return "マイル"
    if d <= 2000: return "中距離"
    if d <= 2400: return "中長"
    return "長距離"


def build_deep_patterns() -> dict:
    """all_horses_training.jsonl から多次元パターンを構築"""
    if not os.path.exists(TRAINING_PATH):
        return {}

    # (venue, dist_band, surface, condition) → 勝ち馬統計
    venue_dist_patterns = defaultdict(lambda: {
        "wins": 0, "winner_styles": Counter(), "winner_form_avg": 0.0,
        "winner_speed_avg": 0.0, "winner_pace_avg": 0.0, "samples": 0,
    })
    # (venue, surface) → 全体傾向
    venue_patterns = defaultdict(lambda: {
        "races": 0, "front_winrate": 0, "back_winrate": 0,
        "winner_avg_speed": 0.0, "winner_avg_form": 0.0,
    })

    with open(TRAINING_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                race = json.loads(line)
            except Exception:
                continue
            venue   = race.get("venue", "")
            surface = race.get("surface", "")
            distance = race.get("distance", 0)
            condition = "良"   # all_horses_training に condition がないのでデフォ
            dband = _dist_band(distance)

            horses = race.get("horses", [])
            winner = None
            for h in horses:
                if h.get("finish_order") == 1:
                    winner = h
                    break
            if not winner:
                continue
            wf = winner.get("factors", {})

            # 勝ち馬の脚質判定（pace/form_scoreから推測）
            pace_sc = wf.get("pace", 50)
            form_sc = wf.get("recent_form", 50)
            speed_sc = wf.get("speed_index", 50)
            # 高pace_score = 上がり脚速い = 差し系
            if pace_sc >= 65:
                style = "差し・追込型"
            elif pace_sc <= 40:
                style = "先行・逃げ型"
            else:
                style = "中団・万能型"

            # venue_dist 統計
            key = (venue, dband, surface)
            vd = venue_dist_patterns[key]
            vd["wins"] += 1
            vd["winner_styles"][style] += 1
            vd["samples"] += 1
            n = vd["samples"]
            vd["winner_form_avg"] = (vd["winner_form_avg"] * (n - 1) + form_sc) / n
            vd["winner_speed_avg"] = (vd["winner_speed_avg"] * (n - 1) + speed_sc) / n
            vd["winner_pace_avg"] = (vd["winner_pace_avg"] * (n - 1) + pace_sc) / n

            # venue 統計
            vp = venue_patterns[(venue, surface)]
            vp["races"] += 1
            if pace_sc >= 65:
                vp["back_winrate"] += 1
            elif pace_sc <= 40:
                vp["front_winrate"] += 1
            n2 = vp["races"]
            vp["winner_avg_speed"] = (vp["winner_avg_speed"] * (n2 - 1) + speed_sc) / n2
            vp["winner_avg_form"] = (vp["winner_avg_form"] * (n2 - 1) + form_sc) / n2

    # 比率化
    for vp in venue_patterns.values():
        if vp["races"] > 0:
            vp["front_winrate"] = round(vp["front_winrate"] / vp["races"] * 100, 1)
            vp["back_winrate"]  = round(vp["back_winrate"] / vp["races"] * 100, 1)
            vp["winner_avg_speed"] = round(vp["winner_avg_speed"], 1)
            vp["winner_avg_form"]  = round(vp["winner_avg_form"], 1)

    # 整形して保存
    out = {
        "venue_dist": {
            f"{k[0]}_{k[1]}_{k[2]}": {
                "samples": v["samples"],
                "winner_form_avg": round(v["winner_form_avg"], 1),
                "winner_speed_avg": round(v["winner_speed_avg"], 1),
                "winner_pace_avg": round(v["winner_pace_avg"], 1),
                "winner_styles": dict(v["winner_styles"]),
            }
            for k, v in venue_dist_patterns.items() if v["samples"] >= 3
        },
        "venue_overall": {
            f"{k[0]}_{k[1]}": v for k, v in venue_patterns.items() if v["races"] >= 5
        },
    }
    os.makedirs(os.path.dirname(PATTERN_PATH), exist_ok=True)
    with open(PATTERN_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def load_deep_patterns() -> dict:
    if not os.path.exists(PATTERN_PATH):
        return {}
    try:
        with open(PATTERN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_race_insight(venue: str, distance: int, surface: str) -> str:
    """note記事に挿入する「このコースの傾向」テキストを生成"""
    p = load_deep_patterns()
    if not p:
        return ""

    dband = _dist_band(distance)
    vd_key = f"{venue}_{dband}_{surface}"
    vd = p.get("venue_dist", {}).get(vd_key, {})
    vp = p.get("venue_overall", {}).get(f"{venue}_{surface}", {})

    parts = []
    if vd:
        styles = vd.get("winner_styles", {})
        if styles:
            top_style = max(styles.items(), key=lambda x: x[1])
            total = sum(styles.values())
            ratio = round(top_style[1] / total * 100)
            parts.append(f"{venue}の{surface}{dband}（過去{vd.get('samples')}レース分析）：勝ち馬の**{ratio}%が{top_style[0]}**。")
            parts.append(
                f"勝ち馬平均はスピード指数 {vd.get('winner_speed_avg'):.0f}・近走フォーム {vd.get('winner_form_avg'):.0f}・上がり脚 {vd.get('winner_pace_avg'):.0f}。"
            )
    if vp:
        front_r = vp.get("front_winrate", 0)
        back_r  = vp.get("back_winrate", 0)
        if front_r > back_r + 10:
            parts.append(f"{venue}{surface}は全体的に**先行有利**（先行勝率 {front_r}% vs 差し {back_r}%）。逃げ・先行馬を中心に据える展開。")
        elif back_r > front_r + 10:
            parts.append(f"{venue}{surface}は**差し有利**な傾向（差し勝率 {back_r}% vs 先行 {front_r}%）。末脚のあるタイプを重視。")
        else:
            parts.append(f"{venue}{surface}は脚質バイアスが小さい。素直に評点順位に従う方針。")
    return "\n".join(parts)


if __name__ == "__main__":
    p = build_deep_patterns()
    print(f"パターン構築完了: venue_dist={len(p.get('venue_dist', {}))}, venue_overall={len(p.get('venue_overall', {}))}")
    print(get_race_insight("東京", 1600, "芝"))
