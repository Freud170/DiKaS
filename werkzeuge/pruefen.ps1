# Prüft den Code vor einem Commit: Lint (ruff), Typen (ty), Tests mit Abdeckung (pytest).
#
# Aufruf im Projektordner:   .\werkzeuge\pruefen.ps1
# Ohne Tests (schnell):      .\werkzeuge\pruefen.ps1 -OhneTests
# Mit Abhängigkeitsprüfung:  .\werkzeuge\pruefen.ps1 -Audit     (braucht Internet)
#
# Die Regeln stehen in pyproject.toml ([tool.ruff], [tool.ty], [tool.coverage]).
# Rückgabewert 0 = alles in Ordnung, 1 = mindestens ein Schritt ist fehlgeschlagen.

param(
    [switch]$OhneTests,
    [switch]$Audit
)

# Fehler werden über $LASTEXITCODE geprüft (wie in packaging\bauen.ps1)
$ErrorActionPreference = "Continue"
$projekt = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projekt ".venv\Scripts\python.exe"
# Unter dieser Testabdeckung (in Prozent) gilt der Lauf als fehlgeschlagen
$mindestAbdeckung = 90

if (-not (Test-Path $python)) {
    throw "Python-Umgebung fehlt: $python (Einrichten siehe README, Abschnitt 'Einrichten')"
}

$fehlgeschlagen = @()

function Schritt($name, [scriptblock]$befehl) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $befehl
    if ($LASTEXITCODE -ne 0) {
        $script:fehlgeschlagen += $name
        Write-Host "--> ${name}: FEHLER" -ForegroundColor Red
    } else {
        Write-Host "--> ${name}: ok" -ForegroundColor Green
    }
}

Push-Location $projekt
try {
    # Lint: unbenutzte Importe/Variablen, typische Fehlerquellen, Sicherheitsregeln
    Schritt "ruff (Lint)" { & $python -m ruff check dikas tests packaging }

    # Typprüfung: Fehler in der Fachlogik brechen ab, Warnungen (Oberfläche/Qt) nur anzeigen
    Schritt "ty (Typen)" { & $python -m ty check --exit-zero-on-warning --output-format concise }

    if (-not $OhneTests) {
        Schritt "pytest (Tests mit Abdeckung)" {
            # --disable-warnings: Die Abdeckungsmessung löst hunderte harmlose ResourceWarnings aus
            & $python -m pytest -q -p no:cacheprovider --disable-warnings `
                --cov --cov-report=term --cov-fail-under=$mindestAbdeckung
        }
    }

    if ($Audit) {
        # Bekannte Sicherheitslücken in den installierten Paketen (fragt die PyPI-Datenbank ab)
        Schritt "pip-audit (Abhängigkeiten)" { & $python -m pip_audit --skip-editable }
    }
} finally {
    Pop-Location
}

Write-Host ""
if ($fehlgeschlagen.Count -gt 0) {
    Write-Host "Fehlgeschlagen: $($fehlgeschlagen -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "Alle Prüfungen bestanden." -ForegroundColor Green
exit 0
