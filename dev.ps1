param(
    [Parameter(Position = 0)]
    [ValidateSet("help", "context", "inspect", "check", "test", "smart", "smart-preview", "full", "status", "diff", "commit")]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Paths = @(),

    [string]$Message
)

$ErrorActionPreference = "Stop"
$previewOnly = ($Command -eq "smart-preview")
if ($previewOnly) { $Command = "smart" }

function Invoke-PreparedTargetedTests {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$TestPaths
    )

    $previousEnvironment = @{
        DATABASE_URL = $env:DATABASE_URL
        POSTGRES_PASSWORD = $env:POSTGRES_PASSWORD
        PYTHONPATH = $env:PYTHONPATH
        GEMINI_ENABLED = $env:GEMINI_ENABLED
    }

    $testDatabase = "ci_targeted_$(Get-Date -Format 'yyyyMMdd_HHmmss_fff')_$PID.db"
    $testExitCode = 0

    try {
        $env:DATABASE_URL = "sqlite:///./$testDatabase"
        $env:POSTGRES_PASSWORD = "ci-test-only"
        $env:PYTHONPATH = "."
        $env:GEMINI_ENABLED = "false"

        Write-Host "`nTest database: $testDatabase" -ForegroundColor DarkGray

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

        Write-Host "`n===== RUNNING SELECTED TESTS =====" -ForegroundColor Cyan
        python -m pytest -q @TestPaths
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
        throw "Selected tests failed with exit code $testExitCode."
    }
}
Push-Location $PSScriptRoot

