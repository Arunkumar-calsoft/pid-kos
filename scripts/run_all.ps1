# scripts/run_all.ps1
# Runs all phases (0-7) for both PID_0 and PID_2 sequentially.
# Usage: pwsh -File scripts/run_all.ps1
# Optionally set: $env:RUN_PIDS = "PID_0,PID_2"

$env:PYTHONIOENCODING = "utf-8"
$pids = if ($env:RUN_PIDS) { $env:RUN_PIDS -split "," } else { @("PID_0", "PID_2") }
$phases = @("run_phase0.py", "run_phase1.py", "run_phase2.py", "run_phase3.py",
            "run_phase4.py", "run_phase5.py", "run_phase6.py")

$root = Split-Path -Parent $PSScriptRoot

function Run-Phase($script, $pid_id, $extra_args) {
    Write-Host "`n========== $script | PID=$pid_id ==========" -ForegroundColor Cyan
    $args_list = @("scripts/$script", "--pid", $pid_id) + $extra_args
    "y" | python @args_list
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] $script failed for $pid_id (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Set-Location $root

foreach ($pid_id in $pids) {
    Write-Host "`n########## PIPELINE START: $pid_id ##########" -ForegroundColor Yellow
    foreach ($phase in $phases) {
        Run-Phase $phase $pid_id @("--force")
    }
    # Phase 7 needs --auto-approve
    Run-Phase "run_phase7.py" $pid_id @("--auto-approve", "--force")
    Write-Host "`n########## PIPELINE COMPLETE: $pid_id ##########" -ForegroundColor Green
}

Write-Host "`nAll PIDs processed successfully." -ForegroundColor Green
