$ErrorActionPreference = "Stop"

$previousEnvironment = @{
    DATABASE_URL = $env:DATABASE_URL
    POSTGRES_PASSWORD = $env:POSTGRES_PASSWORD
    PYTHONPATH = $env:PYTHONPATH
    GEMINI_ENABLED = $env:GEMINI_ENABLED
}

$exitCode = 0

Push-Location $PSScriptRoot

try {
    Write-Host "`n===== CONFIGURING TEST ENVIRONMENT =====" -ForegroundColor Cyan

    $testDatabase = "ci_test_runner_$(Get-Date -Format 'yyyyMMdd_HHmmss_fff').db"
    $env:DATABASE_URL = "sqlite:///./$testDatabase"
    Write-Host "Test database: $testDatabase" -ForegroundColor DarkGray
    $env:POSTGRES_PASSWORD = "ci-test-only"
    $env:PYTHONPATH = "."
    $env:GEMINI_ENABLED = "false"

    Write-Host "`n===== APPLYING DATABASE MIGRATIONS =====" -ForegroundColor Cyan
    python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migrations failed."
    }

    Write-Host "`n===== PREPARING TEST DATABASE =====" -ForegroundColor Cyan
    python tests/ci_setup.py
    if ($LASTEXITCODE -ne 0) {
        throw "Database preparation failed."
    }

    Write-Host "`n===== CHECKING PYTHON COMPILATION =====" -ForegroundColor Cyan
    python -m compileall -q app
    if ($LASTEXITCODE -ne 0) {
        throw "Python compilation failed."
    }

    Write-Host "`n===== RUNNING REGRESSION TESTS =====" -ForegroundColor Cyan
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Regression tests failed."
    }

    Write-Host "`n===== ALL CHECKS PASSED =====" -ForegroundColor Green
}
catch {
    Write-Host "`n===== CHECK FAILED =====" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    $exitCode = 1
}
finally {
    foreach ($name in $previousEnvironment.Keys) {
        if ($null -eq $previousEnvironment[$name]) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item "Env:$name" $previousEnvironment[$name]
        }
    }

    Pop-Location
}

exit $exitCode
