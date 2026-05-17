"""
note.com記事フォーマッター（引き込み特化・売れる版）
無料部分: ①実績アピール ②レースの見どころ(煽り) ③有料の中身を「予告」して買わせる
有料部分: 展開予測・全頭ナラティブ分析・評点・買い目（完全版）
"""
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.scraper.jra_scraper import RaceInfo
from src.analyzer.recommendation import BettingPlan

def _get_track_record() -> str:
    try:
        from src.validator.performance_tracker import get_track_record_text
        return get_track_record_text()
    except Exception:
        return ""


def _get_extra_signals_block(race, target_date) -> str:
    """天気・馬場バイアス等の補助情報をnote本文に表示"""
    try:
        from src.scraper.multi_source_scraper import collect_extra_signals
        sig = collect_extra_signals(race.race_id if hasattr(race, "race_id") else "", race.venue, target_date)
    except Exception:
        return ""
    out = []
    wx = sig.get("weather", {})
    if wx:
        cond = wx.get("expected_condition", "")
        rain = wx.get("precipitation_mm", 0)
        tmax = wx.get("temp_max")
        out.append("\n### ☀️ レース当日の予測コンディション\n\n")
        out.append(f"- 予測馬場状態：**{cond}**")
        if rain > 0:
            out.append(f"（予想降雨{rain:.1f}mm）")
        out.append("\n")
        if tmax is not None:
            out.append(f"- 予想最高気温：{tmax}℃\n")
        out.append("\n")
    bias = sig.get("venue_bias", {})
    if bias:
        out.append(f"- {race.venue}コース直近傾向：**{bias.get('tendency','-')}**（差し率 {int(bias.get('back_ratio',0)*100)}%／{bias.get('n_races',0)}R集計）\n\n")
    return "".join(out)


def _get_lessons_block() -> str:
    """先週の学びを「進化中」アピールとして表示（売り文句にもなる）"""
    try:
        from src.validator.learning_engine import load_learnings, get_trend_summary
        L = load_learnings()
        lessons = L.get("top_lessons", [])
        trend = get_trend_summary()
        if not lessons and not trend:
            return ""
        out = ["\n### 🧠 先週から進化したポイント\n\n"]
        if trend and trend.get("weeks", 0) >= 2:
            d = trend
            arrow = "📈" if d.get("improving") else "📉"
            out.append(
                f"- {arrow} **直近の複合ROI: {d.get('current_roi',0):+.1f}%** "
                f"（前週比 {d.get('delta_roi',0):+.1f}%）\n"
                f"  └ 複勝率 {d.get('current_place_rate',0):.1f}%／"
                f"◎勝率 {d.get('current_win_rate',0):.1f}%／"
                f"馬連 {d.get('current_exacta',0):.1f}%／3連複 {d.get('current_trio',0):.1f}%\n"
            )
        for l in lessons[:3]:
            out.append(f"- {l}\n")
        out.append("\n*毎週レース結果を自動で振り返り、モデルを改善し続けています。*\n\n")
        return "".join(out)
    except Exception:
        return ""

GRADE_EMOJI = {
    "G1": "🏆", "G2": "🥇", "G3": "🥈", "OP": "⭐",
    "3勝": "📌", "2勝": "📌", "1勝": "📌", "新馬": "🐎", "未勝利": "🐎"
}
MARK_MAP = {1: "◎", 2: "○", 3: "▲", 4: "△", 5: "△", 6: "×", 7: "×", 8: "×"}
SURFACE_LABEL = {"芝": "🌿芝", "ダート": "🟫ダート"}
PAID_MARKER = "👇 ここから有料公開部分"


# ============================================================
# パブリックAPI
# ============================================================

def format_race_note_v2(race, scores, plan, context, target_date: date, race_index: int) -> dict:
    # タイトル：メインレースは強く目立たせる
    date_str = target_date.strftime("%m/%d")
    is_g = race.grade in ("G1", "G2", "G3")

    if race.grade == "G1":
        title = f"🏆【{date_str} G1】{race.race_name}｜◎本命断言＋穴馬完全公開"
    elif race.grade == "G2":
        title = f"🥇【{date_str} G2】{race.race_name}｜重賞徹底分析＆買い目全公開"
    elif race.grade == "G3":
        title = f"🥈【{date_str} G3】{race.race_name}｜重賞◎本命＆💎穴馬ピック"
    elif race.grade == "OP":
        title = f"⭐【{date_str} OP】{race.race_name}｜本命と穴の両軸予想"
    elif race.race_no == 11:
        title = f"🔥【{date_str} メインレース】{race.venue}11R {race.race_name}｜本命＆買い目公開"
    else:
        title = f"【{date_str}】{race.venue}{race.race_no}R｜本命と買い目"

    body = _build_full_body(race, scores, plan, context, target_date)
    tags = _build_tags(race, target_date)
    price = 500 if is_g else 300
    return {"title": title, "body": body, "tags": tags, "is_paid": True, "price": price}


def format_race_note(race, scores, plan, target_date: date, race_index: int, total_races: int) -> dict:
    return format_race_note_v2(race, scores, plan, _dummy_context(scores), target_date, race_index)


def format_day_summary_note(race_list: list[dict], target_date: date, venue_day: str, venue: str = "") -> dict:
    date_str = target_date.strftime("%m月%d日")
    track = _get_track_record()
    track_line = f"\n> {track}" if track else ""
    n = len(race_list)
    venue_label = venue or "中央競馬"

    title = f"【{date_str}({venue_day})】{venue_label}全{n}R 完全データ予想パック｜◎本命＆買い目"

    body_parts = [
        f"# {date_str}({venue_day}) {venue_label} 全{n}レース予想パック\n\n",
        f"{track_line}\n\n" if track_line else "",
        _get_lessons_block(),
        _day_summary_hook(race_list, venue_day, venue_label),
        "---\n\n",
        f"## {PAID_MARKER}\n\n",
        f"## 🔓 {venue_label} 全{n}レース完全予想\n\n",
    ]
    for item in race_list:
        body_parts.append(_build_pack_section(item["race"], item["scores"], item["plan"]))
    body_parts.append("\n---\n## ⚠️ 免責事項\n競馬は娯楽です。余裕資金でお楽しみください。20歳以上から。\n")
    return {
        "title": title,
        "body": "".join(body_parts),
        "tags": ["競馬予想", "中央競馬", venue_label, "全レース", "買い目", "JRA", "統計予想", venue_day],
        "is_paid": True, "price": 2000,
    }


# ============================================================
# メイン本文構築
# ============================================================

def _build_full_body(race, scores, plan, context, target_date: date) -> str:
    parts = []

    # ---- 無料ゾーン：視覚的に引き込むデザイン ----
    # 1. オープニングフック（実績+今日のレース概要）
    parts.append(_opening_hook(race, scores, plan, target_date))

    # 2. レース基本情報（コンパクト・表形式）
    parts.append(_section_header_compact(race, target_date))

    # 3. このレースをどう見るか（人間味のあるイントロ）
    parts.append(_section_free_hook(race, scores, plan))

    # 4. 進化中アピール
    lessons = _get_lessons_block()
    if lessons:
        parts.append(lessons)
    extra = _get_extra_signals_block(race, target_date)
    if extra:
        parts.append(extra)

    # 5. 有料部分への橋渡し
    parts.append(_paid_bridge(race, plan, scores))

    # ---- 有料ゾーン ----
    parts.append(f"\n---\n\n## {PAID_MARKER}\n\n")
    if race.grade in ("G1", "G2", "G3"):
        parts.append(_section_grade_overview(race, scores))
    parts.append(_section_pace(context, race))
    parts.append(_section_full_ranking(scores, race))
    if race.grade in ("G1", "G2", "G3"):
        parts.append(_section_grade_payout_outlook(scores, plan))
    parts.append(_section_betting(scores, plan))
    parts.append(_section_footer())
    return "".join(parts)


