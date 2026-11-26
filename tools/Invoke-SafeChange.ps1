[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$RootPrefix = $ProjectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$PowerShellExe = Join-Path $PSHOME 'pwsh.exe'
$Backups = [System.Collections.Generic.List[object]]::new()
$StagedFiles = [System.Collections.Generic.List[string]]::new()
$AppliedTargets = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$MapPath = $null

function Resolve-ProjectFile {
    param(
        [string]$RelativePath,
        [string]$Description,
        [switch]$AllowMissing
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Unsafe $Description path: $RelativePath"
    }

    $full = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RelativePath))
    if (-not $full.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description path escapes project root."
    }

    if (Test-Path -LiteralPath $full) {
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
            throw "$Description is not a file: $RelativePath"
        }
        $resolved = (Resolve-Path -LiteralPath $full).Path
    }
    else {
        if (-not $AllowMissing) {
            throw "$Description file does not exist: $RelativePath"
        }

        $parent = [System.IO.Path]::GetDirectoryName($full)
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "$Description parent directory does not exist: $RelativePath"
        }

        $resolvedParent = (Resolve-Path -LiteralPath $parent).Path
        if (-not (
            $resolvedParent.Equals($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
            $resolvedParent.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        )) {
            throw "$Description parent resolves outside project root."
        }

        $resolved = Join-Path $resolvedParent ([System.IO.Path]::GetFileName($full))
    }

    if (-not $resolved.StartsWith($RootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description resolves outside project root."
    }
    return $resolved
}

