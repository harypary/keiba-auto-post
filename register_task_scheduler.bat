@echo off
chcp 65001 >nul
echo ========================================
echo  競馬予想 自動投稿タスク登録（PC側バックアップトリガー）
echo  - 投稿は GitHub Actions が主体（Secrets 管理済み）
echo  - PCが起動していれば、同時刻に gh CLI でGitHub Actionsを発火させバックアップする
echo ========================================
cd /d "%~dp0"

set GH=gh.exe
set REPO=harypary/keiba-auto-post

:: 既存削除
schtasks /delete /tn "keiba_friday_post"   /f >nul 2>&1
schtasks /delete /tn "keiba_saturday_post" /f >nul 2>&1
schtasks /delete /tn "keiba_sunday_post"   /f >nul 2>&1
schtasks /delete /tn "keiba_monday_review" /f >nul 2>&1
schtasks /delete /tn "keiba_data_update_1" /f >nul 2>&1
schtasks /delete /tn "keiba_data_update_2" /f >nul 2>&1

:: ★ 金曜 09:00 → 土曜レース予想をnoteに自動投稿
schtasks /create /tn "keiba_friday_post" ^
  /tr "\"%GH%\" workflow run auto_post.yml --repo %REPO% -f mode=saturday" ^
  /sc WEEKLY /d FRI /st 09:00 /f
echo [OK] 金曜09時 → 土曜予想投稿（GitHub Actionsトリガー）

:: ★ 土曜 09:00 → 日曜レース予想をnoteに自動投稿
schtasks /create /tn "keiba_saturday_post" ^
  /tr "\"%GH%\" workflow run auto_post.yml --repo %REPO% -f mode=sunday" ^
  /sc WEEKLY /d SAT /st 09:00 /f
echo [OK] 土曜09時 → 日曜予想投稿（GitHub Actionsトリガー）

:: 月曜 07:00 → 先週結果照合・重み自動調整
schtasks /create /tn "keiba_monday_review" ^
  /tr "\"%GH%\" workflow run auto_post.yml --repo %REPO% -f mode=review" ^
  /sc WEEKLY /d MON /st 07:00 /f
echo [OK] 月曜07時 → 週次レビュー・重み調整（GitHub Actionsトリガー）

echo.
echo ========================================
echo 自動スケジュール:
echo   金曜 09:00  土曜レース予想を投稿（前日朝）
echo   土曜 09:00  日曜レース予想を投稿（前日朝）
echo   月曜 07:00  結果照合・モデル自動改善
echo ========================================
echo.
echo  ※ GitHub Actionsの cron も同時刻に設定済み（PC OFFでも投稿される二重化）
echo.
echo タスク一覧:
schtasks /query /tn "keiba_friday_post"   /fo LIST 2>nul | findstr "状態 Status 次回実行 Next"
schtasks /query /tn "keiba_saturday_post" /fo LIST 2>nul | findstr "状態 Status 次回実行 Next"
schtasks /query /tn "keiba_monday_review" /fo LIST 2>nul | findstr "状態 Status 次回実行 Next"
pause
