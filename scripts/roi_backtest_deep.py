"""
深度EV分析の ROI バックテスト。

all_horses_training.jsonl に対し、
- 旧: 単純 final_score の上位
- 新: アンサンブル確率 + Plackett-Luce + Grade判定 + Kelly配分

を単勝・複勝ベースで比較。
払戻はオッズが 0 のレースをスキップ。
"""
import json, os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TRAIN = os.path.join(os.path.dirname(__file__), "..", "data", "backtest", "all_horses_training.jsonl")


def softmax_prob(items):
    base = max(v for _, v in items) if items else 0
    exps = [(no, math.exp((v - base) / 6.0)) for no, v in items]
    z = sum(e for _, e in exps) or 1.0
    return {no: e / z for no, e in exps}


def implied_prob(odds_map, overround=0.80):
    raw = {no: overround / o for no, o in odds_map.items() if o and o > 0}
    z = sum(raw.values()) or 1.0
    return {no: p / z for no, p in raw.items()}


def pl_quinella(pa, pb):
    if pa <= 0 or pb <= 0: return 0
    return min(0.55, pa * pb / max(1e-6, 1 - pa) + pb * pa / max(1e-6, 1 - pb))


def run():
    if not os.path.exists(TRAIN):
        print("training jsonl not found")
        return
    old_stake = old_ret = 0
    new_stake = new_ret = 0
    new_skipped = 0
    races = 0
    races_with_odds = 0

    with open(TRAIN, encoding="utf-8") as f:
        for line in f:
            try:
                race = json.loads(line)
            except Exception:
                continue
            horses = race.get("horses", [])
            if len(horses) < 4: continue
            races += 1

            score_items = [(h["horse_no"], h.get("final_score", 0)) for h in horses]
            score_p = softmax_prob(score_items)
            odds_map = {h["horse_no"]: h.get("odds", 0) for h in horses}
            if not any(o > 0 for o in odds_map.values()):
                continue
            races_with_odds += 1

            market_p = implied_prob(odds_map)
            # アンサンブル（簡易：scoreとmarket半々、MLは未利用）
            ens = {n: 0.6 * score_p.get(n, 0) + 0.4 * market_p.get(n, 0) for n in odds_map}
            zs = sum(ens.values()) or 1.0
            ens = {n: p / zs for n, p in ens.items()}
            edges = {n: ens[n] / market_p[n] - 1 if market_p.get(n) else 0 for n in ens}

            winner = next((h for h in horses if h.get("won")), None)
            placed_nos = {h["horse_no"] for h in horses if h.get("placed")}

            # --- 旧: final_score 上位の単勝のみ 100円 ---
            top_no = max(score_items, key=lambda x: x[1])[0]
            old_stake += 100
            if winner and winner["horse_no"] == top_no:
                old_stake_o = odds_map.get(top_no, 0)
                old_ret += int(old_stake_o * 100)

            # --- 新: グレード判定 + Kelly ---
            max_edge_no = max(edges, key=edges.get) if edges else None
            max_edge = edges.get(max_edge_no, 0) if max_edge_no else 0
            max_ev = max((ens[n] * odds_map.get(n, 0)) for n in ens) if ens else 0

            # Grade判定
            if max_edge >= 0.40 and max_ev >= 1.5:   grade = "S"; budget = 3000
            elif max_edge >= 0.25 and max_ev >= 1.3: grade = "A"; budget = 2000
            elif max_edge >= 0.15 and max_ev >= 1.15: grade = "B"; budget = 1200
            elif max_edge >= 0.05 and max_ev >= 1.05: grade = "C"; budget = 600
            else: grade = "D"; budget = 0

            if grade == "D":
                new_skipped += 1
                continue

            # 単勝候補（EV >= 1.05 & edge >= 5%）
            win_cands = []
            for n, p in ens.items():
                o = odds_map.get(n, 0)
                if not o: continue
                ev = p * o
                ed = edges.get(n, 0)
                if ev >= 1.05 and ed >= 0.05:
                    win_cands.append((ev, n))
            win_cands.sort(reverse=True)
            win_cands = win_cands[:2]
            if not win_cands:
                continue

            # 予算の単勝シェア = 25%、EV 比例
            win_budget = budget * 0.5  # 単純化のため単勝に50%
            wsum = sum(max(0.05, ev - 0.95) for ev, _ in win_cands) or 1.0
            for ev, n in win_cands:
                w = max(0.05, ev - 0.95)
                yen = int(round(win_budget * (w / wsum) / 100)) * 100
                if yen < 100: continue
                new_stake += yen
                if winner and winner["horse_no"] == n:
                    new_ret += int(odds_map.get(n, 0) * yen)

    print(f"races total: {races} / with odds: {races_with_odds}")
    print(f"新ロジック スキップ: {new_skipped} ({new_skipped/max(1,races_with_odds)*100:.1f}%)")
    print()
    print(f"=== 旧 (final_score 上位単勝 100円フラット) ===")
    print(f"  投票: {old_stake:,}円   回収: {old_ret:,}円")
    print(f"  ROI:  {old_ret/max(1,old_stake)*100:.1f}%")
    print()
    print(f"=== 新 (アンサンブル + Grade判定 + Kelly配分) ===")
    print(f"  投票: {new_stake:,}円   回収: {new_ret:,}円")
    print(f"  ROI:  {new_ret/max(1,new_stake)*100:.1f}%")
    print()
    diff = (new_ret/max(1,new_stake) - old_ret/max(1,old_stake)) * 100
    print(f"改善幅: {diff:+.1f}pt")


if __name__ == "__main__":
    run()
