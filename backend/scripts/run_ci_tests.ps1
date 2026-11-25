# Run the backend test stages the way CI does, against the dedicated test database.
#
# Mirrors .woodpecker/test-fast.yml (lint, format, unit) and
# .woodpecker/test-integration.yml (integration + API, 4 workers), one stage after the
# other so they never compete for the database.
#
# Start the database first:  docker compose -f docker-compose.test.yml up -d
#
# On Windows the asyncpg driver is used: psycopg's async mode refuses the default
# ProactorEventLoop, which errors every async database test. CI (Linux) uses psycopg.
#
# Usage (from the repo root or backend/):
#   powershell -File backend/scripts/run_ci_tests.ps1                  # every stage
#   powershell -File backend/scripts/run_ci_tests.ps1 -Stage unit
#   powershell -File backend/scripts/run_ci_tests.ps1 -Stage integration -Workers 4

param(
    [ValidateSet("all", "lint", "unit", "integration")]
    [string]$Stage = "all",
    [int]$Workers = 4
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$env:DATABASE_URL = "postgresql+asyncpg://test:test@localhost:5433/test_batchivo"
$env:ENVIRONMENT = "test"
$failed = @()

function Invoke-Stage([string]$Name, [scriptblock]$Body) {
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { $script:failed += $Name }
}

if ($Stage -in "all", "lint") {
    Invoke-Stage "ruff check" { poetry run ruff check . }
    Invoke-Stage "ruff format" { poetry run ruff format --check . }
}
if ($Stage -in "all", "unit") {
    Invoke-Stage "unit" {
        poetry run pytest tests/unit/ --tb=short -q -p no:cacheprovider -n $Workers --dist worksteal
    }
}
if ($Stage -in "all", "integration") {
    Invoke-Stage "integration + API" {
        poetry run pytest tests/ --ignore=tests/unit/ --tb=short -q -p no:cacheprovider -n $Workers --dist worksteal
    }
}

if ($failed.Count -gt 0) {
    Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All stages passed" -ForegroundColor Green
