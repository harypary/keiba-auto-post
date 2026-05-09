' 競馬予想システム 完全自動化セットアップ
' ダブルクリックで管理者権限で自動実行
Set objShell = CreateObject("Shell.Application")
objShell.ShellExecute "cmd.exe", "/c """ & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\register_task_scheduler.bat""", "", "runas", 1
