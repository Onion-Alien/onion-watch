# Builds Onion Watch for PCs without Python:
#   dist\OnionWatch\OnionWatch.exe   (one folder)
#   dist\OnionWatchSetup.exe          (the one file to give people)
#   dist\OnionWatch-module.zip        (the Onion Board add-on, see scripts\build_module.py)
#
# Needs the dev tools once:  .venv\Scripts\pip install -r requirements-dev.txt
# The installer step needs Inno Setup 6 once:  winget install JRSoftware.InnoSetup
# Run:                       powershell -ExecutionPolicy Bypass -File build.ps1
#
#   -Clean        start PyInstaller from scratch (for a release, or a build acting strangely)
#   -NoInstaller  stop after the app folder
param([switch]$Clean, [switch]$NoInstaller)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv - see README.md, Running from source." }

# the icon and the setup wizard's pictures are drawn in code, like the rest of the art
& $py scripts\make_installer_art.py
if ($LASTEXITCODE -ne 0) { throw "make_installer_art.py failed" }
# the exe's Properties -> Details (an exe without them looks suspicious to virus scanners)
& $py scripts\make_version_info.py
if ($LASTEXITCODE -ne 0) { throw "make_version_info.py failed" }

$cleanArg = @()
if ($Clean) { $cleanArg = @("--clean") }
& $py -m PyInstaller --noconfirm @cleanArg --windowed `
    --name OnionWatch --icon build\onionwatch.ico --version-file build\version_info.txt `
    --paths . `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# PyInstaller ships all of Qt; drop what the app never loads, then prove it still starts
& $py scripts\prune_build.py dist\OnionWatch
if ($LASTEXITCODE -ne 0) { throw "prune_build.py failed" }
& "dist\OnionWatch\OnionWatch.exe" --selftest | Out-Host
if ($LASTEXITCODE -ne 0) { throw "the built app failed its self-test (see above)" }

# Licences travel with the binaries (Qt is LGPL; see scripts\make_notices.py)
Copy-Item LICENSE "dist\OnionWatch\LICENSE.txt"
& $py scripts\make_notices.py "dist\OnionWatch\THIRD-PARTY-NOTICES.txt"
if ($LASTEXITCODE -ne 0) { throw "make_notices.py failed" }

& $py scripts\build_module.py
if ($LASTEXITCODE -ne 0) { throw "build_module.py failed" }

$size = [math]::Round((Get-ChildItem dist\OnionWatch -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Built dist\OnionWatch\OnionWatch.exe ($size MB folder)" -ForegroundColor Green
if ($NoInstaller) { exit 0 }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup 6 not found, so no OnionWatchSetup.exe this time." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 0
}
$version = & $py -c "import onionwatch; print(onionwatch.__version__)"
& $iscc /Q "/DAppVersion=$version" installer\OnionWatch.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Built dist\OnionWatchSetup.exe - that's the one file to give people." -ForegroundColor Green
