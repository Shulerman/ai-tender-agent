[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Message,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string[]]$Paths
)

$ErrorActionPreference = "Stop"

try {
    $repoRoot = (& git rev-parse --show-toplevel 2>&1).ToString().Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
        throw "Текущая папка не является Git-репозиторием."
    }

    Set-Location $repoRoot

    $stagedBefore = @(& git diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось проверить индекс Git."
    }
    if ($stagedBefore.Count -gt 0) {
        throw "В Git уже есть подготовленные изменения. Сначала разберитесь с ними отдельно."
    }

    $requested = @(
        $Paths |
        ForEach-Object { $_.Replace("\", "/") } |
        Sort-Object -Unique
    )

    if ($requested.Count -eq 0) {
        throw "Не указаны файлы для коммита."
    }
    $literalPathspecs = @(
        $requested | ForEach-Object { ":(literal)$_" }
    )

    foreach ($path in $requested) {
        if (
            [System.IO.Path]::IsPathRooted($path) -or
            $path -match '(^|/)\.\.(/|$)' -or
            $path -match '(^|/)\.env($|\.)' -or
            $path -match '(^|/)(ci_test\.db|[^/]*\.bak|[^/]*\.backup|[^/]*\.before[^/]*|[^/]*\.recovered)$' -or
            $path -match '[:*?\[\]]'
        ) {
            throw "Запрещённый или небезопасный путь: $path"
        }

        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Файл не найден или не является обычным файлом: $path"
        }

        & git check-ignore -q -- ":(literal)$path"
        if ($LASTEXITCODE -eq 0) {
            throw "Файл исключён правилами Git: $path"
        }
        if ($LASTEXITCODE -gt 1) {
            throw "Не удалось проверить правила исключения Git: $path"
        }
    }

    if (-not (Test-Path ".\tools\run_tests.ps1" -PathType Leaf)) {
        throw "Не найден run_tests.ps1."
    }

    Write-Host "`nЗапускаю полный набор проверок..." -ForegroundColor Cyan
    $powerShellExe = Join-Path $PSHOME "pwsh.exe"
    & $powerShellExe -NoProfile -File (Join-Path $repoRoot "tools\run_tests.ps1")
    $testExitCode = $LASTEXITCODE

    if ($testExitCode -ne 0) {
        throw "Проверки завершились с ошибкой (код $testExitCode). Коммит не создан."
    }

    Write-Host "`nДобавляю только выбранные файлы..." -ForegroundColor Cyan
    & git add -- $literalPathspecs
    $addExitCode = $LASTEXITCODE

    if ($addExitCode -ne 0) {
        & git reset -- $literalPathspecs
        throw "Не удалось добавить выбранные файлы. Индекс очищен от выбранных файлов."
    }

    $actual = @(& git diff --cached --name-only)
    if ($LASTEXITCODE -ne 0) {
        & git reset -- $literalPathspecs
        throw "Не удалось проверить подготовленные изменения."
    }

    $expectedSorted = @($requested | Sort-Object)
    $actualSorted = @($actual | Sort-Object)

    $difference = Compare-Object -ReferenceObject $expectedSorted -DifferenceObject $actualSorted
    if ($difference) {
        & git reset -- $literalPathspecs
        throw "Список подготовленных файлов отличается от запрошенного. Коммит отменён."
    }

    Write-Host "`nФайлы, которые войдут в коммит:" -ForegroundColor Cyan
    $actualSorted | ForEach-Object { Write-Host "  $_" }

    Write-Host "`nСводка изменений:" -ForegroundColor Cyan
    & git diff --cached --stat
    if ($LASTEXITCODE -ne 0) {
        & git reset -- $literalPathspecs
        throw "Не удалось показать сводку изменений."
    }

    & git diff --cached --check
    if ($LASTEXITCODE -ne 0) {
        & git reset -- $literalPathspecs
        throw "Обнаружены проблемы с пробелами или форматированием. Коммит отменён."
    }

    $answer = Read-Host "`nСоздать локальный коммит '$Message'? (y/N)"

    if ($answer -notin @("y", "Y", "yes", "YES")) {
        & git reset -- $literalPathspecs
        Write-Host "Коммит отменён. Изменения в рабочих файлах сохранены." -ForegroundColor Yellow
        return
    }

    & git commit -m $Message
    $commitExitCode = $LASTEXITCODE

    if ($commitExitCode -ne 0) {
        $remainingStaged = @(& git diff --cached --name-only)
        $stagedQueryExitCode = $LASTEXITCODE

        if ($stagedQueryExitCode -ne 0) {
            throw "Git commit failed with exit code $commitExitCode. Could not inspect remaining index."
        }

        $stagedDescription = if ($remainingStaged.Count -gt 0) {
            $remainingStaged -join ", "
        }
        else {
            "(no staged files)"
        }

        throw "Git commit failed with exit code $commitExitCode. Working files are preserved. Remaining staged files: $stagedDescription"
    }

    Write-Host "`nКоммит создан. Отправка на GitHub не выполнялась." -ForegroundColor Green
}
catch {
    Write-Host "`nОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
