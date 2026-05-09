$ErrorActionPreference = 'SilentlyContinue'
$names = @('keiba_friday_post','keiba_saturday_post','keiba_sunday_post','keiba_monday_review','keiba_weekly_review','keiba_data_update_1','keiba_data_update_2')
foreach ($n in $names) { schtasks /delete /tn $n /f 2>$null | Out-Null }

$gh = (Get-Command gh).Source
$repo = 'harypary/keiba-auto-post'

# Quote path with backslash-escaped quotes for schtasks /tr
$ghQ = '\"' + $gh + '\"'
$friTr = "$ghQ workflow run auto_post.yml --repo $repo -f mode=saturday"
$satTr = "$ghQ workflow run auto_post.yml --repo $repo -f mode=sunday"
$monTr = "$ghQ workflow run auto_post.yml --repo $repo -f mode=review"

& schtasks /create /tn keiba_friday_post   /tr $friTr /sc WEEKLY /d FRI /st 09:00 /f
& schtasks /create /tn keiba_saturday_post /tr $satTr /sc WEEKLY /d SAT /st 09:00 /f
& schtasks /create /tn keiba_monday_review /tr $monTr /sc WEEKLY /d MON /st 07:00 /f

Write-Host ""
Write-Host "=== Registered Tasks ==="
Get-ScheduledTask | Where-Object { $_.TaskName -like 'keiba_*' } | ForEach-Object {
    $next = (Get-ScheduledTaskInfo -TaskName $_.TaskName).NextRunTime
    Write-Host ("{0,-25} Next: {1}" -f $_.TaskName, $next)
}