try {
    switch ($Command) {
        "help" {
            Write-Host "AI Tender Agent - Development Helper" -ForegroundColor Cyan
            Write-Host ""
            Write-Host ".\dev.ps1 context"
            Write-Host ".\dev.ps1 inspect app/ai/technical_analyst.py tests/test_technical_analyst.py"
            Write-Host ".\dev.ps1 check"
            Write-Host ".\dev.ps1 test tests/test_example.py"
            Write-Host ".\dev.ps1 full"
            Write-Host ".\dev.ps1 status"
            Write-Host ".\dev.ps1 diff"
            Write-Host '.\dev.ps1 commit -Message "Description" -Paths "file1.py","file2.py"'
        }

        "context" {
            Write-Host "`n===== PROJECT CONTEXT =====" -ForegroundColor Cyan
            Write-Host "`nPROJECT ROOT: $PSScriptRoot"
            Write-Host "`n===== GIT BRANCH =====" -ForegroundColor Cyan
            git.exe branch --show-current
            if ($LASTEXITCODE -ne 0) { throw "Could not read Git branch." }

            Write-Host "`n===== TRACKED CHANGES =====" -ForegroundColor Cyan
            git.exe status --short --untracked-files=no
            if ($LASTEXITCODE -ne 0) { throw "Could not read Git status." }

            Write-Host "`n===== TRACKED APPLICATION FILES =====" -ForegroundColor Cyan
            $trackedFiles = @(git.exe ls-files app tests)
            if ($LASTEXITCODE -ne 0) { throw "Could not list tracked project files." }
            $trackedApp = @($trackedFiles | Where-Object { $_ -like "app/*" })
            $trackedTests = @($trackedFiles | Where-Object { $_ -like "tests/test_*.py" })
            Write-Host "Application files: $($trackedApp.Count)"
            $trackedApp | ForEach-Object { Write-Host "  $_" }
            Write-Host "`nTest files: $($trackedTests.Count)"
            $trackedTests | ForEach-Object { Write-Host "  $_" }

            Write-Host "`n===== RECENT COMMITS =====" -ForegroundColor Cyan
            git.exe log -5 --oneline
            if ($LASTEXITCODE -ne 0) { throw "Could not read recent commits." }
            Write-Host "`n===== CONTEXT COLLECTION COMPLETE =====" -ForegroundColor Green
        }
        "inspect" {
            if ($Paths.Count -eq 0) {
                throw "Specify Python files under app or tests. Example: .\dev.ps1 inspect app/ai/technical_analyst.py tests/test_technical_analyst.py"
            }
            if ($Paths.Count -gt 8) {
                throw "Inspect accepts at most 8 files per call."
            }

            $root = [System.IO.Path]::GetFullPath($PSScriptRoot)
            foreach ($requestedPath in $Paths) {
                $normalizedPath = $requestedPath.Replace('\', '/')
                if ($normalizedPath -notmatch '^(app|tests)/.+\.py$') {
                    throw "Only Python files under app/ or tests/ are allowed: $requestedPath"
                }

                $resolvedPath = (Resolve-Path -LiteralPath $requestedPath -ErrorAction Stop).Path
                if (-not $resolvedPath.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Path is outside the project directory: $requestedPath"
                }

                Write-Host "`n===== FILE: $normalizedPath =====" -ForegroundColor Cyan
                $lines = @(Get-Content -LiteralPath $resolvedPath)
                $displayCount = [Math]::Min($lines.Count, 500)
                for ($i = 0; $i -lt $displayCount; $i++) {
                    Write-Host ("{0,4}: {1}" -f ($i + 1), $lines[$i])
                }
                if ($lines.Count -gt 500) {
                    Write-Host "... truncated: showing 500 of $($lines.Count) lines ..." -ForegroundColor Yellow
                }
            }
            Write-Host "`n===== INSPECTION COMPLETE =====" -ForegroundColor Green
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

            Write-Host "`n===== GIT DIFF CHECK =====" -ForegroundColor Cyan
            & git.exe diff --check
            if ($LASTEXITCODE -ne 0) {
                throw "Git diff check failed."
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

            Invoke-PreparedTargetedTests -TestPaths $Paths
        }
        "smart" {
            $trackedChanged = @(& git.exe diff --name-only HEAD)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not detect tracked changes."
            }

            $untrackedCandidates = @(& git.exe ls-files --others --exclude-standard -- app tests)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not detect untracked application and test files."
            }

            $untrackedCode = @(
                $untrackedCandidates | Where-Object {
                    ($_ -match '^app/.+\.py$') -or ($_ -match '^tests/test_[^/]+\.py$')
                }
            )

            $allChangedFiles = @()
            $allChangedFiles += $trackedChanged
            $allChangedFiles += $untrackedCode
            $changedFiles = @($allChangedFiles | Sort-Object -Unique)

            $selectedTests = @()
            $fullRequired = ($changedFiles.Count -eq 0)

            foreach ($file in $changedFiles) {
                $path = $file.Replace('\', '/')

                if ($path -match '^tests/test_[^/]+\.py$') {
                    if (Test-Path -LiteralPath $path -PathType Leaf) {
                        $selectedTests += $path
                    }
                    else {
                        $fullRequired = $true
                    }
                    continue
                }

                switch -Exact ($path) {
                    "app/commercial/calculator.py" {
                        $selectedTests += "tests/test_commercial_calculator.py"
                    }
                    "app/commercial/matcher.py" {
                        $selectedTests += "tests/test_commercial_matcher.py"
                        $selectedTests += "tests/test_commercial_matcher_api.py"
                    }
                    "app/commercial/import_service.py" {
                        $selectedTests += "tests/test_commercial_import_service.py"
                        $selectedTests += "tests/test_commercial_import_api.py"
                    }
                    "app/commercial/excel_importer.py" {
                        $selectedTests += "tests/test_excel_importer.py"
                        $selectedTests += "tests/test_commercial_import_service.py"
                        $selectedTests += "tests/test_commercial_import_api.py"
                    }
                    "app/commercial/quantity_parser.py" {
                        $selectedTests += "tests/test_commercial_quantity_parser.py"
                    }
                    "app/commercial/unit_normalizer.py" {
                        $selectedTests += "tests/test_commercial_service.py"
                        $selectedTests += "tests/test_commercial_import_service.py"
                    }
                    "app/commercial/service.py" {
                        $selectedTests += "tests/test_commercial_service.py"
                        $selectedTests += "tests/test_commercial_matcher_api.py"
                        $selectedTests += "tests/test_commercial_import_service.py"
                        $selectedTests += "tests/test_commercial_import_api.py"
                    }
                    "app/ai/technical_analyst.py" {
                        $selectedTests += "tests/test_technical_analyst.py"
                    }
                    "app/ai/technical_models.py" {
                        $selectedTests += "tests/test_technical_models.py"
                        $selectedTests += "tests/test_technical_analyst.py"
                        $selectedTests += "tests/test_commercial_quantity_parser.py"
                    }
                    "app/documents/analysis_service.py" {
                        $selectedTests += "tests/test_document_analysis_service.py"
                        $selectedTests += "tests/test_document_analysis_api.py"
                        $selectedTests += "tests/test_document_analysis_persistence.py"
                    }
                    "app/documents/persistence_service.py" {
                        $selectedTests += "tests/test_document_analysis_persistence.py"
                        $selectedTests += "tests/test_document_analysis_api.py"
                    }
                    "app/documents/storage.py" {
                        $selectedTests += "tests/test_document_upload_api.py"
                    }
                    default {
                        $fullRequired = $true
                    }
                }
            }

            if ($previewOnly) {
                Write-Host "`n===== SMART PREVIEW =====" -ForegroundColor Cyan
                Write-Host "Changed tracked files and new source/test files:"
                if ($changedFiles.Count -eq 0) {
                    Write-Host "  No relevant changes detected."
                }
                else {
                    $changedFiles | ForEach-Object { Write-Host "  $_" }
                }

                if ($fullRequired -or $selectedTests.Count -eq 0) {
                    Write-Host "`nPlanned action: FULL REGRESSION" -ForegroundColor Yellow
                    Write-Host "Reason: no safe targeted mapping exists, a selected test was deleted, or no relevant changes were detected."
                }
                else {
                    $selectedTests = @($selectedTests | Sort-Object -Unique)
                    Write-Host "`nPlanned action: SELECTED TESTS" -ForegroundColor Green
                    $selectedTests | ForEach-Object { Write-Host "  $_" }
                    Write-Host "Database: new isolated SQLite database; migrations and ci_setup will run first."
                }
                break
            }

            if ($fullRequired -or $selectedTests.Count -eq 0) {
                Write-Host "`n===== SMART: FULL REGRESSION REQUIRED =====" -ForegroundColor Yellow
                $powerShellExe = Join-Path $PSHOME "pwsh.exe"
                & $powerShellExe -NoProfile -File (Join-Path $PSScriptRoot "run_tests.ps1")
                if ($LASTEXITCODE -ne 0) {
                    throw "Full regression failed."
                }
            }
            else {
                $selectedTests = @($selectedTests | Sort-Object -Unique)
                Write-Host "`n===== SMART: SELECTED TESTS =====" -ForegroundColor Cyan
                $selectedTests | ForEach-Object { Write-Host "  $_" }

                Invoke-PreparedTargetedTests -TestPaths $selectedTests
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