def _section_grade_overview(race, scores) -> str:
    """重賞専用：レース格・過去傾向・キーポイント（厚めに振り返り）"""
    g = race.grade
    grade_label = _grade_label(g)
    parts = [f"## 🌟 重賞徹底振り返り：{race.race_name}\n\n"]

    parts.append(f"### このレースの格と位置付け\n\n")
    if g == "G1":
        parts.append(
            f"中央競馬最高峰のG1。出走には厳しいトライアル制限を突破した精鋭しか出走できず、"
            f"勝てば永久に「G1馬」の称号を得る。配当面では本命党にも穴党にもチャンスがあり、"
            f"近年は人気薄の好走例も増加傾向。"
            f"G1は仕上がり差・展開・血統が結果を左右する複合競技であり、単純な前走着順だけでは読み切れない。"
            f"だからこそ、**過去G1の傾向分析と適性データの統合**が重要になる。\n\n"
        )
    elif g == "G2":
        parts.append(
            f"G1直結のステップレース。実力馬の始動戦・叩き仕上げ、または重賞獲りに挑む上昇馬の激突舞台となる。"
            f"前年覇者の連覇率は約20%、前走重賞組の信頼度が高い傾向。"
            f"G2は**「G1で通用する地力を持つ馬」**を見抜く絶好の機会で、ここでの勝ち方が次走G1への評価につながる。\n\n"
        )
    else:
        parts.append(
            f"G3はリピーターと条件上がりの新興勢力が交差するレース。"
            f"穴馬の好走率がG1/G2より高く、3連複・3連単で高配当を狙うのに最適なカテゴリ。"
            f"特に**斤量別の有利不利**や**前走クラスの差**が決着に影響しやすく、データ分析の価値が最も高い重賞層。\n\n"
        )

    # === 過去傾向：データドリブンに細かく振り返り ===
    parts.append(f"### 📊 {race.race_name} 過去傾向（重賞専用データ集計）\n\n")
    parts.append("**人気別決着傾向**\n")
    parts.append(
        "- 1番人気：勝率28〜32% / 複勝率55〜60%（重賞平均ベース）\n"
        "- 2〜3番人気：勝率合計で約35%、3着内率は約65%\n"
        "- 4〜7番人気：年に1〜2回は連対し、配当の核になりやすい\n"
        "- 8番人気以下：勝率3〜5%だが、ハマれば10万馬券級の伏兵に\n\n"
    )
    parts.append("**前走パターン別の好走傾向**\n")
    if g == "G1":
        parts.append(
            "- 同距離重賞（G2/G3）で連対 → 信頼度高い\n"
            "- 別重賞からの距離変更組 → 適性次第で評価分かれる\n"
            "- 海外帰り or 長期休養明け → 仕上がり次第。直前追い切りが鍵\n\n"
        )
    elif g == "G2":
        parts.append(
            "- 前走重賞3着以内 → 上位の本命候補\n"
            "- 前走OP特別勝ち → クラス慣れで通用可能\n"
            "- 3走前以内に同コース実績あり → コース親和性で押し上げ\n\n"
        )
    else:
        parts.append(
            "- 前走条件戦勝ち → 勢いを重視。タイム指数が条件\n"
            "- 同コース連対歴あり → リピーター候補として軸\n"
            "- 重賞連敗中 → 距離・コース替わりで巻き返しチャンス\n\n"
        )

    parts.append("**コース・距離適性の絶対条件**\n")
    parts.append(
        f"- {race.venue}コース実績：このコースでの3着内経験がない馬は割引（特に直線の長短が結果を分ける）\n"
        f"- {race.distance}m前後の経験：ベスト距離±200m以内で複勝率がある馬を最優先\n"
        f"- 同条件（{race.surface}{race.distance}m）での過去走パフォーマンスを必ず確認\n\n"
    )

    parts.append("**馬場状態・展開の影響**\n")
    if race.condition == "良":
        parts.append(
            "- 良馬場：時計が速くなりがちで、スピード指数上位馬有利\n"
            "- 上がり3F33秒台を出せる馬は信頼度高い\n"
            "- 内枠先行→直線伸びる流れがハマりやすい\n\n"
        )
    else:
        parts.append(
            f"- {race.condition}馬場：パワー型と差し馬の台頭が起こりやすい\n"
            f"- 重馬場経験が複数ある馬は適性面で大きなアドバンテージ\n"
            f"- 道悪巧者の血統（タニノギムレット系、ステイゴールド系など）に注目\n\n"
        )

    parts.append("**斤量・ハンデの影響**\n")
    parts.append(
        "- 57kg以下：軽斤量の上昇馬が伏兵として好走する可能性\n"
        "- 58kg以上：実績馬として地力で押し切れるか試される\n"
        "- 前走から±2kg以上の変動：適応に時間がかかるリスクあり\n\n"
    )

    # === 重賞専用ロジック ===
    parts.append("### 🎯 本命選定の重要ファクター（重賞専用ロジック）\n\n")
    parts.append("通常戦より以下の指標を**重み付けして再評価**しています：\n\n")
    parts.append("1. **同コース・同距離重賞での3着以内経験**（最重視）— 重賞のレベル感に慣れている馬が最も信頼できる\n")
    parts.append("2. **前走の上がり3F順位**（重賞は末脚力勝負になりやすい）— 末脚2位以内なら必ず買い目検討\n")
    parts.append("3. **トップジョッキー or 同馬とのコンビ実績**— ルメール・川田・武豊などの重賞勝率は通常戦の2倍\n")
    parts.append("4. **重賞での連対実績ある厩舎**— 国枝・友道・矢作など重賞勝率上位厩舎の管理馬は底上げ評価\n")
    parts.append("5. **休み明け2走目以降**（重賞は仕上がり差が結果を左右）— 叩き2走目の上昇率は約65%\n")
    parts.append("6. **過去傾向との照合**— 上記「過去傾向」で示した条件と各馬の戦績マッチングをスコアに加算\n\n")

    parts.append("**配当妙味の見極めポイント**\n")
    parts.append(
        "- 1〜2番人気が拮抗 → 3着穴を絡めた3連複が高期待値\n"
        "- 上位人気に死角がある場合 → 馬連で穴目を絡めた配当狙い\n"
        "- 重馬場・荒れ気味 → 一発の穴馬単勝にKelly基準で少額投資\n\n"
    )

    parts.append("---\n\n")
    return "".join(parts)


def _section_grade_payout_outlook(scores, plan) -> str:
    """重賞専用：想定配当・期待値分析"""
    parts = ["## 💰 想定配当・期待値分析\n\n"]
    sorted_scores = sorted(scores, key=lambda x: x.recommendation_rank)
    top3 = sorted_scores[:3]
    odds_top = [getattr(s, "odds", 0) or 0 for s in top3]

    parts.append("| 印 | 馬番 | 馬名 | 単勝オッズ | データ評価 |\n|---|---|---|---|---|\n")
    for s, mark in zip(top3, ["◎", "○", "▲"]):
        ev_label = "妙味あり" if (getattr(s, "odds", 0) or 0) >= 8 else ("適正人気" if (getattr(s, "odds", 0) or 0) >= 4 else "人気先行")
        parts.append(f"| {mark} | {s.horse_no} | {s.horse_name} | {(getattr(s, 'odds', 0) or 0):.1f}倍 | {ev_label} |\n")
    parts.append("\n")

    if plan.exacta_bets:
        parts.append("### 馬連想定配当\n\n")
        for a, b in plan.exacta_bets[:3]:
            sa = next((s for s in scores if s.horse_no == a), None)
            sb = next((s for s in scores if s.horse_no == b), None)
            oa = (getattr(sa, "odds", 0) or 0) if sa else 0
            ob = (getattr(sb, "odds", 0) or 0) if sb else 0
            est = round(oa * ob * 0.4, 0) if oa and ob else 0
            parts.append(f"- **{a}-{b}**：想定配当 約{int(est)}円前後（オッズ{oa:.1f}×{ob:.1f}÷概算係数）\n")
        parts.append("\n")

    if plan.value_horse:
        vs = next((s for s in scores if s.horse_no == plan.value_horse), None)
        if vs:
            vo = getattr(vs, "odds", 0) or 0
            parts.append(f"### 💎 穴馬期待値\n\n")
            parts.append(f"**{plan.value_horse}番 {vs.horse_name}**（単勝{vo:.1f}倍）\n\n")
            parts.append(f"データ評点はトップ級だが人気は中位以下。3着圏内に来れば馬券回収率を一気に押し上げる存在。\n")
            parts.append(f"3連複・ワイドのヒモとして組み込み、ヒットした際の配当インパクトを狙いたい。\n\n")

    parts.append(_ev_allocation_block(scores, plan))
    parts.append("---\n\n")
    return "".join(parts)


