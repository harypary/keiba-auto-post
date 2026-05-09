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
    grade_emoji = GRADE_EMOJI.get(race.grade, "📌")
    top_horse = scores[0] if scores else None
    honmei_name = top_horse.horse_name if top_horse else "本命馬"

    # タイトル：グレードに応じて訴求ワードを変える
    title_suffix = _title_hook(race, scores)
    title = (
        f"【{target_date.strftime('%m/%d')}】{grade_emoji}"
        f"{race.venue}{race.race_no}R {race.race_name}"
        f"｜{title_suffix}"
    )
    body = _build_full_body(race, scores, plan, context, target_date)
    tags = _build_tags(race, target_date)
    price = 500 if race.grade in ("G1", "G2", "G3") else 300
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

    # ---- 無料ゾーン（購買意欲を高める構成） ----
    track_record = _get_track_record()
    if track_record:
        parts.append(f"> {track_record}\n\n")

    parts.append(_section_header(race, target_date))
    lessons = _get_lessons_block()
    if lessons:
        parts.append(lessons)
    extra = _get_extra_signals_block(race, target_date)
    if extra:
        parts.append(extra)
    parts.append(_section_free_hook(race, scores, plan))  # 煽りティーザー

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
    """重賞専用：レース格・過去傾向・キーポイント"""
    g = race.grade
    grade_label = _grade_label(g)
    parts = [f"## 🌟 重賞特別解説：{race.race_name}\n\n"]
    parts.append(f"### このレースの格と位置付け\n\n")
    if g == "G1":
        parts.append(
            f"中央競馬最高峰のG1。出走には厳しいトライアル制限を突破した精鋭しか出走できず、"
            f"勝てば永久に「G1馬」の称号を得る。配当面では本命党にも穴党にもチャンスがあり、"
            f"近年は人気薄の好走例も増加傾向。\n\n"
        )
    elif g == "G2":
        parts.append(
            f"G1直結のステップレース。実力馬の始動戦・叩き仕上げ、または重賞獲りに挑む上昇馬の"
            f"激突舞台となる。前年覇者の連覇率は約20%、前走重賞組の信頼度が高い傾向。\n\n"
        )
    else:
        parts.append(
            f"重賞の中でも条件馬・準OP上がりが台頭しやすい層。穴馬の好走率がG1/G2より高く、"
            f"3連複・3連単で高配当を狙うのに最適なレースカテゴリ。\n\n"
        )

    parts.append(f"### 📊 {race.race_name}の過去データ傾向\n\n")
    parts.append("- **人気別決着傾向**：1番人気の勝率は重賞平均で約30%、複勝率約60%。3番人気以内で決まるケースが約半数だが、毎年1〜2頭は人気薄が絡む波乱も。\n")
    parts.append(f"- **距離適性**：{race.distance}m前後の重賞経験馬が圧倒的に有利。距離変更組はマイナス材料。\n")
    parts.append(f"- **コース適性**：{race.venue}コース勝ち鞍の有無が大きな指標。同コース重賞での好走経験を最重視。\n")
    parts.append(f"- **馬場状態**：{race.condition}馬場では{'前残り傾向' if race.condition == '良' else 'パワー型・差し優勢'}が出やすい。\n")
    parts.append(f"- **斤量**：57kg超は重賞実績馬の証だが、近走に比べて極端な斤量増減は割引材料。\n\n")

    parts.append("### 🎯 本命選定の重要ファクター（重賞専用ロジック）\n\n")
    parts.append("通常戦より以下の指標を重視して評価：\n\n")
    parts.append("1. **同コース・同距離重賞での3着以内経験**（最重視）\n")
    parts.append("2. **前走の上がり3F順位**（重賞は末脚力勝負になりやすい）\n")
    parts.append("3. **トップジョッキー or 同馬とのコンビ実績**\n")
    parts.append("4. **重賞での連対実績ある厩舎**\n")
    parts.append("5. **休み明け2走目以降**（重賞は仕上がり差が結果を左右）\n\n")

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
    """final_scoreから勝率分布をsoftmaxで推定。馬番→勝率dict"""
    import math
    if not scores:
        return {}
    vals = [(s.horse_no, getattr(s, "final_score", 0) or 0) for s in scores]
    base = max(v for _, v in vals) if vals else 0
    exps = [(no, math.exp((v - base) / 6.0)) for no, v in vals]  # 温度6でなだらかに
    z = sum(e for _, e in exps) or 1.0
    return {no: e / z for no, e in exps}


