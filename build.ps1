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
#   -Scan         then scan the installer on VirusTotal (needs VT_API_KEY): fails if any
#                 engine flags it, else prints the line for the release notes
param([switch]$Clean, [switch]$NoInstaller, [switch]$Scan)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv - see README.md, Running from source." }

# PyPI's stock bootloader gets a machine-learning "Trojan" verdict from Microsoft on
# VirusTotal; one compiled here doesn't (scripts\build_bootloader.ps1)
$stock = "2291f269c3a3804fde1079462239e09a8b32fffbeeaa8f628a531faf5be77d41"   # 6.22.3's runw.exe
$runw = & $py -c "import PyInstaller, os; print(os.path.join(os.path.dirname(PyInstaller.__file__), 'bootloader', 'Windows-64bit-intel', 'runw.exe'))"
if ((Get-FileHash $runw -Algorithm SHA256).Hash.ToLower() -eq $stock) {
    throw "PyInstaller's stock bootloader: run scripts\build_bootloader.ps1 once first"
}

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

# -Scan: VirusTotal (scripts\vt_scan.py, needs VT_API_KEY); the line for the release notes
if ($Scan) {
    & $py scripts\vt_scan.py dist\OnionWatchSetup.exe --markdown | Out-Host
    if ($LASTEXITCODE -eq 1) { throw "a virus scanner flagged OnionWatchSetup.exe: don't release it (see above)" }
    if ($LASTEXITCODE -ne 0) { throw "the VirusTotal scan didn't run (see above)" }
}
