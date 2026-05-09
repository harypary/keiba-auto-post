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
    return {"title": title, "body": body, "tags": tags, "is_paid": True, "price": 300}


def format_race_note(race, scores, plan, target_date: date, race_index: int, total_races: int) -> dict:
    return format_race_note_v2(race, scores, plan, _dummy_context(scores), target_date, race_index)


def format_day_summary_note(race_list: list[dict], target_date: date, venue_day: str) -> dict:
    date_str = target_date.strftime("%m月%d日")
    track = _get_track_record()
    track_line = f"\n> {track}" if track else ""

    title = f"【{date_str}({venue_day})】◎本命厳選！中央競馬 全レース完全データ予想パック"

    body_parts = [
        f"# {date_str}({venue_day}) 全レース予想パック\n\n",
        f"{track_line}\n\n" if track_line else "",
        _day_summary_hook(race_list, venue_day),
        "---\n\n",
        f"{PAID_MARKER}\n\n",
        f"## 🔓 各レース完全予想（全{len(race_list)}レース）\n\n",
    ]
    for item in race_list:
        body_parts.append(_build_pack_section(item["race"], item["scores"], item["plan"]))
    body_parts.append("\n---\n## ⚠️ 免責事項\n競馬は娯楽です。余裕資金でお楽しみください。20歳以上から。\n")
    return {
        "title": title,
        "body": "".join(body_parts),
        "tags": ["競馬予想", "中央競馬", "全レース", "買い目", "JRA", "統計予想", venue_day],
        "is_paid": True, "price": 1500,
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
    parts.append(_section_free_hook(race, scores, plan))  # 煽りティーザー

    # ---- 有料ゾーン ----
    parts.append(f"\n---\n\n## {PAID_MARKER}\n\n")
    parts.append(_section_pace(context, race))
    parts.append(_section_full_ranking(scores, race))
    parts.append(_section_betting(scores, plan))
    parts.append(_section_footer())
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
            "> 全頭データを徹底分析した本命馬と穴馬を公開しています。\n"
            "> 一度の的中でも十分元が取れる300円です。\n\n"
        )
    if g in ("G2", "G3"):
        return (
            "> 📣 **重賞は高配当のチャンス。**\n"
            "> 統計データが示す「消し」と「狙い目」を有料部分で公開。\n"
            "> 情報収集コストを考えれば300円は安いはず。\n\n"
        )
    return (
        "> 📣 **毎週コツコツ回収率プラスを目指しています。**\n"
        "> 本命から穴馬まで、データが導く答えを有料部分で公開。\n"
        "> 1レース300円。当たれば十分元が取れます。\n\n"
    )


def _day_summary_hook(race_list, venue_day) -> str:
    total = len(race_list)
    return (
        f"## 本日{total}レースの完全予想パック\n\n"
        f"毎週{venue_day}の全開催場・全レース（未勝利〜G1）を統計データで分析。\n"
        f"単品{total}×300円 = {total*300}円のところ、**まとめ買いで1,500円**。\n\n"
        f"各馬の過去全成績・血統・騎手相性・展開・敵レベルを統合した\n"
        f"独自スコアで◎本命から穴馬まで完全公開します。\n\n"
    )


def _section_pace(context, race) -> str:
    front = getattr(context, "num_front_runners", 0)
    pace = getattr(context, "pace_prediction", "ミドルペース")
    level = getattr(context, "field_level_label", "条件戦メンバー")
    pace_emoji = {"ハイペース": "🔥", "ミドルペース": "⚡", "スローペース": "🐌"}.get(pace, "⚡")
    pace_desc = _pace_description(pace, front, race.num_horses, race.distance, race.surface)
    return (
        f"## {pace_emoji} 展開予測: **{pace}**\n\n"
        f"先行想定：{front}頭 ／ メンバーレベル：**{level}**\n\n"
        f"{pace_desc}\n\n"
    )


def _section_full_ranking(scores, race) -> str:
    parts = ["## 🏆 全頭完全分析・順位付け\n\n"]
    parts.append("> 評点は統計総合値（過去全レース・血統・騎手相性・展開・敵レベル）。100点満点換算の相対評価です。\n\n")

    for rank, s in enumerate(sorted(scores, key=lambda x: x.recommendation_rank), 1):
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

        aff_obj = getattr(s, "affinity", None)
        aff_txt = ""
        if aff_obj and aff_obj.total >= 2:
            aff_txt = f"（{aff_obj.wins}勝/{aff_obj.total}戦・複勝率{aff_obj.place_rate*100:.0f}%）"

        raw = getattr(s, "raw_stat", None)

        # 本命・対抗は強調
        header_prefix = "🔥 " if rank == 1 else ("✅ " if rank == 2 else "")
        parts.append(f"### {rank}位 {mark} {s.horse_no}番 **{s.horse_name}**　評点: **{final:.1f}** {header_prefix}\n\n")
        parts.append(f"| 騎手 | 脚質 | 斤量 | 通算 | 勝率 | 複勝率 | スピード指数 |\n")
        parts.append(f"|---|---|---|---|---|---|---|\n")
        parts.append(
            f"| {s.jockey} | {style} | {s.weight_carry}kg "
            f"| {races}戦 | {wr*100:.0f}% | {pr*100:.0f}% | {spd:.0f} |\n\n"
        )

        parts.append(f"**📝 分析**\n\n{narrative}\n\n")

        parts.append("**📊 評点内訳**\n\n")
        parts.append("| 基本統計 | 近走フォーム | 騎手相性 | 血統 | 展開 | 敵レベル補正 | **総合** |\n")
        parts.append("|---|---|---|---|---|---|---|\n")
        form = getattr(s, "form_score", 0)
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

        parts.append("---\n")

    return "".join(parts)


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
