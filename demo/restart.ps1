# restart.ps1 — restart the demo environment without wiping data
#
# Usage:
#   .\demo\restart.ps1           — restart everything
#   .\demo\restart.ps1 dashboard — restart dashboard only
#   .\demo\restart.ps1 generator — restart generator only
#   .\demo\restart.ps1 full      — wipe all data and start fresh (re-seeds automatically)

param(
    [string]$Target = "all"
)

$WorkshopDir = Split-Path -Parent $PSScriptRoot
Set-Location $WorkshopDir

switch ($Target) {

    "dashboard" {
        Write-Host "Restarting dashboard..." -ForegroundColor Cyan
        docker compose restart dashboard
        Write-Host "Dashboard restarted. Open http://localhost:8080" -ForegroundColor Green
    }

    "generator" {
        Write-Host "Restarting generator..." -ForegroundColor Cyan
        docker compose stop generator
        docker compose up generator -d
        Write-Host "Generator restarted (demo mode, 2s ticks)." -ForegroundColor Green
    }

    "full" {
        Write-Host "Full reset — wiping all data..." -ForegroundColor Yellow
        docker compose down -v
        Write-Host "Starting databases and dashboard..." -ForegroundColor Cyan
        docker compose up source-db warehouse-db dashboard -d
        Write-Host "Waiting for Postgres to initialise (15s)..." -ForegroundColor Cyan
        Start-Sleep -Seconds 15
        Write-Host "Seeding 30 days of historical data..." -ForegroundColor Cyan
        docker compose run --rm generator python generate.py seed 30
        Write-Host "Loading warehouse..." -ForegroundColor Cyan
        docker compose --profile etl run --rm -e ETL_MODE=FULL etl
        Write-Host "Starting generator..." -ForegroundColor Cyan
        docker compose up generator -d
        Write-Host ""
        Write-Host "Full reset complete. Dashboard: http://localhost:8080" -ForegroundColor Green
    }

    default {
        Write-Host "Restarting all services..." -ForegroundColor Cyan
        docker compose restart source-db warehouse-db dashboard
        docker compose stop generator
        docker compose up generator -d
        Write-Host "All services restarted. Dashboard: http://localhost:8080" -ForegroundColor Green
    }
}