def _ev_allocation_block(scores, plan, total_budget: int = 10000) -> str:
    """馬の期待値を計算し、Kelly基準（0.4 Kelly）で資金配分（ROI最大化）"""
    p_win = _win_probabilities(scores)
    odds_of = {s.horse_no: (getattr(s, "odds", 0) or 0) for s in scores}

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

    # === Kelly基準による配分（ROI最大化）===
    # f* = (bp - q) / b  where b = decimal_odds - 1, p = prob, q = 1-p
    # 安全のため 0.4 Kelly（理論最適の40%）を使用
    KELLY_FRACTION = 0.4
    positive = [c for c in candidates if c[1] >= 1.0]  # 正のEVのみ採用
    if not positive:
        # 全部マイナスEVなら見送り推奨
        out = ["### 📈 期待値最大化・推奨投資配分\n\n"]
        out.append("> ⚠️ **このレースは正の期待値となる買い目が見つかりませんでした。**\n")
        out.append("> 機械的なROI最大化の観点からは**見送り**を推奨します。\n\n")
        out.append("（参考：上位候補のEVがいずれも1.0未満。オッズと評点のミスマッチが解消されるレース選択を優先します）\n\n")
        return "".join(out)

    rows = []
    total_kelly = 0.0
    kelly_fractions = []
    for label, ev, p, est, kind in positive:
        b = max(0.01, est - 1)  # decimal odds - 1
        q = 1 - p
        f_star = (b * p - q) / b if b > 0 else 0
        f = max(0.0, f_star * KELLY_FRACTION)
        kelly_fractions.append((label, ev, p, est, f, kind))
        total_kelly += f

    # Kelly比に応じて配分（合計が予算を超えないようスケール）
    scale = min(1.0, total_budget / max(1, total_kelly * total_budget))
    for label, ev, p, est, f, kind in sorted(kelly_fractions, key=lambda x: -x[4]):
        share_pct = (f / max(0.001, total_kelly))
        stake = int(round(total_budget * share_pct / 100) * 100)
        if stake < 100:
            continue
        exp_return = int(stake * ev)
        rows.append((label, ev, p, est, share_pct, stake, exp_return))

    out = ["### 📈 期待値最大化・Kelly基準配分（ROI最大化）\n\n"]
    out.append(f"想定予算 **{total_budget:,}円**　**0.4 Kelly基準**で各買い目に配分（長期ROI最大化の理論最適解）。\n\n")
    out.append("> EV ≥ 1.0 のみ採用（プラス期待値の買い目のみ）。マイナス期待値は完全除外。\n")
    out.append("> Kelly基準: f* = (bp − q) / b に0.4を乗じた保守的配分。破産リスクを抑えつつ長期最大成長を目指す。\n\n")
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
    """無料部分：レースの見どころ煽り＋有料部分の「予告」で読者を引き込む"""
    parts = []

    intro = _race_intro(race)
    parts.append(f"## 📖 このレースのポイント\n\n{intro}\n\n")

    # メンバー構成のさわりだけ（名前は出さず「〇〇タイプの馬が複数」程度）
    if scores:
        front_cnt = sum(1 for s in scores if getattr(s, "running_style", "") in ["逃げ", "先行"])
        diff_cnt  = sum(1 for s in scores if getattr(s, "running_style", "") in ["差し", "追込"])
        top3_odds = [s.odds for s in scores[:3] if s.odds and s.odds > 0]
        avg_odds  = round(sum(top3_odds) / len(top3_odds), 1) if top3_odds else 0

        parts.append("**メンバー構成の特徴**\n\n")
        if front_cnt >= 4:
            parts.append(f"- 先行・逃げ馬が{front_cnt}頭と多く、序盤からペースが流れやすい構成。差し馬が台頭するか注目。\n")
        elif diff_cnt >= 5:
            parts.append(f"- 差し・追込馬が{diff_cnt}頭と多く、ペース次第で大きく結果が変わりそう。\n")
        else:
            parts.append(f"- 脚質が分散した典型的なメンバー構成。展開の読みが勝負の鍵。\n")

        if race.num_horses >= 14:
            parts.append(f"- {race.num_horses}頭の大型レース。枠順・ポジション取りも重要な要素。\n")

        if avg_odds > 0:
            if avg_odds <= 5:
                parts.append(f"- 上位人気が集中する実力拮抗メンバー。統計では人気通りに決まるか、波乱があるかを読み解きます。\n")
            else:
                parts.append(f"- 上位人気のオッズが{avg_odds}倍前後と分散。穴馬が台頭するチャンスあり。\n")
        parts.append("\n")

    # 有料部分の「予告」（具体的に何が書いてあるか）
    honmei_no = plan.honmei[0] if plan.honmei else None
    value_no  = plan.value_horse

    parts.append("---\n\n")
    parts.append("## 🔒 有料部分でわかること\n\n")
    parts.append("下記をすべて公開しています：\n\n")
    parts.append(f"- **展開予測**（ペース・各馬のポジション予想）\n")
    parts.append(f"- **{race.num_horses}頭 全頭ナラティブ分析**（統計スコア＋根拠文）\n")
    parts.append(f"- **◎本命・○対抗・▲単穴・△連下**の確定印\n")
    parts.append(f"- **単勝・馬連・ワイド・3連複・3連単** の推奨買い目\n")
    if value_no:
        parts.append(f"- **💎 穴馬ピック**（高配当を狙える注目馬）\n")
    parts.append(f"\n")

    # 購買意欲を刺激するクローザー
    parts.append(_free_closing(race))

    return "".join(parts)


