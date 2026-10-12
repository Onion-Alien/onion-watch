# The checks a commit needs, in one go (as Onion Board's): ruff, the sensitive-data
# scan, the i18n catalogs, CODE.md's module list, and pyright on changed files. The
# tests are left to CI unless you ask (-Tests: the whole suite, about 40 s).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\precommit.ps1
#   ... -Tests    also run the tests
#   ... -Base X   compare with branch X instead of origin/main
#
# Stops at the first failure. Run from anywhere; it works in the repo root. In a git
# worktree without its own .venv, the main checkout's .venv is used.
param([switch]$Tests, [string]$Base = "origin/main")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $main = Split-Path -Parent (Resolve-Path (git rev-parse --git-common-dir))
    $py = Join-Path $main ".venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) { throw "No .venv: see docs/CODE.md, Running from source" }
$env:QT_QPA_PLATFORM = "offscreen"
$total = [Diagnostics.Stopwatch]::StartNew()

# how long each step and the whole run took, so it's clear what's slow
function Took($sw) { "{0:0.0} s" -f $sw.Elapsed.TotalSeconds }

function Step($name, [scriptblock]$cmd) {
    Write-Host "== $name" -ForegroundColor Cyan
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $name ($(Took $sw), total $(Took $total))" -ForegroundColor Red; exit 1
    }
    Write-Host "   $name took $(Took $sw)" -ForegroundColor DarkGray
}

Step "ruff" { & $py -m ruff check . }
Step "sensitive data" { & $py scripts\check_sensitive.py }
# as CI's lint job: every text in every catalog, and every module in docs/CODE.md
Step "translations" { & $py scripts\i18n_extract.py --check }
Step "CODE.md modules" { & $py scripts\check_code_doc.py }
# pyright on the changed files; only errors not in scripts/pyright_baseline.json fail
Step "types (new errors only)" { & $py scripts\check_types.py --base $Base }

# A fix comes with the test that would have caught it. Only a warning: some fixes
# can't be tested, and the PR's "Regression test:" line says why.
$ErrorActionPreference = "Continue"   # git's line-ending notes on stderr aren't failures
$branch = git rev-parse --abbrev-ref HEAD
$subjects = @(git log "$Base..HEAD" --format=%s 2>$null)
$changed = @(git diff --name-only $Base 2>$null) + @(git ls-files --others --exclude-standard)
$ErrorActionPreference = "Stop"
$isFix = ($branch -like "fix/*") -or ($subjects -match '(?i)\bfix')
if ($isFix -and ($changed -like "onionwatch/*") -and -not ($changed -like "tests/*")) {
    Write-Host "WARNING: this looks like a fix but changes no tests. Add the test that would have caught it, or say why not on the PR's 'Regression test:' line." -ForegroundColor Yellow
}

if (-not $Tests) {
    Write-Host "Checks passed in $(Took $total). Tests left to CI (-Tests runs them here)." -ForegroundColor Green
    exit 0
}
Step "pytest" { & $py -m pytest -q }
Write-Host "All checks passed in $(Took $total)." -ForegroundColor Green
