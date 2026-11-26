$script:DevProjectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-DevScript {
    param([string[]]$Arguments)

    $exe = Join-Path $PSHOME "pwsh.exe"
    & $exe -NoProfile -File (Join-Path $script:DevProjectRoot "tools\dev.ps1") @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "dev.ps1 завершился с кодом $LASTEXITCODE."
    }
}



function dctx {
    & (Join-Path $PSScriptRoot "dctx.ps1")
}

function t {
    Invoke-DevScript -Arguments @("full")
}

function tp {
    param(
        [Parameter(Mandatory, Position = 0)]
        [string[]]$Paths
    )

    Invoke-DevScript -Arguments (@("test") + $Paths)
}

function tc {
    Write-Host "Отдельная подготовка БД больше не требуется." -ForegroundColor Cyan
    Write-Host "Миграции и ci_setup автоматически выполняются командами test, smart и full."
}

function gs {
    git.exe status --short
}

function gd {
    git.exe diff
}

function glog {
    git.exe log -5 --oneline
}

function pyc {
    Push-Location $script:DevProjectRoot
    try {
        python -m compileall -q app
        if ($LASTEXITCODE -ne 0) {
            throw "Python compilation failed."
        }
        Write-Host "Python compilation passed." -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}

function dh {
    Write-Host "AI Tender Agent - Shortcuts" -ForegroundColor Cyan
    Write-Host "t                         - полный набор проверок"
    Write-Host "tp tests\test_file.py    - подготовка БД и выбранные тесты"
    Write-Host "tc                        - информация о подготовке тестовой БД"
    Write-Host "gs                        - Git status"
    Write-Host "gd                        - Git diff"
    Write-Host "glog                      - последние 5 коммитов"
    Write-Host "pyc                       - компиляция Python"
    Write-Host "dctx                      - сбор контекста и копирование"`n    Write-Host "dh                        - эта справка"
}