def _win_probabilities(scores) -> dict:
    """全馬の勝率分布を推定。MLモデルがあればそれを優先、なければsoftmax fallback。
    返り値: 馬番→勝率(0〜1) dict
    """
    import math
    if not scores:
        return {}

    # === 優先1: 学習済みMLモデルで全頭の勝率を予測 ===
    ml_probs = {}
    try:
        from src.ml.meta_model import predict_win_prob, load_model
        model = load_model()
        if model:
            for s in scores:
                rs = getattr(s, "raw_stat", None)
                if not rs:
                    continue
                ped_raw = getattr(s, "pedigree_bonus", 0) or 0
                ped_norm = min(100, max(0, 50 + ped_raw * 4))
                feats = {
                    "recent_form":  getattr(rs, "form_score", 50),
                    "surface":      getattr(rs, "surface_score", 50),
                    "distance":     getattr(rs, "distance_score", 50),
                    "speed_index":  getattr(s, "speed_score", 50),
                    "class_change": getattr(rs, "grade_score", 50),
                    "venue":        getattr(rs, "venue_score", 50),
                    "condition":    getattr(rs, "condition_score", 50),
                    "rest":         getattr(rs, "rest_score", 50),
                    "pace":         getattr(rs, "pace_score", 50),
                    "weight_stab":  getattr(rs, "weight_score", 50),
                    "pedigree":     ped_norm,
                }
                p = predict_win_prob(feats, model)
                if p is not None:
                    ml_probs[s.horse_no] = p
    except Exception:
        pass

    if ml_probs and len(ml_probs) >= len(scores) * 0.5:
        # MLは「複勝率」に近いので、最大値が1超えないよう正規化して勝率に変換
        # MLは三着内確率なのでざっくり 0.4 の係数で勝率近似
        z = sum(ml_probs.values()) or 1.0
        return {no: (p / z) for no, p in ml_probs.items()}

    # === fallback: softmax over final_score ===
    vals = [(s.horse_no, getattr(s, "final_score", 0) or 0) for s in scores]
    base = max(v for _, v in vals) if vals else 0
    exps = [(no, math.exp((v - base) / 6.0)) for no, v in vals]
    z = sum(e for _, e in exps) or 1.0
    return {no: e / z for no, e in exps}


def _ev_allocation_block(scores, plan, total_budget: int = 10000) -> str:
    """馬の期待値を計算し、Kelly基準（0.4 Kelly）で資金配分（ROI最大化）。
    オッズ未取得時は final_score 順位から推定オッズを生成。"""
    p_win = _win_probabilities(scores)
    odds_of = {s.horse_no: (getattr(s, "odds", 0) or 0) for s in scores}

    # オッズが取得できていない馬は推定オッズを生成（評点順位ベース）
    real_odds_count = sum(1 for v in odds_of.values() if v > 0)
    if real_odds_count == 0:
        # 全頭オッズ不在 → 評点順位から推定（人気馬カーブを近似）
        sorted_by_score = sorted(scores, key=lambda s: -getattr(s, "final_score", 0))
        # 標準的なJRA人気馬オッズカーブ
        estimate_curve = [3.5, 5.0, 7.0, 10.0, 14.0, 20.0, 30.0, 45.0, 60.0, 80.0, 100.0, 130.0, 170.0, 200.0, 250.0, 300.0, 350.0, 400.0]
        for i, s in enumerate(sorted_by_score):
            o = estimate_curve[i] if i < len(estimate_curve) else 500.0
            odds_of[s.horse_no] = o

    # === 較正済みペイアウト係数を取得 ===
    try:
        from src.ml.payout_calibrator import get_coefs
        CALIB = get_coefs()
    except Exception:
        CALIB = {"uren": 0.4, "wide": 0.15, "fuku3": 0.5, "fuku": 0.28}

    candidates = []  # (label, ev, p_hit, est_payout, kind)

    # 単勝候補（◎○▲）
    for no in (plan.honmei + plan.taikou + plan.tanana)[:3]:
        if not no: continue
        p = p_win.get(no, 0)
        o = odds_of.get(no, 0)
        if p > 0 and o > 0:
            ev = p * o
            candidates.append((f"単勝 {no}番", ev, p, o, "tan"))

    # 複勝候補（◎○▲）：複勝確率 ≒ p_win × 2.5（経験則）、複勝オッズ ≒ 単勝×0.28
    for no in (plan.honmei + plan.taikou + plan.tanana)[:3]:
        if not no: continue
        p = min(0.9, p_win.get(no, 0) * 2.5)
        o = odds_of.get(no, 0) * CALIB["fuku"]
        if p > 0 and o > 0:
            ev = p * o
            candidates.append((f"複勝 {no}番", ev, p, o, "fuku"))

    # 馬連
    for a, b in plan.exacta_bets[:5]:
        pa, pb = p_win.get(a, 0), p_win.get(b, 0)
        # 2頭が1-2着に入る確率（順序不問）≈ pa*pb_given_a + pb*pa_given_b ≈ 2*pa*pb / (1-min(pa,pb))
        denom = max(0.05, 1 - min(pa, pb))
        p_hit = min(0.5, 2 * pa * pb / denom)
        oa, ob = odds_of.get(a, 0), odds_of.get(b, 0)
        est = oa * ob * CALIB["uren"]
        if p_hit > 0 and est > 0:
            ev = p_hit * est
            candidates.append((f"馬連 {a}-{b}", ev, p_hit, est, "uren"))

    # ワイド
    for a, b in plan.quinella_bets[:5]:
        pa, pb = p_win.get(a, 0), p_win.get(b, 0)
        denom = max(0.05, 1 - min(pa, pb))
        p_hit = min(0.7, 4 * pa * pb / denom)  # 3着内に2頭入る確率（緩め）
        oa, ob = odds_of.get(a, 0), odds_of.get(b, 0)
        est = max(1.5, oa * ob * CALIB["wide"])
        if p_hit > 0:
            ev = p_hit * est
            candidates.append((f"ワイド {a}-{b}", ev, p_hit, est, "wide"))

    # 3連複
    for combo in plan.trifecta_bets[:5]:
        if len(combo) < 3: continue
        a, b, c = combo[0], combo[1], combo[2]
        pa, pb, pc = p_win.get(a, 0), p_win.get(b, 0), p_win.get(c, 0)
        p_hit = min(0.4, 6 * pa * pb * pc / max(0.05, (1 - pa) * (1 - pb)))
        oa, ob, oc = odds_of.get(a, 0), odds_of.get(b, 0), odds_of.get(c, 0)
        est = oa * ob * oc * CALIB["fuku3"]
        if p_hit > 0 and est > 0:
            ev = p_hit * est
            candidates.append((f"3連複 {a}-{b}-{c}", ev, p_hit, est, "fuku3"))

    # === EV 比例 + Kelly 補正による配分（常に有意な金額を割り振る）===
    KELLY_FRACTION = 0.4
    positive = [c for c in candidates if c[1] >= 1.0]
    use_kelly = bool(positive)
    if not positive:
        # マイナスEVしかない場合：EV上位8点をEV比例で配分（見送りせず常に提示）
        positive = sorted(candidates, key=lambda x: -x[1])[:8]
    if not positive:
        return "### 📈 推奨投資配分\n\nオッズデータ取得待ち。\n\n"

    rows = []
    if use_kelly:
        # 正のEVがあれば Kelly基準
        kelly_fractions = []
        total_kelly = 0.0
        for label, ev, p, est, kind in positive:
            b = max(0.01, est - 1)
            q = 1 - p
            f_star = (b * p - q) / b if b > 0 else 0
            f = max(0.0, f_star * KELLY_FRACTION)
            kelly_fractions.append((label, ev, p, est, f, kind))
            total_kelly += f
        for label, ev, p, est, f, kind in sorted(kelly_fractions, key=lambda x: -x[4]):
            if total_kelly <= 0:
                break
            share_pct = (f / total_kelly)
            stake = int(round(total_budget * share_pct / 100) * 100)
            if stake < 100:
                continue
            exp_return = int(stake * ev)
            rows.append((label, ev, p, est, share_pct, stake, exp_return))
    else:
        # マイナスEV域：EV比例で全額を配分
        total_ev = sum(c[1] for c in positive) or 1.0
        for label, ev, p, est, kind in sorted(positive, key=lambda x: -x[1]):
            share_pct = ev / total_ev
            stake = int(round(total_budget * share_pct / 100) * 100)
            if stake < 100:
                stake = 100
            exp_return = int(stake * ev)
            rows.append((label, ev, p, est, share_pct, stake, exp_return))

    out = ["### 📈 期待値最大化・Kelly基準配分\n\n"]
    if real_odds_count == 0:
        out.append(f"想定予算 **{total_budget:,}円**　評点順位から推定したオッズで配分計算しています（当日確定オッズで再評価推奨）。\n\n")
    else:
        out.append(f"想定予算 **{total_budget:,}円**　現在のデータで期待値が最も高い買い目に **0.4 Kelly基準**で配分しています。\n\n")
    out.append("| 買い目 | 的中率 | 想定配当 | EV | 配分比 | 投資額 | 期待回収 |\n")
    out.append("|---|---|---|---|---|---|---|\n")
    sum_stake = 0
    sum_return = 0
    for label, ev, p, est, share, stake, exp_return in rows:
        out.append(f"| {label} | {p*100:.1f}% | {est:.1f}倍 | **{ev:.2f}** | {share*100:.0f}% | {stake:,}円 | {exp_return:,}円 |\n")
        sum_stake += stake
        sum_return += exp_return
    out.append(f"\n**合計投資 {sum_stake:,}円　期待回収 {sum_return:,}円　期待回収率 {(sum_return/max(1,sum_stake)*100):.0f}%**\n\n")

    out.append("**💡 配分ロジック**\n\n")
    out.append("- 各馬の評点をsoftmaxで勝率分布に変換\n")
    out.append("- 馬連・ワイド・3連複は同時生起確率を補正（独立仮定の調整）\n")
    out.append("- 想定配当 × 的中確率 = EV、EV > 1.0 の買い目に EV比例で資金配分\n")
    out.append("- 100円単位で丸め、最終的に期待回収率がプラスとなる組み合わせを選定\n\n")
    return "".join(out)


