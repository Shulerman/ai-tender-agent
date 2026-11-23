$script:DevProjectRoot = $PSScriptRoot

function Invoke-DevScript {
    param([string[]]$Arguments)

    $exe = Join-Path $PSHOME "pwsh.exe"
    & $exe -NoProfile -File (Join-Path $script:DevProjectRoot "dev.ps1") @Arguments

    if ($LASTEXITCODE -ne 0) {
        throw "dev.ps1 завершился с кодом $LASTEXITCODE."
    }
}

function Invoke-CiDatabaseSetup {
    $previousEnvironment = @{
        DATABASE_URL = $env:DATABASE_URL
        POSTGRES_PASSWORD = $env:POSTGRES_PASSWORD
        PYTHONPATH = $env:PYTHONPATH
    }

    Push-Location $script:DevProjectRoot

    try {
        $env:DATABASE_URL = "sqlite:///./ci_test.db"
        $env:POSTGRES_PASSWORD = "ci-test-only"
        $env:PYTHONPATH = "."

        python tests/ci_setup.py

        if ($LASTEXITCODE -ne 0) {
            throw "Подготовка тестовой базы завершилась ошибкой."
        }
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
}

function t {
    Invoke-DevScript -Arguments @("full")
}

function tp {
    param(
        [Parameter(Mandatory, Position = 0)]
        [string[]]$Paths
    )

    Invoke-CiDatabaseSetup
    Invoke-DevScript -Arguments (@("test") + $Paths)
}

function tc {
    Invoke-CiDatabaseSetup
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
    Write-Host "tc                        - подготовка тестовой БД"
    Write-Host "gs                        - Git status"
    Write-Host "gd                        - Git diff"
    Write-Host "glog                      - последние 5 коммитов"
    Write-Host "pyc                       - компиляция Python"
    Write-Host "dh                        - эта справка"
}
