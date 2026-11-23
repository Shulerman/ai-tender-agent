$ErrorActionPreference = "Stop"

$previousEnvironment = @{
    DATABASE_URL = $env:DATABASE_URL
    POSTGRES_PASSWORD = $env:POSTGRES_PASSWORD
    PYTHONPATH = $env:PYTHONPATH
}

$exitCode = 0

Push-Location $PSScriptRoot

try {
    Write-Host "`n===== CONFIGURING TEST ENVIRONMENT =====" -ForegroundColor Cyan

    $env:DATABASE_URL = "sqlite:///./ci_test.db"
    $env:POSTGRES_PASSWORD = "ci-test-only"
    $env:PYTHONPATH = "."

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