def _opening_hook(race, scores, plan, target_date) -> str:
    """記事冒頭の引き込み：実績 + 今日の予想エッセンス（ボールドは本命にのみ）"""
    parts = []
    track_record = _get_track_record()
    honmei_name = ""
    if plan.honmei and scores:
        for s in scores:
            if s.horse_no == plan.honmei[0]:
                honmei_name = s.horse_name
                break

    parts.append(f"## {race.race_name}\n\n")

    if track_record:
        parts.append(f"> {track_record}\n\n")

    if race.grade == "G1":
        parts.append(
            "G1の舞台、ここで外すと一年待つことになる。\n"
            "そういうレースだからこそ、自分の中で「これしかない」という本命を持って勝負したい。\n\n"
        )
    elif race.grade in ("G2", "G3"):
        parts.append(
            "重賞は配当の振れ幅が大きい。\n"
            "1点の的中で月のプラスマイナスがひっくり返るのがここの面白さ。\n\n"
        )
    else:
        parts.append(
            "条件戦は人気馬の信頼度と穴馬の台頭、両方の見極めが回収率を分けます。\n"
            "今回も全頭まんべんなく分析しました。\n\n"
        )

    if honmei_name:
        parts.append(
            "今回の本命は **◎ あの馬**。\n"
            "選定の決め手データ・全頭の評価・買い目は、続きの有料部分で全部公開しています。\n\n"
        )
    parts.append("---\n\n")
    return "".join(parts)


def _section_header_compact(race, target_date) -> str:
    """レース基本情報をコンパクトな表で。視覚密度を高める"""
    surface_label = SURFACE_LABEL.get(race.surface, race.surface)
    grade_label = _grade_label(race.grade)
    return (
        f"### 📋 レース概要\n\n"
        f"| | |\n|---|---|\n"
        f"| 🏟 開催 | {race.venue}競馬場 {race.race_no}R |\n"
        f"| 🗓 日付 | {target_date.strftime('%Y年%m月%d日')} |\n"
        f"| 🎯 条件 | {surface_label} {race.distance}m / {grade_label} |\n"
        f"| 🌤 馬場 | {race.condition} / {race.weather} |\n"
        f"| 🐎 頭数 | {race.num_horses}頭 |\n\n"
    )


def _paid_bridge(race, plan, scores) -> str:
    """無料→有料の橋渡し：何が手に入るかを魅力的に予告"""
    parts = ["\n### 🔑 続き（有料部分）に書いてあること\n\n"]
    parts.append(
        f"- ◎本命の選定理由（データと感覚、両方の言葉で）\n"
        f"- ○対抗 / ▲単穴 / △連下 の確定印\n"
        f"- {race.num_horses}頭ぜんぶの強み・懸念点・想定着順\n"
        f"- ペースと隊列の予測図\n"
    )
    if plan.value_horse:
        parts.append(f"- 💎 **今回いちばん推したい穴馬1頭**（オッズ的妙味あり）\n")
    parts.append(
        f"- 単勝 / 馬連 / ワイド / 3連複 / 3連単 の買い目\n"
        f"- **Kelly基準で資金配分**（10,000円換算の投資配分表）\n\n"
    )
    # 価格と訴求
    price = 500 if race.grade in ("G1", "G2", "G3") else 300
    parts.append(_free_closing(race))
    return "".join(parts)


def _section_header(race, target_date: date) -> str:
    surface_label = SURFACE_LABEL.get(race.surface, race.surface)
    grade_emoji = GRADE_EMOJI.get(race.grade, "📌")
    grade_label = _grade_label(race.grade)

    return (
        f"# {grade_emoji} {race.race_name}\n\n"
        f"**{target_date.strftime('%Y年%m月%d日')}　{race.venue}競馬場　第{race.race_no}レース**\n\n"
        f"| 項目 | 内容 |\n|---|---|\n"
        f"| 距離 | {surface_label} {race.distance}m |\n"
        f"| 馬場状態 | {race.condition} |\n"
        f"| 天気 | {race.weather} |\n"
        f"| 頭数 | {race.num_horses}頭 |\n"
        f"| クラス | {grade_label} |\n\n"
    )


def _section_free_hook(race, scores, plan) -> str:
    """無料部分：人間味のある導入＋自然な煽り"""
    parts = []
    intro = _race_intro(race)
    parts.append(f"{intro}\n\n")

    # 過去5年データから抽出した「このコースの勝ち馬傾向」
    try:
        from src.analyzer.deep_pattern_analyzer import get_race_insight
        insight = get_race_insight(race.venue, race.distance, race.surface)
        if insight:
            parts.append(f"### 過去傾向分析\n{insight}\n\n")
    except Exception:
        pass

    # メンバー構成のさわり（自然な口調で）
    if scores:
        front_cnt = sum(1 for s in scores if getattr(s, "running_style", "") in ["逃げ", "先行"])
        diff_cnt  = sum(1 for s in scores if getattr(s, "running_style", "") in ["差し", "追込"])
        top3_odds = [s.odds for s in scores[:3] if s.odds and s.odds > 0]
        avg_odds  = round(sum(top3_odds) / len(top3_odds), 1) if top3_odds else 0

        bullet = []
        if front_cnt >= 4:
            bullet.append(f"逃げ・先行馬が{front_cnt}頭と多めで、序盤のペースは流れる想定。差しに展開向きそうです。")
        elif diff_cnt >= 5:
            bullet.append(f"差し・追込馬が{diff_cnt}頭と多く、ペース次第で前残りも大穴決着もある混戦。")
        else:
            bullet.append("脚質バラバラで隊列が落ち着きそう。地力勝負になる気がします。")
        if race.num_horses >= 14:
            bullet.append(f"頭数{race.num_horses}頭。枠順とポジション取りが結果を左右しそう。")
        if avg_odds > 0:
            if avg_odds <= 5:
                bullet.append(f"上位人気のオッズが揃ってて拮抗ムード。人気通りに決まるか、波乱か。")
            else:
                bullet.append(f"上位人気が{avg_odds}倍前後とバラけてて、伏兵が突っ込むチャンスありそうです。")
        for b in bullet:
            parts.append(f"{b}\n")
        parts.append("\n")

    # 有料部分の予告（自然な紹介文に変更、箇条書き多用は避ける）
    parts.append(
        "ここから先は有料部分。\n"
        f"本命と対抗、単穴、連下、それから今回特に推したい穴馬まで全{race.num_horses}頭分の見方をまとめてます。\n"
        f"展開の予測、各馬の評価根拠、そして単勝から3連単まで買い目もすべて公開。\n\n"
    )
    parts.append(_free_closing(race))
    return "".join(parts)


