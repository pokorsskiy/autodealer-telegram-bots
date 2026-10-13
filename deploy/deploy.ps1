# Выкладка на сервер одной командой: .\deploy\deploy.ps1
# Выкатывает только закоммиченное: проверяет ветку и рабочую копию, прогоняет
# тесты, пушит main и запускает на сервере deploy/update.sh.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "venv\Scripts\python.exe"
$sshHost = "autobot"
$siteUrl = "https://example.com/"

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "Выкладка остановлена: $text" -ForegroundColor Red; exit 1 }

Set-Location $root

Step "Проверка ветки и рабочей копии"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne "main") { Fail "текущая ветка $branch, выкладывается только main" }
$dirty = git status --porcelain
if ($dirty) {
    Write-Host ($dirty -join "`n")
    Fail "есть незакоммиченные изменения, на сервер уедет только то, что в коммитах"
}

Step "Тесты"
foreach ($bot in "showcase_bot", "showcase_telegram_bot", "showcase_webapp_bot", "showcase_hybrid_bot") {
    Push-Location (Join-Path $root $bot)
    & $python -m unittest --quiet
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "не прошли тесты $bot" }
}

Step "Отправка в GitHub"
git push origin main
if ($LASTEXITCODE -ne 0) { Fail "git push не прошёл" }

Step "Обновление сервера"
ssh $sshHost "sudo /opt/autobot/deploy/update.sh"
if ($LASTEXITCODE -ne 0) { Fail "update.sh на сервере завершился с ошибкой" }

Step "Проверка сайта"
try {
    $response = Invoke-WebRequest -Uri $siteUrl -UseBasicParsing -TimeoutSec 20
    Write-Host "$siteUrl отвечает: $($response.StatusCode)"
} catch {
    Fail "$siteUrl не отвечает: $($_.Exception.Message)"
}

$commit = (git log --oneline -1).Trim()
Write-Host "Готово. На сервере: $commit" -ForegroundColor Green
