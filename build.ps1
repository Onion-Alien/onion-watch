# Builds Onion Watch for PCs without Python:
#   dist\OnionWatch\OnionWatch.exe   (one folder)
#   dist\OnionWatch-Installer.exe     (the one file to give people)
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
#
# VIRUS SCANNERS (don't undo either fix; README -> releasing has the evidence):
# - The installer is zip-compressed, not lzma (installer\OnionWatch.iss). With solid
#   lzma, Microsoft's machine-learning scanner on VirusTotal called nearly every build
#   "Trojan:Win32/Wacatac.B!ml", whatever was inside: 0.4.0, 0.3.1's source built again,
#   even an installer with no OnionWatch.exe in it. The same files zipped scan clean.
# - Every build uses a PyInstaller bootloader compiled on this PC
#   (scripts\build_bootloader.ps1, run automatically when the stock one is installed):
#   the stock one is the same file in thousands of programs, some of them malware.
# A release build (-Scan) that's flagged anyway isn't released.
param([switch]$Clean, [switch]$NoInstaller, [switch]$Scan)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv - see README.md, Running from source." }

$stock = "2291f269c3a3804fde1079462239e09a8b32fffbeeaa8f628a531faf5be77d41"   # 6.22.3's runw.exe
$runw = & $py -c "import PyInstaller, os; print(os.path.join(os.path.dirname(PyInstaller.__file__), 'bootloader', 'Windows-64bit-intel', 'runw.exe'))"
if ((Get-FileHash $runw -Algorithm SHA256).Hash.ToLower() -eq $stock) {
    Write-Host "PyInstaller's stock bootloader: compiling one here first" -ForegroundColor Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_bootloader.ps1
    if ($LASTEXITCODE -ne 0) { throw "scripts\build_bootloader.ps1 failed (see above)" }
    $Clean = $true
}

# the icon and the setup wizard's pictures are drawn in code, like the rest of the art
& $py scripts\make_installer_art.py
if ($LASTEXITCODE -ne 0) { throw "make_installer_art.py failed" }
# the exe's Properties -> Details (an exe without them looks suspicious to virus scanners)
& $py scripts\make_version_info.py
if ($LASTEXITCODE -ne 0) { throw "make_version_info.py failed" }

$cleanArg = @()
if ($Clean) { $cleanArg = @("--clean") }
# Of scipy only scipy.fft is used (onionwatch\imgops.py), with the linalg and special
# it imports; scipy's __init__ names every subpackage, so the rest is excluded by name.
& $py -m PyInstaller --noconfirm @cleanArg --windowed `
    --name OnionWatch --icon build\onionwatch.ico --version-file build\version_info.txt `
    --exclude-module scipy.signal --exclude-module scipy.ndimage `
    --exclude-module scipy.stats --exclude-module scipy.optimize `
    --exclude-module scipy.interpolate --exclude-module scipy.integrate `
    --exclude-module scipy.sparse --exclude-module scipy.spatial `
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
    Write-Host "Inno Setup 6 not found, so no OnionWatch-Installer.exe this time." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 0
}
$version = & $py -c "import onionwatch; print(onionwatch.__version__)"
& $iscc /Q "/DAppVersion=$version" installer\OnionWatch.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Built dist\OnionWatch-Installer.exe - that's the one file to give people." -ForegroundColor Green

# -Scan: VirusTotal (scripts\vt_scan.py, needs VT_API_KEY); the line for the release notes
if ($Scan) {
    & $py scripts\vt_scan.py dist\OnionWatch-Installer.exe --markdown | Out-Host
    $scanned = $LASTEXITCODE
    if ($scanned -eq 1) { throw "a virus scanner flagged OnionWatch-Installer.exe: don't release it (README -> releasing)" }
    if ($scanned -ne 0) { throw "the VirusTotal scan didn't run (see above)" }
}