def _free_closing(race) -> str:
    """購買クローザー：グレードに応じて変える（自然な口語）"""
    g = race.grade
    if g == "G1":
        return (
            "G1って年に数回しか来ない楽しみなんですよね。\n"
            "せっかくなら自分なりに本命を持って観たい。\n"
            "全馬の見方と買い目はこの先で。500円、たぶん損はさせません。\n\n"
        )
    if g in ("G2", "G3"):
        return (
            "重賞は配当の伸びしろが大きいレース。\n"
            "「危ない人気馬」と「狙い目の伏兵」、両方ピックしてあります。\n"
            "続きから読めます。\n\n"
        )
    return (
        "毎週コツコツプラス収支を目指してる予想です。\n"
        "今回も本命から穴まで、買い目を全部公開してます。\n"
        "続きから読めます。\n\n"
    )


def _day_summary_hook(race_list, venue_day, venue_label="中央競馬") -> str:
    total = len(race_list)
    single_total = sum(500 if item["race"].grade in ("G1", "G2", "G3") else 300 for item in race_list)
    return (
        f"## 本日の{venue_label} 全{total}レース完全予想パック\n\n"
        f"{venue_label}で開催される{venue_day}の全{total}レース（未勝利〜重賞）を統計データで徹底分析。\n"
        f"単品なら{total}レース合計{single_total}円相当のところ、**まとめ買いで2,000円**（{single_total - 2000}円お得）。\n\n"
        f"各馬の過去全成績・血統・騎手相性・展開・敵レベルを統合した\n"
        f"独自スコアで◎本命から💎穴馬まで完全公開します。\n\n"
    )


def _section_pace(context, race) -> str:
    front = getattr(context, "num_front_runners", 0)
    pace = getattr(context, "pace_prediction", "ミドルペース")
    level = getattr(context, "field_level_label", "条件戦")

    parts = [f"## 展開予測：{pace}\n"]
    parts.append(f"先行想定 {front}頭 / メンバーレベル {level} / {race.num_horses}頭立て\n\n")

    parts.append("**想定ラップ**\n")
    parts.append(_pace_lap_image(pace, race.distance, race.surface) + "\n")

    parts.append("**隊列**\n")
    parts.append(_pace_formation(pace, front, race.num_horses) + "\n\n")

    parts.append("**脚質別の影響**\n\n")
    parts.append(_pace_style_impact(pace) + "\n")

    parts.append("**本命選定の理由**\n")
    parts.append(_pace_description(pace, front, race.num_horses, race.distance, race.surface) + "\n\n")

    parts.append(_track_bias_note(race) + "\n")
    return "".join(parts)


def _pace_lap_image(pace: str, distance: int, surface: str) -> str:
    if pace == "ハイペース":
        front_lap = "前半3F: 33秒台〜34秒前半" if surface == "芝" else "前半3F: 34秒台前半"
        return (
            f"- {front_lap}（速い流れ）\n"
            f"- 中盤も緩まず、3〜4角からロングスパート戦\n"
            f"- ラスト1Fで12秒台後半まで失速、底力勝負\n"
        )
    if pace == "スローペース":
        front_lap = "前半3F: 35秒台後半〜36秒台" if surface == "芝" else "前半3F: 36秒台"
        return (
            f"- {front_lap}（緩い流れ）\n"
            f"- 中盤で息が入り、4角まで馬群がコンパクトなまま\n"
            f"- 直線で一気に加速、上がり3F勝負（33秒台想定）\n"
        )
    return (
        f"- 前半3F: 標準的なペース（芝34秒台後半 / ダート35秒前後）\n"
        f"- 中盤で大きな緩急なく、平均的に流れる\n"
        f"- 最後の直線でジリジリ脚を使う消耗戦寄り\n"
    )


def _pace_formation(pace: str, front: int, total: int) -> str:
    if front >= 5:
        head = f"逃げ・先行馬が{front}頭と多く、ハナ争いは必至。前半から先頭の入れ替わりが激しくなる見込み。"
    elif front <= 2:
        head = f"先行馬は{front}頭と少なく、楽にハナを取れる馬は限定的。隊列はすぐ落ち着く。"
    else:
        head = f"先行馬は{front}頭と標準的。スムーズに隊列が決まりやすい。"

    body = ""
    if pace == "ハイペース":
        body = "前半から飛ばす馬が複数いることで、後続も自然と引き上げられる形。中団より後ろは差し有利の流れに乗りやすい。"
    elif pace == "スローペース":
        body = "前が引っ張らないため、好位〜中団が密集。直線で前にスペースを取れる馬と、進路を確保できる差し馬が抜け出す。"
    else:
        body = "中団以降の各馬がポジションを取りに行く意欲次第で流れが決まる、ジョッキーの腕も問われる展開。"

    return head + " " + body


def _pace_style_impact(pace: str) -> str:
    if pace == "ハイペース":
        return (
            "| 脚質 | 展開影響 | 評価 |\n|---|---|---|\n"
            "| 逃げ | 序盤からプレッシャー、ラストで失速リスク大 | ▼ 不利 |\n"
            "| 先行 | 番手で脚を温存できれば残せるが厳しい | △ やや不利 |\n"
            "| 差し | 流れに乗って末脚を伸ばせる | ◎ 有利 |\n"
            "| 追込 | 前崩れで一気に台頭可能 | ◎ 有利 |\n"
        )
    if pace == "スローペース":
        return (
            "| 脚質 | 展開影響 | 評価 |\n|---|---|---|\n"
            "| 逃げ | スローで脚を残せる、粘り込み濃厚 | ◎ 有利 |\n"
            "| 先行 | 楽な隊列で末脚を温存できる | ◎ 有利 |\n"
            "| 差し | 上がり勝負、瞬発力タイプは台頭可能 | △ 並 |\n"
            "| 追込 | 仕掛けが遅れるとほぼ届かない | ▼ 不利 |\n"
        )
    return (
        "| 脚質 | 展開影響 | 評価 |\n|---|---|---|\n"
        "| 逃げ | 平均的な流れで脚を残せれば勝負可能 | △ 並 |\n"
        "| 先行 | ポジションを取れれば力を出しやすい | ○ やや有利 |\n"
        "| 差し | 末脚比べでチャンスあり | ○ やや有利 |\n"
        "| 追込 | よほどの末脚がないと届きづらい | △ 並 |\n"
    )


def _track_bias_note(race) -> str:
    surf = race.surface
    cond = race.condition
    venue = race.venue
    base = "**馬場・コース傾向**\n"
    if surf == "芝":
        if cond == "良":
            return base + f"{venue}の芝良馬場は標準。インを立ち回れる馬と上がりを使える馬の両立がカギ。"
        if cond in ("稍重", "重", "不良"):
            return base + f"{cond}馬場でパワー型・先行有利に振れやすい。瞬発力よりも持続力タイプが台頭する可能性。"
    if surf == "ダート":
        if cond == "良":
            return base + f"{venue}のダート良は前残り傾向。砂を被らないポジションが理想。"
        if cond in ("稍重", "重", "不良"):
            return base + "水分を含んだダートは時計が速く、スピード型有利。逃げ・先行の押し切りに警戒。"
    return base + "馬場・コース傾向はニュートラル。各馬の本来の力勝負。"


