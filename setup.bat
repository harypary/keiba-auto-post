@echo off
chcp 65001 >nul
echo ========================================
echo 競馬予想note投稿システム セットアップ
echo ========================================
cd /d "%~dp0"

:: Python確認
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [エラー] Python がインストールされていません
    echo https://www.python.org/ からインストールしてください
    pause
    exit /b 1
)

:: 仮想環境作成
echo [1/4] 仮想環境を作成中...
python -m venv venv
call venv\Scripts\activate.bat

:: パッケージインストール
echo [2/4] 必要パッケージをインストール中...
pip install -r requirements.txt

:: フォルダ作成
echo [3/4] フォルダを作成中...
if not exist data\cache mkdir data\cache
if not exist data\output mkdir data\output
if not exist logs mkdir logs

:: .env作成
echo [4/4] 設定ファイルを確認中...
if not exist .env (
    copy .env.example .env
    echo.
    echo [重要] .env ファイルを編集して設定を入力してください:
    echo   - ANTHROPIC_API_KEY
    echo   - NOTE_EMAIL
    echo   - NOTE_PASSWORD
    echo   - NOTE_USER_ID
    echo.
    notepad .env
) else (
    echo .env ファイルは既に存在します
)

echo.
echo ========================================
echo セットアップ完了！
echo テスト実行: test_dryrun.bat
echo 本番起動: start_scheduler.bat
echo ========================================
pause
