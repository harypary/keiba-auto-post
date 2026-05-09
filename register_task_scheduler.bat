@echo off
chcp 65001 >nul
echo ========================================
echo  競馬予想 Windowsタスクスケジューラ登録
echo  ※ 管理者として実行してください
echo ========================================
cd /d "%~dp0"

set PYTHON=%~dp0venv\Scripts\python.exe
set MAIN=%~dp0main.py
set REVIEW=%~dp0weekly_review.py
set BACKTEST=%~dp0run_historical_backtest.py

:: 既存削除
schtasks /delete /tn "keiba_saturday_post"  /f >nul 2>&1
schtasks /delete /tn "keiba_sunday_post"    /f >nul 2>&1
schtasks /delete /tn "keiba_monday_review"  /f >nul 2>&1
schtasks /delete /tn "keiba_data_update_1"  /f >nul 2>&1
schtasks /delete /tn "keiba_data_update_2"  /f >nul 2>&1

:: ★ 金曜 21:00 → 土曜レース予想をnoteに自動投稿
schtasks /create /tn "keiba_saturday_post" ^
  /tr "\"%PYTHON%\" \"%MAIN%\" --run-now saturday" ^
  /sc WEEKLY /d FRI /st 21:00 /rl HIGHEST /f
echo [OK] 金曜21時 → 土曜予想投稿

:: ★ 土曜 21:00 → 日曜レース予想をnoteに自動投稿
schtasks /create /tn "keiba_sunday_post" ^
  /tr "\"%PYTHON%\" \"%MAIN%\" --run-now sunday" ^
  /sc WEEKLY /d SAT /st 21:00 /rl HIGHEST /f
echo [OK] 土曜21時 → 日曜予想投稿

:: 月曜 07:00 → 先週結果照合・重み自動調整
schtasks /create /tn "keiba_monday_review" ^
  /tr "\"%PYTHON%\" \"%REVIEW%\"" ^
  /sc WEEKLY /d MON /st 07:00 /rl HIGHEST /f
echo [OK] 月曜07時 → 週次レビュー・重み調整

echo.
echo ========================================
echo 自動スケジュール:
echo   金曜 21:00  土曜レース予想を投稿
echo   土曜 21:00  日曜レース予想を投稿
echo   月曜 07:00  結果照合・モデル自動改善
echo ========================================
echo.
echo タスク一覧:
schtasks /query /tn "keiba_saturday_post" /fo LIST 2>nul | findstr "状態\|Status\|次回実行\|Next Run"
schtasks /query /tn "keiba_sunday_post"   /fo LIST 2>nul | findstr "状態\|Status\|次回実行\|Next Run"
schtasks /query /tn "keiba_monday_review" /fo LIST 2>nul | findstr "状態\|Status\|次回実行\|Next Run"
pause