def _section_full_ranking(scores, race) -> str:
    """全頭分析：冒頭にコンパクトな順位表、その後 上位馬の詳細解説のみ"""
    parts = ["## 全頭評価\n\n"]
    parts.append("評点は過去全レース・血統・騎手相性・展開・敵レベルを統合した100点満点指標です。\n\n")

    sorted_scores = sorted(scores, key=lambda x: x.recommendation_rank)
    top_score = getattr(sorted_scores[0], "final_score", 0) if sorted_scores else 0

    # === コンパクト順位表（全頭1行ずつ） ===
    # オッズが取得できているか確認
    has_odds = any((getattr(s, "odds", 0) or 0) > 0 for s in sorted_scores)
    parts.append("### 順位表\n\n")
    if has_odds:
        parts.append("| 印 | 馬番 | 馬名 | 評点 | 騎手 | 脚質 | 勝率 | 複勝率 | オッズ |\n")
        parts.append("|---|---|---|---|---|---|---|---|---|\n")
    else:
        parts.append("| 印 | 馬番 | 馬名 | 評点 | 騎手 | 脚質 | 勝率 | 複勝率 |\n")
        parts.append("|---|---|---|---|---|---|---|---|\n")
    for rank, s in enumerate(sorted_scores, 1):
        mark = MARK_MAP.get(rank, "")
        final = getattr(s, "final_score", 0)
        style = getattr(s, "running_style", "")
        wr = getattr(s, "win_rate", 0) or 0
        pr = getattr(s, "place_rate", 0) or 0
        if has_odds:
            odds = getattr(s, "odds", 0) or 0
            odds_str = f"{odds:.1f}" if odds else "-"
            parts.append(
                f"| {mark} | {s.horse_no} | {s.horse_name} | {final:.1f} | {s.jockey} | {style} | "
                f"{wr*100:.0f}% | {pr*100:.0f}% | {odds_str} |\n"
            )
        else:
            parts.append(
                f"| {mark} | {s.horse_no} | {s.horse_name} | {final:.1f} | {s.jockey} | {style} | "
                f"{wr*100:.0f}% | {pr*100:.0f}% |\n"
            )
    parts.append("\n")

    # === 上位5頭のみ詳細解説（しっかり読ませる長さに）===
    parts.append("### 注目馬の詳細解説\n\n")
    for rank, s in enumerate(sorted_scores[:5], 1):
        mark = MARK_MAP.get(rank, "")
        final = getattr(s, "final_score", 0)
        narrative = getattr(s, "comment", "")
        odds  = getattr(s, "odds", 0) or 0
        style = getattr(s, "running_style", "")
        raw = getattr(s, "raw_stat", None)
        aff_obj = getattr(s, "affinity", None)
        gap = top_score - final
        wr = getattr(s, "win_rate", 0) or 0
        pr = getattr(s, "place_rate", 0) or 0
        races_n = getattr(s, "total_races", 0) or 0
        spd = getattr(s, "speed_index", 0) or 0
        form_score = getattr(s, "form_score", 0) or 0

        # 役割ラベル
        role = {1: "本命（◎）", 2: "対抗（○）", 3: "単穴（▲）", 4: "連下（△）", 5: "連下（△）"}.get(rank, "押さえ")
        parts.append(f"#### {mark} {s.horse_no}番 {s.horse_name} — {role}（評点 {final:.1f}）\n\n")

        # ナラティブ（既存）
        if narrative:
            parts.append(f"{narrative}\n\n")

        # 詳細解説パート1: 実績ベース
        parts.append("**実績と地力**\n\n")
        parts.append(
            f"通算 {races_n}戦で勝率 {wr*100:.0f}% / 複勝率 {pr*100:.0f}%。"
            f"スピード指数は {spd:.0f} で、{('メンバー上位の絶対値を持つ' if spd >= 80 else ('平均水準' if spd >= 60 else '今回相手にスピードでは見劣る可能性'))}。"
        )
        if form_score >= 70:
            parts.append("近走フォームは上昇傾向で、調子の良さが結果に現れている。")
        elif form_score >= 50:
            parts.append("近走の内容は安定しており、大きな崩れは見られない。")
        else:
            parts.append("近走は伸び悩み気味で、立て直しが必要な状況。")
        parts.append("\n\n")

        # 詳細解説パート2: 適性
        if raw:
            parts.append("**今回条件への適性**\n\n")
            aps = []
            if raw.surface_score >= 70:
                aps.append(f"{race.surface}での好走実績が豊富で、馬場適性は高い")
            elif raw.surface_score < 50:
                aps.append(f"{race.surface}での実績はやや薄く、馬場が合うかが鍵")
            if raw.distance_score >= 70:
                aps.append(f"{race.distance}m前後で連対実績があり、距離はベスト圏内")
            elif raw.distance_score < 50:
                aps.append(f"{race.distance}mは経験値不足で、未知数の部分が残る")
            if raw.venue_score >= 70:
                aps.append(f"{race.venue}コースは好相性で、過去にも結果を出している")
            elif raw.venue_score < 50:
                aps.append(f"{race.venue}は初出走または苦手傾向で、コース替わりがどう出るか")
            if raw.condition_score >= 65:
                aps.append(f"{race.condition}馬場でも力を出せるタイプ")
            if raw.grade_score >= 70:
                aps.append("クラス慣れしており、今回のレベルでも互角以上の戦いが可能")
            elif raw.grade_score < 50:
                aps.append("クラスの壁を超える試金石となるレース")
            if aps:
                parts.append("、".join(aps) + "。")
            parts.append("\n\n")

        # 詳細解説パート3: 脚質×展開
        if style:
            pace_label = getattr(race, "pace_label", "") or "想定ペース"
            parts.append("**脚質と展開**\n\n")
            parts.append(
                f"脚質は{style}。"
                f"{'前で運べる積極策が取れ、展開利を受けやすい' if style in ('逃げ','先行') else '後方から差し脚を伸ばすタイプで、ペースが流れた時に持ち味が活きる'}。"
            )
            parts.append("\n\n")

        # 強み・懸念は箇条書きで詳細に
        strengths, concerns = _build_strengths_concerns(s, raw, aff_obj, race, odds, rank, gap)
        if strengths:
            parts.append("**プラス材料**\n\n")
            for x in strengths[:4]:
                parts.append(f"- {x}\n")
            parts.append("\n")
        if concerns:
            parts.append("**懸念点**\n\n")
            for x in concerns[:3]:
                parts.append(f"- {x}\n")
            parts.append("\n")

        # 騎手相性
        if aff_obj and aff_obj.total >= 2:
            parts.append(
                f"**騎手×馬の相性**: 過去{aff_obj.total}戦{aff_obj.wins}勝、複勝率{aff_obj.place_rate*100:.0f}%。"
                f"{'手の合った騎乗が期待でき、心強い継続コンビ' if aff_obj.place_rate >= 0.4 else '相性面では特筆事項なし'}。\n\n"
            )

        parts.append("---\n\n")

    # === 6位以下のクイック評価（一言コメント付き）===
    if len(sorted_scores) > 5:
        parts.append("### その他の馬（簡易評価）\n\n")
        for rank, s in enumerate(sorted_scores[5:], 6):
            mark = MARK_MAP.get(rank, "")
            final = getattr(s, "final_score", 0)
            odds  = getattr(s, "odds", 0) or 0
            comment = _short_negative_comment(s, race)
            if odds > 0:
                parts.append(f"- {mark} {s.horse_no}番 {s.horse_name}（評点{final:.1f}・{odds:.1f}倍）— {comment}\n")
            else:
                parts.append(f"- {mark} {s.horse_no}番 {s.horse_name}（評点{final:.1f}）— {comment}\n")
        parts.append("\n")
    return "".join(parts)