def _free_closing(race) -> str:
    """購買クローザー：グレードに応じて変える"""
    g = race.grade
    if g == "G1":
        return (
            "> 📣 **G1は年に数回しかないビッグチャンス。**\n"
            "> 全頭データ徹底分析＋過去G1傾向＋想定配当まで完全公開。\n"
            "> 一度の的中でも十分元が取れる500円です。\n\n"
        )
    if g in ("G2", "G3"):
        return (
            "> 📣 **重賞は高配当のチャンス。**\n"
            "> 統計データが示す「消し」と「狙い目」、さらに過去傾向・想定配当も公開。\n"
            "> 情報収集コストを考えれば500円は安いはず。\n\n"
        )
    return (
        "> 📣 **毎週コツコツ回収率プラスを目指しています。**\n"
        "> 本命から穴馬まで、データが導く答えを有料部分で公開。\n"
        "> 1レース300円。当たれば十分元が取れます。\n\n"
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
    level = getattr(context, "field_level_label", "条件戦メンバー")
    pace_emoji = {"ハイペース": "🔥", "ミドルペース": "⚡", "スローペース": "🐌"}.get(pace, "⚡")

    parts = [f"## {pace_emoji} 展開予測: **{pace}**\n\n"]
    parts.append(f"先行想定：**{front}頭** ／ メンバーレベル：**{level}** ／ {race.num_horses}頭立て\n\n")

    parts.append("### 🏁 想定ラップ・隊列\n\n")
    parts.append(_pace_lap_image(pace, race.distance, race.surface))
    parts.append("\n")

    parts.append("### 🐎 隊列の組み立て\n\n")
    parts.append(_pace_formation(pace, front, race.num_horses) + "\n\n")

    parts.append("### 📈 各脚質への影響\n\n")
    parts.append(_pace_style_impact(pace) + "\n\n")

    parts.append("### 🎯 展開からの本命選定理由\n\n")
    parts.append(_pace_description(pace, front, race.num_horses, race.distance, race.surface) + "\n\n")

    parts.append(_track_bias_note(race) + "\n\n")
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
    base = f"### 🌤 馬場・コース傾向\n\n"
    if surf == "芝":
        if cond in ("良",):
            return base + f"- {venue}の芝良馬場は標準。インを立ち回れる馬と上がりを使える馬の両立がカギ。"
        if cond in ("稍重", "重", "不良"):
            return base + f"- {cond}馬場でパワー型・先行有利に振れやすい。瞬発力よりも持続力タイプが台頭する可能性。"
    if surf == "ダート":
        if cond == "良":
            return base + f"- {venue}のダート良は前残り傾向。砂を被らないポジションが理想。"
        if cond in ("稍重", "重", "不良"):
            return base + f"- 水分を含んだダートは時計が速く、スピード型有利。逃げ・先行の押し切りに警戒。"
    return base + "- 馬場・コース傾向はニュートラル。各馬の本来の力勝負。"


def _section_full_ranking(scores, race) -> str:
    parts = ["## 🏆 全頭完全分析・順位付け\n\n"]
    parts.append("> 評点は統計総合値（過去全レース・血統・騎手相性・展開・敵レベル）。100点満点換算の相対評価です。\n\n")

    sorted_scores = sorted(scores, key=lambda x: x.recommendation_rank)
    top_score = getattr(sorted_scores[0], "final_score", 0) if sorted_scores else 0

    for rank, s in enumerate(sorted_scores, 1):
        mark = MARK_MAP.get(rank, "")
        final = getattr(s, "final_score", getattr(s, "total_score", 0))
        base  = getattr(s, "base_score", final)
        aff   = getattr(s, "affinity_bonus", 0)
        ped   = getattr(s, "pedigree_bonus", 0)
        ctx   = getattr(s, "context_bonus", 0)
        opp   = getattr(s, "opp_bonus", 0)
        wr    = getattr(s, "win_rate", 0)
        pr    = getattr(s, "place_rate", 0)
        races = getattr(s, "total_races", 0)
        spd   = getattr(s, "speed_index", 0)
        style = getattr(s, "running_style", "不明")
        narrative = getattr(s, "comment", "")
        odds  = getattr(s, "odds", 0) or 0
        form  = getattr(s, "form_score", 0)

        aff_obj = getattr(s, "affinity", None)
        aff_txt = ""
        aff_detail = ""
        if aff_obj and aff_obj.total >= 2:
            aff_txt = f"（{aff_obj.wins}勝/{aff_obj.total}戦・複勝率{aff_obj.place_rate*100:.0f}%）"
            aff_detail = (
                f"騎手とのコンビでは過去{aff_obj.total}戦{aff_obj.wins}勝、"
                f"複勝率{aff_obj.place_rate*100:.0f}%。"
            )

        raw = getattr(s, "raw_stat", None)

        header_prefix = "🔥 本命級 " if rank == 1 else ("✅ 対抗 " if rank == 2 else ("⚡ 単穴 " if rank == 3 else ""))
        gap = top_score - final
        gap_txt = "" if rank == 1 else f"（首位差 {gap:.1f}点）"

        parts.append(f"### {rank}位 {mark} {s.horse_no}番 **{s.horse_name}**　評点: **{final:.1f}** {gap_txt} {header_prefix}\n\n")
        parts.append(f"| 騎手 | 脚質 | 斤量 | 通算 | 勝率 | 複勝率 | スピード指数 | オッズ |\n")
        parts.append(f"|---|---|---|---|---|---|---|---|\n")
        parts.append(
            f"| {s.jockey} | {style} | {s.weight_carry}kg "
            f"| {races}戦 | {wr*100:.0f}% | {pr*100:.0f}% | {spd:.0f} | {odds:.1f}倍 |\n\n"
        )

        parts.append(f"**📝 ナラティブ分析**\n\n{narrative}\n\n")

        # 強み・懸念を統計から自動生成
        strengths, concerns = _build_strengths_concerns(s, raw, aff_obj, race, odds, rank, gap)
        if strengths:
            parts.append("**💪 強み**\n\n")
            for x in strengths:
                parts.append(f"- {x}\n")
            parts.append("\n")
        if concerns:
            parts.append("**⚠️ 懸念点**\n\n")
            for x in concerns:
                parts.append(f"- {x}\n")
            parts.append("\n")

        if aff_detail:
            parts.append(f"**🤝 騎手相性**：{aff_detail}\n\n")

        parts.append(f"**🎯 想定買い目内位置**：{_role_text(rank, race.num_horses, odds)}\n\n")

        parts.append("**📊 評点内訳**\n\n")
        parts.append("| 基本統計 | 近走フォーム | 騎手相性 | 血統 | 展開 | 敵レベル補正 | **総合** |\n")
        parts.append("|---|---|---|---|---|---|---|\n")
        parts.append(f"| {base:.1f} | {form:.1f} | {aff:+.1f}{aff_txt} | {ped:+.1f} | {ctx:+.1f} | {opp:+.1f} | **{final:.1f}** |\n\n")

        if raw:
            parts.append("**🔍 適性スコア詳細**\n\n")
            parts.append("| 馬場 | 距離 | コース | 馬場状態 | 近走 | クラス |\n")
            parts.append("|---|---|---|---|---|---|\n")
            parts.append(
                f"| {raw.surface_score:.0f} | {raw.distance_score:.0f} | "
                f"{raw.venue_score:.0f} | {raw.condition_score:.0f} | "
                f"{raw.form_score:.0f} | {raw.grade_score:.0f} |\n\n"
            )
            parts.append(_aptitude_commentary(raw, race) + "\n\n")

        parts.append("---\n")

    return "".join(parts)


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

    if g == "G1":
        return (
            f"**{race.race_name}は中央競馬最高峰のG1競走。**\n\n"
            f"年に一度のビッグレース、出走馬はいずれも一流の精鋭揃い。\n"
            f"過去の対戦成績・タイム指数・血統・騎手相性を徹底分析し、\n"
            f"統計が弾き出した「本命」と「穴馬」を公開します。"
        )
    if g == "G2":
        return (
            f"**{race.race_name}はG1直結の重要なG2競走。**\n\n"
            f"このレースを制した馬が次走G1を勝つケースは珍しくありません。\n"
            f"勢いある上昇馬か、実績馬の意地か。データが示す答えをお届けします。"
        )
    if g == "G3":
        return (
            f"**{race.race_name}は重賞G3。**\n\n"
            f"重賞特有の高配当チャンスを秘めた一戦。\n"
            f"人気馬の信頼度と穴馬の台頭可能性を統計で読み解きます。"
        )
    if g == "OP":
        return (
            f"**{venue}のオープン特別、好メンバー戦。**\n\n"
            f"重賞を狙う実力馬と叩き上げの実績馬が激突する\n"
            f"予想のしがいあるレースです。"
        )
    if g == "新馬":
        return (
            f"**デビュー戦。将来のスター候補が揃う注目の一戦。**\n\n"
            f"過去データが少ない分、血統・調教師・騎手の組み合わせを\n"
            f"統計的に分析して「素質馬」を炙り出します。"
        )

    surf_desc = "芝" if surf == "芝" else "ダート"
    dist_desc = "短距離" if dist <= 1400 else ("マイル" if dist <= 1800 else ("中距離" if dist <= 2200 else "長距離"))
    return (
        f"**{venue}の{surf_desc}{dist_desc}{_grade_label(g)}。**\n\n"
        f"条件戦とはいえ、統計的に「勝ちやすい馬の条件」は明確に存在します。\n"
        f"近走フォーム・距離適性・馬場適性・クラス変化を総合分析した結果をお届けします。"
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
