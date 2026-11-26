param(
    [Parameter(Position = 0)]
    [ValidateSet("help", "context", "inspect", "check", "test", "smart", "smart-preview", "apply", "full", "status", "diff", "commit")]
    [string]$Command = "help",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Paths = @(),

    [string]$Message,

    [string]$Symbol
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
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

    $testDatabase = "ci_targeted_$([guid]::NewGuid().ToString('N')).db"
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
Push-Location $ProjectRoot

try {
    switch ($Command) {
        "help" {
            Write-Host "AI Tender Agent - Development Helper" -ForegroundColor Cyan
            Write-Host ""
            Write-Host ".\tools\dev.ps1 context"
            Write-Host ".\tools\dev.ps1 inspect app/ai/technical_analyst.py tests/test_technical_analyst.py"
            Write-Host ".\tools\dev.ps1 check"
            Write-Host ".\tools\dev.ps1 test tests/test_example.py"
            Write-Host ".\tools\dev.ps1 smart-preview"
            Write-Host ".\tools\dev.ps1 smart"
            Write-Host ".\tools\dev.ps1 apply tools/plans/change-plan.json"
            Write-Host ".\tools\dev.ps1 full"
            Write-Host ".\tools\dev.ps1 status"
            Write-Host ".\tools\dev.ps1 diff"
            Write-Host '.\tools\dev.ps1 commit -Message "Description" -Paths "file1.py","file2.py"'
        }

        "context" {
            Write-Host "`n===== PROJECT CONTEXT =====" -ForegroundColor Cyan
            Write-Host "`nPROJECT ROOT: $ProjectRoot"
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
                throw "Specify Python files under app or tests."
            }
            if ($Paths.Count -gt 8) {
                throw "Inspect accepts at most 8 files per call."
            }

            $root = [System.IO.Path]::GetFullPath($ProjectRoot)
            $report = [System.Collections.Generic.List[string]]::new()

            $astCode = @"
import ast, json, sys
from pathlib import Path

path = Path(sys.argv[1])
requested = sys.argv[2]
source = path.read_text(encoding="utf-8-sig")
tree = ast.parse(source, filename=str(path))
lines = source.splitlines()
matches = []

for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == requested:
        decorators = getattr(node, "decorator_list", [])
        start = min([node.lineno] + [d.lineno for d in decorators])
        end = node.end_lineno
        matches.append({
            "name": node.name,
            "kind": type(node).__name__,
            "start": start,
            "end": end,
            "source": "\n".join(lines[start - 1:end])
        })

print(json.dumps({"matches": matches}, ensure_ascii=False))
"@

            foreach ($requestedPath in $Paths) {
                $normalizedPath = $requestedPath.Replace('\', '/')
                if ($normalizedPath -notmatch '^(app|tests)/.+\.py$') {
                    throw "Only Python files under app/ or tests/ are allowed: $requestedPath"
                }

                $resolvedPath = (Resolve-Path -LiteralPath $requestedPath -ErrorAction Stop).Path
                if (-not $resolvedPath.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Path is outside the project directory: $requestedPath"
                }

                $report.Add("")
                $report.Add("===== FILE: $normalizedPath =====")

                if ($Symbol) {
                    $pythonOutput = & python -c $astCode $resolvedPath $Symbol 2>&1
                    if ($LASTEXITCODE -ne 0) {
                        throw "AST extraction failed for ${normalizedPath}: $($pythonOutput -join ' ')"
                    }

                    try {
                        $payload = ($pythonOutput -join "`n") | ConvertFrom-Json -ErrorAction Stop
                    }
                    catch {
                        throw "Could not parse AST extraction result for ${normalizedPath}: $($_.Exception.Message)"
                    }

                    if (@($payload.matches).Count -eq 0) {
                        throw "Symbol '$Symbol' was not found in $normalizedPath."
                    }

                    foreach ($match in $payload.matches) {
                        $report.Add("--- $($match.kind): $($match.name), lines $($match.start)-$($match.end) ---")
                        $sourceLines = @($match.source -split "`n")
                        for ($i = 0; $i -lt $sourceLines.Count; $i++) {
                            $report.Add(("{0,4}: {1}" -f ($match.start + $i), $sourceLines[$i]))
                        }
                    }
                }
                else {
                    $fileLines = [System.IO.File]::ReadAllLines($resolvedPath)
                    $displayCount = [Math]::Min($fileLines.Count, 500)
                    for ($i = 0; $i -lt $displayCount; $i++) {
                        $report.Add(("{0,4}: {1}" -f ($i + 1), $fileLines[$i]))
                    }
                    if ($fileLines.Count -gt 500) {
                        $report.Add("... truncated: showing 500 of $($fileLines.Count) lines ...")
                    }
                }
            }

            $report.Add("")
            $report.Add("===== INSPECTION COMPLETE =====")
            $reportText = $report -join [Environment]::NewLine

            Set-Clipboard -Value $reportText -ErrorAction Stop
            Write-Output $reportText
            Write-Host "`n[inspect] Result copied to clipboard." -ForegroundColor Green
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
            Write-Host "`n===== GIT STAGED DIFF CHECK =====" -ForegroundColor Cyan
            & git.exe diff --cached --check
            if ($LASTEXITCODE -ne 0) {
                throw "Git staged diff check failed."
            }

            Write-Host "`n===== CHECK PASSED =====" -ForegroundColor Green
        }

        "test" {
            if ($Paths.Count -eq 0) {
                throw "Specify at least one test path. Example: .\dev.ps1 test tests/test_commercial_import_api.py"
            }

            $testsRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "tests")).TrimEnd('\', '/') +
                [System.IO.Path]::DirectorySeparatorChar

            foreach ($path in $Paths) {
                $resolvedTest = (Resolve-Path -LiteralPath $path -ErrorAction Stop).Path
                if (-not (Test-Path -LiteralPath $resolvedTest -PathType Leaf)) {
                    throw "Test path is not a file: $path"
                }
                if ([System.IO.Path]::GetExtension($resolvedTest) -ne ".py" -or
                    -not $resolvedTest.StartsWith($testsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "Only Python test files inside tests/ are allowed: $path"
                }
            }

            Invoke-PreparedTargetedTests -TestPaths $Paths
        }
        "smart" {
                        $trackedChanged = @(
                & git.exe diff --name-only HEAD -- app tests
            )
            if ($LASTEXITCODE -ne 0) {
                throw "Could not detect tracked changes."
            }

            $untrackedCandidates = @(& git.exe ls-files --others --exclude-standard -- app tests)
            if ($LASTEXITCODE -ne 0) {
                throw "Could not detect untracked application and test files."
            }

            $untrackedCode = @(
                $untrackedCandidates | Where-Object {
                    $isSourceOrTest = (
                        ($_ -match '^app/.+\.py$') -or
                        ($_ -match '^tests/.+\.py$')
                    )
                    $isBackup = $_ -match '(?i)(\.bak|\.backup|\.before|\.recovered|\.old|backup_)'
                    $isSourceOrTest -and -not $isBackup
                }
            )

            $allChangedFiles = @()
            $allChangedFiles += $trackedChanged
            $allChangedFiles += $untrackedCode
            $changedFiles = @($allChangedFiles | Sort-Object -Unique)

            $selectedTests = @()
            $fullRequired = $false

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

                if ($changedFiles.Count -eq 0) {
                    Write-Host "`nPlanned action: NO TESTS REQUIRED" -ForegroundColor DarkGray
                }
                elseif ($fullRequired -or $selectedTests.Count -eq 0) {
                    Write-Host "`nPlanned action: FULL REGRESSION" -ForegroundColor Yellow
                    Write-Host "Reason: no safe targeted mapping exists or a selected test was deleted."
                }
                else {
                    $selectedTests = @($selectedTests | Sort-Object -Unique)
                    Write-Host "`nPlanned action: SELECTED TESTS" -ForegroundColor Green
                    $selectedTests | ForEach-Object { Write-Host "  $_" }
                    Write-Host "Database: new isolated SQLite database; migrations and ci_setup will run first."
                }
                break
            }

            if ($changedFiles.Count -eq 0) {
                Write-Host "`n===== SMART: NO RELEVANT CHANGES =====" -ForegroundColor DarkGray
                Write-Host "Tests were not started."
            }
            elseif ($fullRequired -or $selectedTests.Count -eq 0) {
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
        "apply" {
            if ($Paths.Count -ne 1) {
                throw "Specify exactly one JSON plan path. Example: .\tools\dev.ps1 apply tools/plans/change-plan.json"
            }

            $planPath = $Paths[0]
            $powerShellExe = Join-Path $PSHOME "pwsh.exe"
            & $powerShellExe -NoProfile -File (Join-Path $PSScriptRoot "Invoke-SafeChange.ps1") -PlanPath $planPath
            $applyExitCode = $LASTEXITCODE

            if ($applyExitCode -ne 0) {
                throw "Safe apply failed with exit code $applyExitCode."
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
