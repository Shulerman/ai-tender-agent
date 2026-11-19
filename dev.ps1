param(
    [Parameter(Position = 0)]
    [ValidateSet("help", "check", "test", "full", "status", "diff", "commit")]
    [string]$Command = "help",

    [Parameter(Position = 1)]
    [string[]]$Paths = @(),

    [string]$Message
)

$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot

try {
    switch ($Command) {
        "help" {
            Write-Host "AI Tender Agent - Development Helper" -ForegroundColor Cyan
            Write-Host ""
            Write-Host ".\dev.ps1 check"
            Write-Host ".\dev.ps1 test tests/test_example.py"
            Write-Host ".\dev.ps1 full"
            Write-Host ".\dev.ps1 status"
            Write-Host ".\dev.ps1 diff"
            Write-Host '.\dev.ps1 commit -Message "Description" -Paths "file1.py","file2.py"'
        }

        "check" {
            Write-Host "`n===== PYTHON COMPILATION =====" -ForegroundColor Cyan
            python -m compileall -q app
            if ($LASTEXITCODE -ne 0) {
                throw "Python compilation failed."
            }

            Write-Host "`n===== POWERSHELL SYNTAX =====" -ForegroundColor Cyan

            $scripts = Get-ChildItem -Path $PSScriptRoot -Filter "*.ps1" -File

            foreach ($script in $scripts) {
                $tokens = $null
                $errors = $null

                [System.Management.Automation.Language.Parser]::ParseFile(
                    $script.FullName,
                    [ref]$tokens,
                    [ref]$errors
                ) | Out-Null

                if ($errors.Count -gt 0) {
                    $errors | Format-List
                    throw "PowerShell syntax error in $($script.Name)"
                }

                Write-Host "OK: $($script.Name)" -ForegroundColor Green
            }

            Write-Host "`n===== CHECK PASSED =====" -ForegroundColor Green
        }

        "test" {
            if ($Paths.Count -eq 0) {
                throw "Specify at least one test path. Example: .\dev.ps1 test tests/test_commercial_import_api.py"
            }

            foreach ($path in $Paths) {
                if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                    throw "Test file not found: $path"
                }
            }

            $previousEnvironment = @{
                DATABASE_URL = $env:DATABASE_URL
                POSTGRES_PASSWORD = $env:POSTGRES_PASSWORD
                PYTHONPATH = $env:PYTHONPATH
            }

            try {
                $env:DATABASE_URL = "sqlite:///./ci_test.db"
                $env:POSTGRES_PASSWORD = "ci-test-only"
                $env:PYTHONPATH = "."

                python -m pytest -q @Paths
                $testExitCode = $LASTEXITCODE
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
            }

            if ($testExitCode -ne 0) {
                throw "Selected tests failed."
            }
        }

        "full" {
            $powerShellExe = Join-Path $PSHOME "pwsh.exe"
            & $powerShellExe -NoProfile -File (Join-Path $PSScriptRoot "run_tests.ps1")
            $fullExitCode = $LASTEXITCODE

            if ($fullExitCode -ne 0) {
                throw "Full test suite failed with exit code $fullExitCode."
            }

            Write-Host "`n===== FULL TEST SUITE PASSED =====" -ForegroundColor Green
        }

        "status" {
            & git.exe status --short
            if ($LASTEXITCODE -ne 0) {
                throw "Git status failed."
            }
        }

        "diff" {
            & git.exe diff
            if ($LASTEXITCODE -ne 0) {
                throw "Git diff failed."
            }
        }

        "commit" {
            if ([string]::IsNullOrWhiteSpace($Message)) {
                throw "Commit message is required. Use -Message."
            }

            if ($Paths.Count -eq 0) {
                throw "Explicit file paths are required. Use -Paths."
            }

            $powerShellExe = Join-Path $PSHOME "pwsh.exe"
            & $powerShellExe -NoProfile -File (Join-Path $PSScriptRoot "checkpoint.ps1") -Message $Message -Paths $Paths
            $commitExitCode = $LASTEXITCODE

            if ($commitExitCode -ne 0) {
                throw "Checkpoint failed with exit code $commitExitCode."
            }
        }
    }
}
catch {
    Write-Host "`n===== COMMAND FAILED =====" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
