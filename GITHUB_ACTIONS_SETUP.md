# GitHub Actions 自動投稿セットアップ手順

PCが落ちていても自動でnote投稿される、無料クラウド実行環境です。

## 1. GitHubリポジトリ作成（5分）

1. https://github.com/new で **Privateリポジトリ** を作成
2. ローカルからプッシュ：

```bash
cd C:\Users\haryp\game\21.kiba
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
git push -u origin main
```

⚠️ **`.env` は絶対にコミットしないこと**（`.gitignore` 設定済み）

## 2. GitHub Secrets 登録（3分）

リポジトリ → Settings → Secrets and variables → Actions → New repository secret

以下3つを登録：

| Name | Value |
|---|---|
| `NOTE_EMAIL` | `haryparybb@icloud.com` |
| `NOTE_PASSWORD` | （あなたのnote.comパスワード） |
| `NOTE_USER_ID` | `_almanddd` |

## 3. 自動実行スケジュール

`.github/workflows/auto_post.yml` で設定済み：

| 曜日・時刻 (JST) | 内容 |
|---|---|
| 金曜 21:00 | 土曜レース予想 → note投稿 |
| 土曜 21:00 | 日曜レース予想 → note投稿 |
| 月曜 07:00 | 先週結果照合 + モデル自動改善 |

PCの状態に関係なく、GitHubのサーバー上で実行されます。

## 4. 手動実行（テスト）

リポジトリ → Actions タブ → "競馬予想 note自動投稿" → "Run workflow" → モード選択 → 実行

## 5. ログ確認

Actions タブから各実行の詳細ログを確認可能。
artifactsから各実行で生成された予想JSONをダウンロードできます。

## ⚠️ GitHub Actions 無料枠

- Privateリポジトリ: 月2,000分（毎週3回 × 約30分 = 月360分なので余裕）
- パブリックリポジトリ: 無制限

## トラブル対応

- **note.com ログイン失敗**：パスワード変更時は Secret も更新
- **netkeiba スクレイピング失敗**：UA変更が必要かも（`src/scraper/base_scraper.py`）
- **重みが更新されない**：cache設定が正しくないと前回の重みがロードされない