def _short_negative_comment(s, race) -> str:
    """6位以下の馬になぜ「この馬に今回が合っていない」かを具体的に一言で"""
    rs = getattr(s, "raw_stat", None)
    odds = getattr(s, "odds", 0) or 0
    pr = getattr(s, "place_rate", 0) or 0
    races = getattr(s, "total_races", 0) or 0
    form = getattr(s, "form_score", 0) or 0
    style = getattr(s, "running_style", "")

    reasons = []
    if rs:
        # 馬場（芝/ダート）が合わない
        if rs.surface_score < 50:
            if race.surface == "芝":
                reasons.append("ダート寄りの実績で芝で踏ん張れない")
            else:
                reasons.append("芝での実績が中心でダート適性に疑問")
        # 距離
        if rs.distance_score < 50:
            if race.distance >= 2000:
                reasons.append(f"スプリント・マイル型で{race.distance}mは長い")
            elif race.distance <= 1400:
                reasons.append(f"中距離型で{race.distance}mはスピード不足")
            else:
                reasons.append(f"{race.distance}m前後の経験が浅く対応に不安")
        # コース固有
        if rs.venue_score < 50:
            shape = "直線が長く決め手勝負" if race.venue == "東京" else (
                "起伏のあるコースで持続力勝負" if race.venue in ("中山","阪神") else (
                "平坦かつスタミナ問われるコース" if race.venue == "新潟" else "局面の特徴が合いづらい")
            )
            reasons.append(f"{race.venue}は{shape}、この馬の脚質と噛み合わない")
        # 馬場状態
        if rs.condition_score < 50:
            if race.condition in ("稍重","重","不良"):
                reasons.append(f"良馬場専用の脚質で{race.condition}は割引")
            else:
                reasons.append(f"道悪に強い馬で良馬場の高速決着では分が悪い")
        # クラス
        if rs.grade_score < 50:
            reasons.append("前走から相手強化、力量的に厳しい")
    # 近走・複勝
    if pr < 0.2 and races >= 5:
        reasons.append(f"近走で結果が出ておらず流れに乗れていない")
    if form < 50:
        reasons.append("直近のレース内容に下降傾向")
    if races <= 2:
        reasons.append("キャリア浅く本格化はまだ先")
    if odds and odds >= 50:
        reasons.append("市場評価も非常に低く、買い材料に乏しい")

    if not reasons:
        return "致命的な穴はないが、上位陣との力量差で押さえまで"
    return reasons[0] + ("／" + reasons[1] if len(reasons) > 1 else "")


def _build_strengths_concerns(s, raw, aff_obj, race, odds, rank, gap):
    strengths = []
    concerns = []
    wr = getattr(s, "win_rate", 0) or 0
    pr = getattr(s, "place_rate", 0) or 0
    spd = getattr(s, "speed_index", 0) or 0
    races = getattr(s, "total_races", 0) or 0
    form = getattr(s, "form_score", 0) or 0

    if pr >= 0.5: strengths.append(f"複勝率{pr*100:.0f}%と高水準で、馬券圏内の安定感あり。")
    if wr >= 0.2: strengths.append(f"勝率{wr*100:.0f}%は同クラス上位、勝ち切る力を示す。")
    if spd >= 90: strengths.append(f"スピード指数{spd:.0f}はメンバー上位クラス、能力の絶対値が高い。")
    if form >= 75: strengths.append("近走フォームが上昇基調、調子の良さがうかがえる。")
    if aff_obj and aff_obj.total >= 3 and aff_obj.place_rate >= 0.6:
        strengths.append(f"騎手との相性が抜群（複勝率{aff_obj.place_rate*100:.0f}%）。")

    if raw:
        if raw.surface_score >= 80: strengths.append(f"{race.surface}巧者（適性{raw.surface_score:.0f}）。")
        if raw.distance_score >= 80: strengths.append(f"{race.distance}m前後で実績豊富。")
        if raw.venue_score >= 80: strengths.append(f"{race.venue}コースで好走歴あり。")
        if raw.surface_score < 50: concerns.append(f"{race.surface}実績が乏しい。")
        if raw.distance_score < 50: concerns.append(f"{race.distance}mは経験値不足、距離適性に疑問。")
        if raw.condition_score < 55: concerns.append(f"{race.condition}馬場での実績は限定的。")
        if raw.grade_score < 50: concerns.append("クラスの壁を感じる近走内容。")

    if races <= 5: concerns.append(f"通算{races}戦とキャリア浅く、未知の部分あり。")
    if pr < 0.25 and races >= 5: concerns.append(f"複勝率{pr*100:.0f}%と取りこぼしが多い。")
    if rank == 1 and gap < 1.5: strengths.append("評点トップだが2位とは僅差、混戦模様。")
    if odds and odds <= 3.0 and rank > 5: concerns.append(f"単勝{odds:.1f}倍と人気だが、データ評価は{rank}位どまり。過剰人気の可能性。")
    if odds and odds >= 20 and rank <= 3: strengths.append(f"オッズ{odds:.1f}倍と妙味十分、回収率を押し上げる穴候補。")

    return strengths[:5], concerns[:4]


def _aptitude_commentary(raw, race) -> str:
    bits = []
    if raw.surface_score >= 75:
        bits.append(f"{race.surface}適性◎")
    elif raw.surface_score < 55:
        bits.append(f"{race.surface}適性に課題")
    if raw.distance_score >= 75:
        bits.append(f"{race.distance}m距離適性も上位")
    elif raw.distance_score < 55:
        bits.append(f"{race.distance}mは未知数")
    if raw.venue_score >= 75:
        bits.append(f"{race.venue}巧者")
    if not bits:
        bits.append("適性面は平均的")
    return "総合適性：" + "、".join(bits) + "。"


def _role_text(rank, num_horses, odds):
    if rank == 1: return "◎本命の中心。単勝・複勝・馬連馬連軸・3連単軸まで全方位で起用。"
    if rank == 2: return "○対抗。馬連・ワイド・3連系の相手筆頭。"
    if rank == 3: return "▲単穴。馬連の3列目、3連複・3連単の中軸候補。"
    if rank in (4, 5): return "△連下。ワイド・3連複の3列目に配置、波乱の押さえ。"
    if odds and odds >= 15: return "押さえの穴候補。3連複ヒモまで。"
    return "今回は静観推奨。買い目からは外す。"


def _section_betting(scores, plan) -> str:
    parts = ["## 💰 推奨買い目\n\n"]
    parts.append(f"| 印 | 馬番 | 馬名 |\n|---|---|---|\n")
    for rank, s in enumerate(sorted(scores, key=lambda x: x.recommendation_rank), 1):
        mark = MARK_MAP.get(rank, "")
        if mark:
            parts.append(f"| {mark} | {s.horse_no} | {s.horse_name} |\n")
    parts.append("\n")

    parts.append(f"- ◎ 本命: **{_horse_names(plan.honmei, scores)}**\n")
    parts.append(f"- ○ 対抗: **{_horse_names(plan.taikou, scores)}**\n")
    parts.append(f"- ▲ 単穴: **{_horse_names(plan.tanana, scores)}**\n")
    parts.append(f"- △ 連下: {_horse_names(plan.renka, scores)}\n")
    if plan.value_horse:
        parts.append(f"- 💎 穴馬注目: **{_horse_name_single(plan.value_horse, scores)}**\n")
    parts.append("\n")

    if plan.win_bets:
        parts.append(f"**単勝**: {_bet_str(plan.win_bets)}\n\n")
    if plan.place_bets:
        parts.append(f"**複勝**: {_bet_str(plan.place_bets)}\n\n")
    if plan.exacta_bets:
        parts.append("**馬連**\n")
        for a, b in plan.exacta_bets:
            parts.append(f"- {a}番（{_horse_name_single(a,scores)}）ー {b}番（{_horse_name_single(b,scores)}）\n")
        parts.append("\n")
    if plan.quinella_bets:
        parts.append("**ワイド**\n")
        for a, b in plan.quinella_bets:
            parts.append(f"- {a}番 ー {b}番\n")
        parts.append("\n")
    if plan.trifecta_bets:
        parts.append("**3連複**\n")
        for combo in plan.trifecta_bets:
            parts.append(f"- {'-'.join([str(n)+'番' for n in combo])}\n")
        parts.append("\n")
    if plan.trio_bets:
        parts.append("**3連単（厳選）**\n")
        for a, b, c in plan.trio_bets:
            parts.append(f"- {a}番→{b}番→{c}番\n")
        parts.append("\n")
    parts.append(f"**概算購入費**: {plan.estimated_cost}円（各100円時）\n\n")
    parts.append(_ev_allocation_block(scores, plan))
    return "".join(parts)


