<#
.SYNOPSIS
  自宅PCのWindowsタスクスケジューラに「馬データ事前取得→Release配信」を登録する。

  ■ 収集タイミングの考え方
  JRAの出馬表（馬ID・確定枠・脚質・オッズ）が公開されるのは木曜午後〜。
  週明け〜水曜は仮登録しか無く収集しても空振りになる。
  そこで「木・金・土の日中、PCが開いていれば何度でも拾いにいく」方式にする。

    - 木/金/土の 09:00〜21:00、3時間おきにトリガ（= その時間帯にPCが開いていれば実行）
    - 毎回 saturday分・sunday分の両方を取得 → GitHub Release へ
    - 既に取得済みの馬は cache 再利用で数十秒、Release は毎回 --clobber で上書き

  PCがスリープでも WakeToRun で自動起床。物理電源OFFのときは StartWhenAvailable
  により次回起動時に取りこぼし分を自動実行する。
  → 木〜土のどこか一度でもPCが開いていれば、週末分のデータが揃う。

.NOTES
  実行（管理者権限のPowerShellで一度だけ）:
      powershell -ExecutionPolicy Bypass -File scripts\register_prefetch_task.ps1

  解除:
      powershell -ExecutionPolicy Bypass -File scripts\register_prefetch_task.ps1 -Unregister

  手動テスト:
      Start-ScheduledTask -TaskName KeibaPrefetch-Weekend
#>
param(
    [switch]$Unregister,
    [string]$StartTime  = "09:00",   # 収集開始時刻
    [int]   $RepeatHours = 3,        # 何時間おきに拾うか
    [int]   $WindowHours = 12        # 何時間ぶん繰り返すか（09:00開始+12h=21:00まで）
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Script   = Join-Path $RepoRoot "scripts\local_prefetch_upload.py"

$TaskName = "KeibaPrefetch-Weekend"
# 旧バージョンで作った曜日別タスクがあれば一緒に掃除する
$OldTasks = @("KeibaPrefetch-Saturday", "KeibaPrefetch-Sunday")

if ($Unregister) {
    foreach ($t in (@($TaskName) + $OldTasks)) {
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

# 旧タスクが残っていたら除去
foreach ($t in (@($TaskName) + $OldTasks)) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
    }
}

# --- 実行内容: saturday分→sunday分を順に取得（片方が空振り/失敗でも両方走るよう & で連結）---
#   PREFETCH_DAYS=3,4,5  … 木金土のみ実行（ログオン/解除トリガが平日に発火しても空振りさせない）
#   PREFETCH_THROTTLE_HOURS=5 … 同じ対象日を直近5h以内に取得済みならスキップ（開く度の無駄取得を防ぐ）
$logSat = Join-Path $RepoRoot "data\prefetch_saturday.log"
$logSun = Join-Path $RepoRoot "data\prefetch_sunday.log"
$inner  = "set `"PREFETCH_DAYS=3,4,5`" & set `"PREFETCH_THROTTLE_HOURS=5`" & " +
          "`"$Python`" `"$Script`" saturday >> `"$logSat`" 2>&1 & " +
          "`"$Python`" `"$Script`" sunday   >> `"$logSun`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
              -Argument "/c $inner" -WorkingDirectory $RepoRoot

# --- トリガ1: 木・金・土の StartTime に開始し、WindowHours ぶん RepeatHours おきに繰り返す ---
$trigger = New-ScheduledTaskTrigger -Weekly `
               -DaysOfWeek Thursday, Friday, Saturday -At $StartTime
# 日中の繰り返しを付与（-Once トリガから Repetition だけ拝借する定番手法）
$rep = (New-ScheduledTaskTrigger -Once -At $StartTime `
            -RepetitionInterval (New-TimeSpan -Hours $RepeatHours) `
            -RepetitionDuration (New-TimeSpan -Hours $WindowHours)).Repetition
$trigger.Repetition = $rep

# --- トリガ2: ログオン時（PC起動→ログイン＝「開いた」）。曜日はスクリプト側ガードで木金土に限定 ---
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# --- トリガ3: ワークステーションのロック解除時（つけっぱなしPCを開いた瞬間）---
#   New-ScheduledTaskTrigger に解除トリガが無いため CIM で直接生成
$unlockTrigger = $null
try {
    $cls = Get-CimClass -Namespace Root/Microsoft/Windows/TaskScheduler `
                        -ClassName MSFT_TaskSessionStateChangeTrigger
    $unlockTrigger = New-CimInstance -CimClass $cls -ClientOnly
    $unlockTrigger.Enabled     = $true
    $unlockTrigger.StateChange = 8          # 8 = TASK_SESSION_UNLOCK
    $unlockTrigger.UserId      = $env:USERNAME
} catch {
    Write-Host "  [warn] ロック解除トリガを作成できませんでした: $($_.Exception.Message)"
}

$triggers = @($trigger, $logonTrigger)
if ($unlockTrigger) { $triggers += $unlockTrigger }

$settings = New-ScheduledTaskSettingsSet `
                -WakeToRun `
                -StartWhenAvailable `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
                -MultipleInstances IgnoreNew `
                -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

# ログオン中のユーザーで実行（gh のキーリング資格情報を使うため）
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal `
    -Description "競馬: 木〜土にPCを開いた瞬間(起動/ログオン/ロック解除)＋日中定期で週末全頭データを自宅IPで取得しGitHub Releaseへ配信" | Out-Null

$endTime = ([datetime]$StartTime).AddHours($WindowHours).ToString("HH:mm")
Write-Host ""
Write-Host "登録: $TaskName"
Write-Host "  曜日       : 木・金・土（スクリプト側ガードで限定）"
Write-Host "  開いた瞬間 : ログオン時＋ロック解除時に強制実行"
Write-Host "  日中定期   : $StartTime 〜 $endTime（$RepeatHours 時間おき）"
Write-Host "  取りこぼし : PC起動時に自動で追いつく（StartWhenAvailable）"
Write-Host "  無駄防止   : 同じ対象日は直近5h以内なら再取得スキップ"
Write-Host ""
Get-ScheduledTask -TaskName $TaskName | Format-Table TaskName, State -AutoSize
Write-Host "手動テスト: Start-ScheduledTask -TaskName $TaskName"
Write-Host "ログ確認  : data\prefetch_saturday.log / data\prefetch_sunday.log"
