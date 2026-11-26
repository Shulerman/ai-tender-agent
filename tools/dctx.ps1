$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $report = [System.Collections.Generic.List[string]]::new()
    $report.Add("===== AI TENDER AGENT: QUICK CONTEXT =====")
    $report.Add("Project: $ProjectRoot")
    $report.Add("Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $report.Add("PowerShell: $($PSVersionTable.PSVersion)")

    $branch = & git.exe branch --show-current
    if ($LASTEXITCODE -ne 0) { throw "Git branch failed." }
    $report.Add("Branch: $branch")

    $report.Add("")
    $report.Add("===== GIT STATUS =====")
    $status = @(& git.exe status --short 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Git status failed." }
    if ($status.Count) { foreach ($line in $status) { $report.Add([string]$line) } }
    else { $report.Add("Working tree clean.") }

    $report.Add("")
    $report.Add("===== DIFF SUMMARY =====")
    $diff = @(& git.exe diff HEAD --stat 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Git diff failed." }
    if ($diff.Count) { foreach ($line in $diff) { $report.Add([string]$line) } }
    else { $report.Add("No tracked diff.") }

    $report.Add("")
    $report.Add("===== RECENT COMMITS =====")
    $commits = @(& git.exe log -5 --oneline 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Git log failed." }
    foreach ($line in $commits) { $report.Add([string]$line) }

    $report.Add("")
    $report.Add("===== PYTHON =====")
    $version = & python --version 2>&1
    if ($LASTEXITCODE -eq 0) { $report.Add([string]$version) }
    else { $report.Add("Python version unavailable.") }

    $text = $report -join [Environment]::NewLine
    Set-Clipboard -Value $text
    Write-Output $text
    Write-Host "`n[Контекст скопирован в буфер обмена]" -ForegroundColor Green
}
finally {
    Pop-Location
}