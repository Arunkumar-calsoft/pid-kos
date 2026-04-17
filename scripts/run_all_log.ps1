# scripts/run_all_log.ps1
# Like run_all.ps1 but writes per-phase logs and a summary report.
# Usage: powershell -File scripts/run_all_log.ps1

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH      = Split-Path -Parent $PSScriptRoot

$pids_list = if ($env:RUN_PIDS) { $env:RUN_PIDS -split "," } else { @("PID_0", "PID_2") }
$phases = @("run_phase0.py","run_phase1.py","run_phase2.py","run_phase3.py",
            "run_phase4.py","run_phase5.py","run_phase6.py","run_phase7.py")

$root    = Split-Path -Parent $PSScriptRoot
$logDir  = Join-Path $root "logs\pipeline_run"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Set-Location $root

$summary = @()

function Invoke-Phase($script, $pid_id, $extra_args) {
    $label   = "$script | $pid_id"
    $logFile = Join-Path $logDir ($pid_id + "__" + ($script -replace '\.py$','') + ".log")

    Write-Host "`n========== $label ==========" -ForegroundColor Cyan

    $args_list = @("scripts/$script", "--pid", $pid_id) + $extra_args
    # Capture stdout+stderr merged; redirect stderr separately to avoid PS NativeCommandError noise
    $output = ("y" | python @args_list 2>&1) | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
    }

    # Write raw output to log file
    $output | Out-File -FilePath $logFile -Encoding utf8

    # Surface to console
    $output | ForEach-Object { Write-Host $_ }

    # Parse for real errors / warnings (ignore NativeCommandError wrapper lines from PS)
    $errors   = $output | Where-Object { $_ -match 'Traceback|Exception:|Error:' -and $_ -notmatch 'NativeCommandError|RemoteException|CategoryInfo|FullyQualifiedErrorId' }
    $warnings = $output | Where-Object { $_ -match '\[WARN\]|WARNING' -and $_ -notmatch 'NativeCommandError' }

    $status = if ($LASTEXITCODE -ne 0) { "FAIL" } elseif ($errors) { "ERR" } elseif ($warnings) { "WARN" } else { "OK" }

    $summary += [PSCustomObject]@{
        Phase    = $script
        PID      = $pid_id
        Status   = $status
        Errors   = ($errors   | Select-Object -First 3) -join " | "
        Warnings = ($warnings | Select-Object -First 3) -join " | "
        Log      = $logFile
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "FATAL: $label exited $LASTEXITCODE - stopping." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# â”€â”€ Clear database â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host "`n>>> Clearing Neo4j database..." -ForegroundColor Yellow
python scripts/clear_db.py
if ($LASTEXITCODE -ne 0) { Write-Host "FATAL: DB clear failed" -ForegroundColor Red; exit 1 }

# â”€â”€ Register PIDs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host "`n>>> Registering PIDs..." -ForegroundColor Yellow

$reg = @(
    @("--plant-id","PLANT_001","--plant-name","Energy Impact Center","--skid-id","SKID_01","--skid-type","CONDENSATE","--pid-id","PID_0","--graphml","PLANT_001/SKID_01/PID_0/0.graphml","--image","PLANT_001/SKID_01/PID_0/0.png","--rev","A","--date","2020-09-01"),
    @("--plant-id","PLANT_001","--plant-name","Energy Impact Center","--skid-id","SKID_01","--skid-type","CONDENSATE","--pid-id","PID_2","--graphml","PLANT_001/SKID_01/PID_2/2.graphml","--image","PLANT_001/SKID_01/PID_2/2.png","--rev","A","--date","2020-09-01")
)
foreach ($r in $reg) {
    python scripts/register_pid.py @r
    if ($LASTEXITCODE -ne 0) { Write-Host "FATAL: register_pid failed" -ForegroundColor Red; exit 1 }
}

# â”€â”€ Run all phases for each PID â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
foreach ($pid_id in $pids_list) {
    Write-Host "`n########## PIPELINE START: $pid_id ##########" -ForegroundColor Yellow

    $phaseList = $phases | Select-Object -First 7
    foreach ($phase in $phaseList) {   # phase0..phase6
        Invoke-Phase $phase $pid_id @("--force")
    }
    # Phase 7 needs --auto-approve
    Invoke-Phase "run_phase7.py" $pid_id @("--auto-approve", "--force")

    Write-Host "`n########## PIPELINE COMPLETE: $pid_id ##########" -ForegroundColor Green
}

# â”€â”€ Print summary table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Host "`n`n============================================================" -ForegroundColor Magenta
Write-Host "  PHASE SUMMARY" -ForegroundColor Magenta
Write-Host "============================================================" -ForegroundColor Magenta

$summary | Format-Table -AutoSize -Property Phase, PID, Status, Errors | Out-String | Write-Host

# Also save summary CSV
$summaryFile = Join-Path $logDir "summary.csv"
$summary | Export-Csv -Path $summaryFile -NoTypeInformation -Encoding UTF8
Write-Host "Logs saved to: $logDir" -ForegroundColor Cyan
Write-Host "Summary CSV:   $summaryFile" -ForegroundColor Cyan

# Print any non-OK phases details
$failed = $summary | Where-Object { $_.Status -ne "OK" }
if ($failed) {
    Write-Host "`n--- NON-OK PHASES ---" -ForegroundColor Red
    foreach ($f in $failed) {
        Write-Host "`n[$($f.Status)] $($f.Phase) / $($f.PID)" -ForegroundColor Yellow
        if ($f.Errors)   { Write-Host "  ERRORS:   $($f.Errors)"   -ForegroundColor Red }
        if ($f.Warnings) { Write-Host "  WARNINGS: $($f.Warnings)" -ForegroundColor DarkYellow }
        Write-Host "  Full log: $($f.Log)" -ForegroundColor Gray
    }
} else {
    Write-Host "`nAll phases OK." -ForegroundColor Green
}
