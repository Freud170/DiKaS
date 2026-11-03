# Baut DiKaS.exe (PyInstaller) und den Installer DiKaS-Setup-<Version>.exe (Inno Setup).
#
# Aufruf im Projektordner:   .\packaging\bauen.ps1
# Optional ohne Tests:       .\packaging\bauen.ps1 -OhneTests
# Ergebnis:                  build\installer\DiKaS-Setup-<Version>.exe

param(
    [switch]$OhneTests
)

# Fehler werden über $LASTEXITCODE geprüft: PyInstaller schreibt normale Meldungen auf stderr,
# was Windows PowerShell 5.1 sonst als Fehler wertet.
$ErrorActionPreference = "Continue"
$projekt = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projekt ".venv\Scripts\python.exe"
$build = Join-Path $projekt "build"

function Schritt($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

if (-not (Test-Path $python)) { throw "Python-Umgebung fehlt: $python" }

# Version aus dem Programm lesen (eine Quelle der Wahrheit: dikas/__init__.py)
$version = & $python -c "import dikas; print(dikas.__version__)"
Write-Host "DiKaS Version $version"

if (-not $OhneTests) {
    Schritt "Tests"
    & $python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen – es wird nichts gebaut." }
}

Schritt "DiKaS.exe bauen (PyInstaller)"
# Nur Windows und Python im PATH: sonst sammelt PyInstaller fremde DLLs ein, die zufällig im
# PATH liegen (z. B. aus einem Java-JDK). Der eigene PATH wird danach wiederhergestellt.
$alterPath = $env:Path
$pythonBasis = & $python -c "import sys; print(sys.base_prefix)"
$env:Path = "$env:SystemRoot\System32;$env:SystemRoot;$pythonBasis;$(Split-Path $python)"
try {
& $python -m PyInstaller `
    --noconfirm --clean --windowed `
    --name DiKaS `
    --icon (Join-Path $PSScriptRoot "dikas.ico") `
    --add-data "$(Join-Path $projekt 'dikas\ui\haken.svg');dikas\ui" `
    --add-data "$(Join-Path $projekt 'dikas\ui\symbol.png');dikas\ui" `
    --distpath (Join-Path $build "dist") `
    --workpath (Join-Path $build "work") `
    --specpath $build `
    (Join-Path $PSScriptRoot "start_dikas.py")
$pyinstallerErgebnis = $LASTEXITCODE
} finally {
    $env:Path = $alterPath
}
if ($pyinstallerErgebnis -ne 0) { throw "PyInstaller fehlgeschlagen." }

Schritt "Installer bauen (Inno Setup)"
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup nicht gefunden. Installation: winget install JRSoftware.InnoSetup" }

& $iscc /Q `
    "/DVersion=$version" `
    "/DQuelle=$(Join-Path $build 'dist\DiKaS')" `
    "/DAusgabe=$(Join-Path $build 'installer')" `
    (Join-Path $PSScriptRoot "dikas.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fehlgeschlagen." }

$setup = Join-Path $build "installer\DiKaS-Setup-$version.exe"
Schritt "Fertig"
Write-Host "Installer: $setup ($([math]::Round((Get-Item $setup).Length / 1MB)) MB)" -ForegroundColor Green