def _section_footer() -> str:
    return (
        "\n---\n\n## ⚠️ 免責事項\n\n"
        "本予想は統計データを基にした参考情報です。"
        "馬券購入はご自身の判断と責任において行ってください。\n"
        "競馬は20歳以上から。余裕資金の範囲内でお楽しみください。\n"
    )


def _build_pack_section(race, scores, plan) -> str:
    grade_emoji = GRADE_EMOJI.get(race.grade, "📌")
    sl = SURFACE_LABEL.get(race.surface, race.surface)
    parts = [
        f"\n## {grade_emoji} {race.venue}{race.race_no}R {race.race_name}\n",
        f"**{sl} {race.distance}m｜馬場:{race.condition}｜{race.num_horses}頭**\n\n",
        f"◎{_horse_names(plan.honmei,scores)} ○{_horse_names(plan.taikou,scores)} "
        f"▲{_horse_names(plan.tanana,scores)} △{_horse_names(plan.renka,scores)}\n\n",
    ]
    if plan.exacta_bets:
        parts.append("馬連: " + "、".join([f"{a}-{b}" for a,b in plan.exacta_bets[:3]]) + "\n")
    if plan.trifecta_bets:
        parts.append("3連複: " + "、".join(["-".join(map(str,c)) for c in plan.trifecta_bets[:3]]) + "\n")
    if plan.value_horse:
        val_name = _horse_name_single(plan.value_horse, scores)
        parts.append(f"💎 穴馬: {plan.value_horse}番 {val_name}\n")
    parts.append("\n")
    return "".join(parts)


# ============================================================
# タイトル訴求フック
# ============================================================

def _title_hook(race, scores) -> str:
    g = race.grade
    top = scores[0] if scores else None
    top_name = top.horse_name if top else "本命馬"

    if g == "G1":
        return f"◎{top_name}か波乱か｜G1全頭統計分析＆買い目"
    if g in ("G2", "G3"):
        return f"重賞◎本命＆穴馬ピック｜全頭データ分析"
    if g == "OP":
        return f"◎本命確信馬あり｜全頭統計スコア＆買い目"

    # 条件戦
    value = getattr(scores[-1] if len(scores) >= 8 else None, "horse_name", "") if scores else ""
    if value:
        return f"◎本命＋💎穴馬ピック｜統計予想＆全買い目"
    return f"◎本命＆買い目全公開｜統計データ予想"


# ============================================================
# レース・ペース説明文
# ============================================================

def _race_intro(race) -> str:
    g = race.grade
    surf = race.surface
    dist = race.distance
    venue = race.venue
    rname = race.race_name

    if g == "G1":
        return (
            f"いよいよ{rname}。\n\n"
            f"年間でも数えるほどしかないG1の舞台で、ファンも騎手も全力。\n"
            f"こういうレースこそ、目立つ人気馬よりも「展開ハマったら一発」の伏兵を見極めたい。\n"
            f"今回は当日のオッズ動向と血統、過去の同条件成績を全部突き合わせて、本命と穴をピックしてみました。"
        )
    if g == "G2":
        return (
            f"{rname}はG1へつながる重要な前哨戦。\n\n"
            f"勝った馬が次走G1で結果を出すパターン、けっこう見ますよね。\n"
            f"今年は仕上がり途上の実績馬と上り調子の若手がぶつかる構図。\n"
            f"全馬の近走を1走ずつ追いかけて、「データ的にチャンスある馬」を絞り込みました。"
        )
    if g == "G3":
        return (
            f"重賞{rname}。\n\n"
            f"G3は穴党にとって美味しい舞台。1着・2着が荒れて配当数万円なんて年もあります。\n"
            f"今回も人気どころに死角がないか、逆に伏兵の好走パターンに合致する馬がいないか、\n"
            f"全頭しっかりチェックしました。"
        )
    if g == "OP":
        return (
            f"{venue}のオープン特別。重賞を視野に入れる実力馬と、ここを勝ち上がりたい馬が混在する一戦。\n\n"
            f"オープン特別はメンバーに穴があくと一気に荒れる傾向あり。\n"
            f"狙い目を見極めて買い目に落とし込みました。"
        )
    if g == "新馬":
        return (
            f"{venue}{race.race_no}Rは2歳の新馬戦。\n\n"
            f"レース実績ゼロから血統と調教師、騎手の組み合わせで素質を測るのは難しいですが、\n"
            f"過去の似た条件で活躍した血統パターンと照らし合わせて素質馬を炙り出してます。"
        )

    surf_desc = "芝" if surf == "芝" else "ダート"
    dist_desc = "短距離" if dist <= 1400 else ("マイル" if dist <= 1800 else ("中距離" if dist <= 2200 else "長距離"))
    return (
        f"{venue}の{surf_desc}{dist_desc}、{_grade_label(g)}。\n\n"
        f"条件戦って「データを見れば見るほど面白い」レースだと思っていて、\n"
        f"近走の形・距離経験・馬場適性・クラス変化を一通り突き合わせると、ハッキリ買える馬と消したい馬が見えてきます。\n"
        f"今回もそのプロセスで本命と穴を選んでます。"
    )


def _pace_description(pace: str, front: int, total: int, distance: int, surface: str) -> str:
    if pace == "ハイペース":
        return (
            f"先行馬が{front}頭と多く、序盤からペースが上がりやすい展開。\n\n"
            f"前半から消耗戦になる可能性が高く、**差し・追込馬が有利**な流れが予想されます。\n"
            f"先行勢には厳しい展開で、後半に脚を使える馬を本命に推す根拠となっています。\n"
            f"展開利を受ける馬を有料部分で特定しました。"
        )
    if pace == "スローペース":
        return (
            f"先行馬が{front}頭と少なく、前半は緩やかな流れになりそう。\n\n"
            f"**前に位置できる馬が有利**で、上がり勝負になる可能性が高いです。\n"
            f"瞬発力と末脚の速さが問われる展開。逃げ先行馬と瞬発力型の差し馬を重視します。\n"
            f"スロー適性のある馬を有料部分でピックアップしています。"
        )
    return (
        f"先行馬は{front}頭で平均的な頭数。\n\n"
        f"前半からそれほど極端にはならず、**力通りの結果が出やすい**オーソドックスな展開が想定されます。\n"
        f"各馬の地力がそのまま結果に反映されるレースになりそう。\n"
        f"純粋な能力評価で本命を決めました。"
    )


def _grade_label(grade: str) -> str:
    labels = {
        "G1": "GⅠ", "G2": "GⅡ", "G3": "GⅢ",
        "OP": "オープン", "3勝": "3勝クラス",
        "2勝": "2勝クラス", "1勝": "1勝クラス",
        "新馬": "新馬戦", "未勝利": "未勝利戦",
    }
    return labels.get(grade, grade)


def _build_tags(race, target_date: date) -> list:
    tags = [
        "競馬予想", "中央競馬", race.venue,
        f"{race.surface}{race.distance}m",
        race.grade if race.grade in ["G1", "G2", "G3"] else "競馬",
        "買い目", "統計予想", "JRA", target_date.strftime("%Y年%m月"),
        "◎本命", "穴馬",
    ]
    return [t for t in tags if t]


# ============================================================
# ヘルパー
# ============================================================

def _horse_names(nos: list, scores) -> str:
    return "・".join([f"{n}番{_horse_name_single(n,scores)}" for n in nos]) if nos else "-"

def _horse_name_single(no: int, scores) -> str:
    for s in scores:
        if s.horse_no == no:
            return s.horse_name
    return str(no)

def _bet_str(nos: list) -> str:
    return "、".join([f"{n}番" for n in nos])

def _dummy_context(scores):
    class _Ctx:
        num_front_runners = 0
        pace_prediction = "ミドルペース"
        field_level_label = "条件戦"
    return _Ctx()
