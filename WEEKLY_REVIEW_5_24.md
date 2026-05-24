# 2026/5/22-24 週次反省レポート

## 結果サマリー

| 日 | 期待 | 実績 |
|---|---|---|
| 5/23 (土) 土曜分 | 36レース投稿 | 数件投稿、ほぼ未達 |
| 5/24 (日) 日曜分 | 36レース投稿 | ~22件投稿（プロフィール表示 16件）、重複3ペア発生 |

## 起きた問題

### 1. netkeiba.com の Bot ブロック
- **問題**: GitHub Actions の Ubuntu IP帯が `db.netkeiba.com`（馬個別ページ）を 403 でブロック
- **影響**: 馬データ取得 → 1馬あたり robust_fetch で最大120秒 → 36レース処理が10時間超に
- **応急対応**: サーキットブレーカーで諦め判定の高速化、SCRAPE_MODE=fast 導入

### 2. playwright sync API の競合
- **問題**: `playwright_fetcher`（馬データ用）と `note_publisher`（投稿用）が同プロセスで sync_playwright を多重起動 → `asyncio loop` 例外で全投稿失敗
- **影響**: 1時間以上 1件も投稿されない事象
- **修正**: `DISABLE_PLAYWRIGHT_FETCH=1` で投稿用 playwright のみ動作

### 3. 重複投稿
- **問題**: 複数の workflow run が同時実行（schedule + workflow_dispatch + cancelled runs の inline retry）
- **影響**: 同一レースの記事が複数公開（東京1Rx3、東京2Rx2 等）
- **修正**: 
  - `concurrency: group: auto-post-${mode}` で同モード並行禁止
  - 投稿直前 note.com 再スキャン
  - `find_and_publish_drafts` に race_key 重複チェック

### 4. Google Cache が使えない
- **問題**: 2024年廃止、リダイレクトのみ返す → fallback layer として無効
- **修正**: robust_fetch から実質除外、Wayback Machine と playwright 直アクセスを優先

### 5. プロフィールページ表示制限
- **問題**: note.com profile は最新 ~18件しか表示しない → 投稿数の正確な把握が困難
- **対策**: ローカル投稿ログ（`data/published_articles.json`）を artifact 化、cross-run 共有

### 6. macOS prefetch の不発
- **問題**: macOS runner で playwright 直アクセスを期待したが、`playwright install chromium` 抜けで起動失敗 → 成功 0頭
- **修正**: install step に `playwright install chromium` 追加（次週から有効）

## 今週の真因

**「データソース1個（netkeiba）依存」+「環境依存（GH Actions IP がブロック対象）」のダブルパンチ**。
冗長化が無い設計で、netkeiba がコケた瞬間に全停止。

## 来週に向けた改善（実装済 + 計画）

### A. データソース冗長化
- ✅ Wayback Machine フォールバック
- ✅ macOS runner で別IP帯のキャッシュ事前構築（金土17:00）
- ⏳ keibalab / sportsnavi 等の代替ソース実装（来週中）

### B. プロセス分離による競合解消
- ✅ prefetch は別 workflow（macOS）で playwright 自由使用
- ✅ auto_post は Ubuntu で DISABLE_PLAYWRIGHT_FETCH=1（投稿用 playwright のみ）
- ✅ cleanup_duplicates も別 workflow（投稿と非干渉）

### C. 重複絶対防止
- ✅ concurrency group で同モード並行禁止
- ✅ 投稿直前 note.com 再スキャン
- ✅ 永続投稿ログ（artifact 90日保持）
- ✅ find_and_publish_drafts に race_key dedup
- ⏳ 自動 cleanup workflow（土日深夜起動、既設定済み）

### D. 進捗可視化
- ✅ ストリーミング投稿（解析→即投稿）
- ✅ Monitor で 30秒毎に変化通知

## 来週の自動スケジュール

| 時刻 (JST) | workflow |
|---|---|
| 金 17:00 | prefetch (macOS, 土曜分) |
| 金 20:30〜22:00 | auto_post saturday × 4回 |
| 金 22:00〜翌1:30 | publish_retry × 8回 |
| 土 01:00 | cleanup_duplicates 自動 |
| 土 17:00 | prefetch (macOS, 日曜分) |
| 土 20:30〜22:00 | auto_post sunday × 4回 |
| 土 22:00〜翌1:30 | publish_retry × 8回 |
| 日 01:00 | cleanup_duplicates 自動 |
| 月 07:00 | weekly review + ML 再学習 |

## データ収集強化（来週中に実装）

1. **複数データソースからの集約**: jra.go.jp 公式ページ + keibalab + 既存 netkeiba
2. **過去レース結果の網羅取得**: 直近1年の全レース結果をバッチ取得 → ML学習データに追加
3. **新規キャッシュビルダー workflow**: 平日深夜に未取得馬を補完取得（土日のスパイク回避）
4. **オッズ時系列**: 投票終盤と最終のオッズ変化を記録 → ML 特徴量化

## 来週の目標

- 土日それぞれ 36 レース完投（重複ゼロ）
- 投稿エラー時の即時自動復旧
- 予測精度: ◎勝率 20% 以上を目指す（前週 16.7%）
