@echo off
chcp 65001 >nul
echo テスト実行（note投稿なし・ファイル保存のみ）
cd /d "%~dp0"

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: 翌日の予想をドライラン
python main.py --dry-run --run-now saturday

echo.
echo 生成ファイルは data\output\ フォルダを確認してください
pause