function Assert-SafeTarget {
    param([string]$Path)

    $relative = [System.IO.Path]::GetRelativePath($ProjectRoot, $Path).Replace('\','/')
    $segments = $relative -split '/'
    if ($segments -contains '.git' -or
        $relative -match '(^|/)\.env($|\.)' -or
        $relative -match '(?i)(^|/)(secrets?|credentials?)(/|$)' -or
        $relative -match '(?i)\.(db|sqlite|sqlite3|bak|backup)$' -or
        $relative -match '(?i)\.safebackup_' -or
        $relative -match '(?i)(^|/)(backups?|database|databases)(/|$)') {
        throw "Protected target path is not allowed: $relative"
    }
}

function Get-FormatSignature {
    param([string]$Path)

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $bom = $bytes.Length -ge 3 -and
        $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    $offset = if ($bom) { 3 } else { 0 }
    $encoding = [System.Text.UTF8Encoding]::new($false, $true)
    $content = $encoding.GetString($bytes, $offset, $bytes.Length - $offset)

    $crlf = ([regex]::Matches($content, "`r`n")).Count
    $lf = ([regex]::Matches($content, "(?<!`r)`n")).Count
    $cr = ([regex]::Matches($content, "`r(?!`n)")).Count
    $kinds = [System.Collections.Generic.List[string]]::new()
    if ($crlf -gt 0) { $kinds.Add("CRLF") }
    if ($lf -gt 0) { $kinds.Add("LF") }
    if ($cr -gt 0) { $kinds.Add("CR") }
    return "$bom|$([string]::Join(',', $kinds))"
}

function Invoke-Validation {
    param([string]$ScriptPath, [string]$Phase)

    Write-Host "`n===== $Phase VALIDATION =====" -ForegroundColor Cyan
    & $PowerShellExe -NoProfile -File $ScriptPath -Phase $Phase -ChangesJson $MapPath
    if ($LASTEXITCODE -ne 0) {
        throw "$Phase validation failed with exit code $LASTEXITCODE."
    }
}

try {
    if (-not (Test-Path -LiteralPath $PowerShellExe -PathType Leaf)) {
        throw "PowerShell executable not found: $PowerShellExe"
    }

    $resolvedPlan = if ([System.IO.Path]::IsPathRooted($PlanPath)) {
        [System.IO.Path]::GetFullPath($PlanPath)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $PlanPath))
    }

    if (-not (Test-Path -LiteralPath $resolvedPlan -PathType Leaf)) {
        throw "Plan not found: $PlanPath"
    }

    $plan = Get-Content -LiteralPath $resolvedPlan -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($plan.version -ne 1) { throw 'Unsupported plan version. Expected 1.' }
    if (@($plan.changes).Count -eq 0) { throw 'Plan contains no changes.' }

    $preCheck = Resolve-ProjectFile ([string]$plan.preCheck) 'Pre-check'
    $postCheck = Resolve-ProjectFile ([string]$plan.postCheck) 'Post-check'

    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $changes = [System.Collections.Generic.List[object]]::new()

    foreach ($change in $plan.changes) {
        $create = $false
        if ($null -ne $change.PSObject.Properties['create']) {
            if ($change.create -isnot [bool]) {
                throw "The create property must be a Boolean."
            }
            $create = $change.create
        }

        $destination = Resolve-ProjectFile ([string]$change.target) 'Target' -AllowMissing:$create
        $candidate = Resolve-ProjectFile ([string]$change.candidate) 'Candidate'
        Assert-SafeTarget $destination

        if ($destination -eq $candidate) { throw 'Candidate cannot be the target file.' }
        if ($seen.Contains($candidate)) { throw 'A candidate cannot also be a target.' }
        if (-not $seen.Add($destination)) { throw "Duplicate target: $destination" }

        if ($create) {
            if (Test-Path -LiteralPath $destination) {
                throw "Create target already exists: $destination"
            }
        }
        elseif ((Get-FormatSignature $destination) -ne (Get-FormatSignature $candidate)) {
            throw "Candidate encoding or line endings differ from target: $destination"
        }

        $changes.Add([pscustomobject]@{
            Target = $destination
            Candidate = $candidate
            Create = $create
        })
    }

    $MapPath = Join-Path $env:TEMP ("safechange_map_" + [guid]::NewGuid().ToString('N') + '.json')
    [System.IO.File]::WriteAllText(
        $MapPath,
        (ConvertTo-Json -InputObject @($changes) -Depth 5),
        [System.Text.UTF8Encoding]::new($false)
    )

    Write-Host '===== PLAN VALIDATED =====' -ForegroundColor Cyan
    Write-Host "Target files: $($changes.Count)"

    $preApplySnapshots = @{}
    foreach ($change in $changes) {
        if ($change.Create) {
            if (Test-Path -LiteralPath $change.Target) {
                throw "Create target appeared before PreApply: $($change.Target)"
            }
        }
        else {
            $preApplySnapshots[$change.Target] = [System.IO.File]::ReadAllBytes($change.Target)
        }
    }

    try {
        Invoke-Validation $preCheck 'PreApply'

        foreach ($change in $changes) {
            if ($change.Create) {
                if (Test-Path -LiteralPath $change.Target) {
                    throw "PreApply validator created target; file preserved: $($change.Target)"
                }
                continue
            }

            if (-not (Test-Path -LiteralPath $change.Target -PathType Leaf)) {
                throw "PreApply validator deleted target: $($change.Target)"
            }

            $before = [Convert]::ToBase64String($preApplySnapshots[$change.Target])
            $after = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($change.Target))
            if ($before -ne $after) {
                throw "PreApply validator modified target: $($change.Target)"
            }
        }
    }
    catch {
        $preApplyFailure = $_.Exception.Message
        $restoreErrors = [System.Collections.Generic.List[string]]::new()

        foreach ($change in $changes) {
            if ($change.Create) {
                if (Test-Path -LiteralPath $change.Target) {
                    Write-Warning "Unexpected create target preserved: $($change.Target)"
                }
                continue
            }

            try {
                $snapshot = $preApplySnapshots[$change.Target]
                $mustRestore = -not (Test-Path -LiteralPath $change.Target -PathType Leaf)

                if (-not $mustRestore) {
                    $current = [System.IO.File]::ReadAllBytes($change.Target)
                    $mustRestore = (
                        [Convert]::ToBase64String($current) -ne
                        [Convert]::ToBase64String($snapshot)
                    )
                }

                if ($mustRestore) {
                    [System.IO.File]::WriteAllBytes($change.Target, $snapshot)
                }

                $restored = [System.IO.File]::ReadAllBytes($change.Target)
                if ([Convert]::ToBase64String($restored) -ne
                    [Convert]::ToBase64String($snapshot)) {
                    throw 'Restored bytes do not match original snapshot.'
                }
            }
            catch {
                $restoreErrors.Add("$($change.Target): $($_.Exception.Message)")
            }
        }

        if ($restoreErrors.Count -gt 0) {
            throw "PRECHECK RESTORE INCOMPLETE. Original failure: $preApplyFailure. Restore errors: $($restoreErrors -join '; ')"
        }
        throw $preApplyFailure
    }

    Write-Host "`n===== BACKUP =====" -ForegroundColor Cyan
    foreach ($change in $changes) {
        if ($change.Create) {
            Write-Host "NO BACKUP (new file): $($change.Target)"
            continue
        }

        $backup = "$($change.Target).safebackup_$(Get-Date -Format 'yyyyMMdd_HHmmss_fff')_$([guid]::NewGuid().ToString('N')).bak"
        [System.IO.File]::Copy($change.Target, $backup, $false)

        $Backups.Add([pscustomobject]@{
            Target = $change.Target
            Backup = $backup
            Hash = (Get-FileHash -LiteralPath $change.Target -Algorithm SHA256).Hash
        })
        Write-Host "BACKUP: $backup"
    }

    Write-Host "`n===== APPLY =====" -ForegroundColor Cyan
    foreach ($change in $changes) {
        $stage = "$($change.Target).safechange_tmp_$([guid]::NewGuid().ToString('N'))"
        [System.IO.File]::Copy($change.Candidate, $stage, $false)
        $StagedFiles.Add($stage)

        if ($change.Create) {
            [System.IO.File]::Move($stage, $change.Target)
        }
        else {
            [System.IO.File]::Move($stage, $change.Target, $true)
        }

        [void]$AppliedTargets.Add($change.Target)
        Write-Host "APPLIED: $($change.Target)"
    }

    Invoke-Validation $postCheck 'PostApply'

    foreach ($change in $changes) {
        $candidateHash = (Get-FileHash -LiteralPath $change.Candidate -Algorithm SHA256).Hash
        $targetHash = (Get-FileHash -LiteralPath $change.Target -Algorithm SHA256).Hash
        if ($candidateHash -ne $targetHash) {
            throw "Post-apply hash mismatch: $($change.Target)"
        }
    }

    Write-Host "`nSUCCESS: changes applied and verified. Backups retained." -ForegroundColor Green
}
catch {
    $failure = $_.Exception.Message
    Write-Host "`nTRANSACTION FAILED: $failure" -ForegroundColor Red

    if ($AppliedTargets.Count -gt 0) {
        Write-Host "`n===== ROLLBACK =====" -ForegroundColor Yellow
        $rollbackErrors = [System.Collections.Generic.List[string]]::new()

        for ($index = $changes.Count - 1; $index -ge 0; $index--) {
            $change = $changes[$index]
            if (-not $AppliedTargets.Contains($change.Target)) { continue }

            try {
                if ($change.Create) {
                    if (Test-Path -LiteralPath $change.Target -PathType Leaf) {
                        $expectedHash = (Get-FileHash -LiteralPath $change.Candidate -Algorithm SHA256).Hash
                        $currentHash = (Get-FileHash -LiteralPath $change.Target -Algorithm SHA256).Hash

                        if ($currentHash -ne $expectedHash) {
                            throw 'Created target was modified; preserved during rollback.'
                        }

                        [System.IO.File]::Delete($change.Target)
                    }

                    if (Test-Path -LiteralPath $change.Target) {
                        throw 'Created target still exists after rollback deletion.'
                    }

                    Write-Host "CREATED FILE REMOVED AND VERIFIED: $($change.Target)" -ForegroundColor Green
                    continue
                }

                $backupRecord = $Backups |
                    Where-Object { $_.Target -eq $change.Target } |
                    Select-Object -First 1

                if ($null -eq $backupRecord) {
                    throw 'Backup record for replaced target was not found.'
                }

                [System.IO.File]::Copy($backupRecord.Backup, $change.Target, $true)
                $restoredHash = (Get-FileHash -LiteralPath $change.Target -Algorithm SHA256).Hash

                if ($restoredHash -ne $backupRecord.Hash) {
                    throw 'Restored hash does not match original.'
                }

                Write-Host "RESTORED AND VERIFIED: $($change.Target)" -ForegroundColor Green
            }
            catch {
                $rollbackErrors.Add("$($change.Target): $($_.Exception.Message)")
            }
        }

        if ($rollbackErrors.Count -gt 0) {
            throw "ROLLBACK INCOMPLETE: $($rollbackErrors -join '; '). Original error: $failure"
        }

        Write-Host 'ROLLBACK VERIFIED. Replacement backups retained.' -ForegroundColor Green
    }

    throw $failure
}
finally {
    foreach ($stage in $StagedFiles) {
        if (Test-Path -LiteralPath $stage) {
            Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue
        }
    }
    if ($MapPath -and (Test-Path -LiteralPath $MapPath)) {
        Remove-Item -LiteralPath $MapPath -Force -ErrorAction SilentlyContinue
    }
}