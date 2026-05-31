<#
.SYNOPSIS
  自宅PCのWindowsタスクスケジューラに「馬データ事前取得→Release配信」を週2回登録する。

  - 金曜 17:00 … 翌・土曜分の全頭データを取得してGitHub Releaseへ
  - 土曜 17:00 … 翌・日曜分の全頭データを取得してGitHub Releaseへ

  netkeibaはGitHubの全IPを403ブロックするため、唯一ブロックされない自宅IPで
  先回り取得し、Release経由でクラウドの投稿ジョブへ渡す（恒久対策の取得側）。

  PCがスリープでも WakeToRun で自動起床して実行する。物理電源OFFのときは
  StartWhenAvailable により次回起動時に取りこぼし分を自動実行する。

.NOTES
  実行（管理者権限のPowerShellで一度だけ）:
      powershell -ExecutionPolicy Bypass -File scripts\register_prefetch_task.ps1

  解除:
      powershell -ExecutionPolicy Bypass -File scripts\register_prefetch_task.ps1 -Unregister
#>
param(
    [switch]$Unregister,
    [string]$Time = "17:00"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Script   = Join-Path $RepoRoot "scripts\local_prefetch_upload.py"

$TaskSat = "KeibaPrefetch-Saturday"
$TaskSun = "KeibaPrefetch-Sunday"

if ($Unregister) {
    foreach ($t in @($TaskSat, $TaskSun)) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false
            Write-Host "解除: $t"
        }
    }
    return
}

# python.exe を解決
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
if (-not $Python) { throw "python が見つかりません。PATHを確認してください。" }
Write-Host "Python: $Python"
Write-Host "Repo  : $RepoRoot"

function Register-PrefetchTask {
    param([string]$Name, [string]$DayOfWeek, [string]$Mode)

    $logDir = Join-Path $RepoRoot "data"
    $log    = Join-Path $logDir "prefetch_$Mode.log"
    # cmd.exe 経由で stdout/stderr をログに残す
    $inner  = "`"$Python`" `"$Script`" $Mode >> `"$log`" 2>&1"
    $action = New-ScheduledTaskAction -Execute "cmd.exe" `
                  -Argument "/c $inner" -WorkingDirectory $RepoRoot

    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $Time

    $settings = New-ScheduledTaskSettingsSet `
                    -WakeToRun `
                    -StartWhenAvailable `
                    -AllowStartIfOnBatteries `
                    -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
                    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

    # ログオン中のユーザーで実行（gh のキーリング資格情報を使うため）
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description "競馬: $Mode 分の全頭データを自宅IPで取得しGitHub Releaseへ配信" | Out-Null
    Write-Host "登録: $Name  ($DayOfWeek $Time → mode=$Mode)"
}

Register-PrefetchTask -Name $TaskSat -DayOfWeek Friday   -Mode saturday
Register-PrefetchTask -Name $TaskSun -DayOfWeek Saturday -Mode sunday

Write-Host ""
Write-Host "完了。登録済みタスク:"
Get-ScheduledTask -TaskName "KeibaPrefetch-*" | Format-Table TaskName, State -AutoSize
Write-Host ""
Write-Host "手動テスト: Start-ScheduledTask -TaskName $TaskSun"
Write-Host "ログ確認  : data\prefetch_sunday.log / data\prefetch_saturday.log"
