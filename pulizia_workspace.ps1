# =============================================================================
# pulizia_workspace.ps1
# Pulisce la cartella di lavoro PHD2_Assist_PATCHED dei file non più necessari.
# Da lanciare con: click destro -> "Esegui con PowerShell"
# Oppure da PowerShell:  powershell -ExecutionPolicy Bypass -File pulizia_workspace.ps1
# =============================================================================

$ErrorActionPreference = "Continue"
$root = "C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED"

Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host " Pulizia cartella di lavoro Adaptive Agent for PHD2" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""

# --- GUARDIA: verifica di essere nella cartella giusta -----------------------
if (-not (Test-Path "$root\build_dist.py") -or -not (Test-Path "$root\NOTE_CLAUDE.md")) {
    Write-Host "ERRORE: $root non sembra essere la cartella corretta del progetto." -ForegroundColor Red
    Write-Host "Verificare che esista C:\Users\aless\Downloads\PHD2_Assist_PATCHED\PHD2_Assist_PATCHED\" -ForegroundColor Red
    Read-Host "Premi Invio per uscire"
    exit 1
}
Set-Location $root

# --- Spazio prima -------------------------------------------------------------
$sizeBefore = (Get-ChildItem -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("Spazio occupato PRIMA: {0:N1} MB" -f $sizeBefore) -ForegroundColor Yellow
Write-Host ""

# --- CATEGORIA A: build artifacts rigenerabili -------------------------------
Write-Host "[A] Eliminazione build artifacts (dist, build, __pycache__, .pytest_cache)..." -ForegroundColor Green

$targetsA = @(
    "$root\dist",
    "$root\build",
    "$root\.pytest_cache"
)
foreach ($t in $targetsA) {
    if (Test-Path $t) {
        # -Force serve per superare attributi read-only su file PyInstaller/pytest
        Remove-Item -Path $t -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $t) {
            Write-Host "  WARN: $t resta presente (qualche file in uso?)" -ForegroundColor Yellow
        } else {
            Write-Host "  OK eliminata: $(Split-Path $t -Leaf)" -ForegroundColor DarkGray
        }
    }
}

# __pycache__ ovunque dentro il progetto
Get-ChildItem -Path $root -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
    Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  OK eliminata: $($_.FullName.Substring($root.Length + 1))" -ForegroundColor DarkGray
}

# --- CATEGORIA B: pulizia varia ----------------------------------------------
Write-Host ""
Write-Host "[B] Pulizia ZIP duplicati, logs root, scratch files..." -ForegroundColor Green

$targetsB = @(
    "$root\AdaptiveAgentForPHD2.NinaPlugin.zip",
    "$root\AdaptiveAgentForPHD2.zip",
    "$root\scratch_expose.py",
    "$root\test_e2e.py"
)
foreach ($t in $targetsB) {
    if (Test-Path $t) {
        Remove-Item -Path $t -Force -ErrorAction SilentlyContinue
        if (Test-Path $t) {
            Write-Host "  WARN: $(Split-Path $t -Leaf) resta presente" -ForegroundColor Yellow
        } else {
            Write-Host "  OK eliminato: $(Split-Path $t -Leaf)" -ForegroundColor DarkGray
        }
    }
}

# logs/ nella root: cancella tutti i file dentro, poi la cartella
if (Test-Path "$root\logs") {
    Get-ChildItem -Path "$root\logs" -File -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item -Path "$root\logs" -Force -ErrorAction SilentlyContinue
    if (Test-Path "$root\logs") {
        Write-Host "  WARN: logs/ resta presente (cartella non vuota?)" -ForegroundColor Yellow
    } else {
        Write-Host "  OK eliminata: logs/" -ForegroundColor DarkGray
    }
}

# --- CATEGORIA C: sposta PROMPT_*.md in prompts_storici/ ---------------------
Write-Host ""
Write-Host "[C] Sposto PROMPT_*.md in prompts_storici/..." -ForegroundColor Green

if (-not (Test-Path "$root\prompts_storici")) {
    New-Item -ItemType Directory -Path "$root\prompts_storici" | Out-Null
}
$prompts = Get-ChildItem -Path $root -Filter "PROMPT_*.md" -File
foreach ($p in $prompts) {
    Move-Item -Path $p.FullName -Destination "$root\prompts_storici\" -Force -ErrorAction SilentlyContinue
    Write-Host "  Spostato: $($p.Name)" -ForegroundColor DarkGray
}
$movedCount = (Get-ChildItem -Path "$root\prompts_storici" -Filter "PROMPT_*.md").Count
Write-Host "  Totale PROMPT_*.md in prompts_storici/: $movedCount" -ForegroundColor Green

# --- VERIFICA file critici INTATTI -------------------------------------------
Write-Host ""
Write-Host "[VERIFICA] File e cartelle critici intatti:" -ForegroundColor Cyan
$critical = @(
    "Adaptive_Agent_PHD2_v2.2.zip",
    "Pacchetto_Distribuzione",
    "AdaptiveAgentForPHD2.NinaPlugin",
    "config.toml", "main.py", "build_dist.py", "PHD2_Agent.spec",
    "NOTE_CLAUDE.md", "CONTESTO_PROGETTO.md", "README.md",
    "doc", "phd2_agent", "tests", "dashboard", "simulator"
)
foreach ($c in $critical) {
    if (Test-Path "$root\$c") {
        Write-Host "  OK $c" -ForegroundColor DarkGreen
    } else {
        Write-Host "  ATTENZIONE manca: $c" -ForegroundColor Red
    }
}

# --- Spazio dopo --------------------------------------------------------------
Write-Host ""
$sizeAfter = (Get-ChildItem -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB
$saved = $sizeBefore - $sizeAfter
Write-Host ("Spazio occupato DOPO:  {0:N1} MB" -f $sizeAfter) -ForegroundColor Yellow
Write-Host ("Liberati:              {0:N1} MB" -f $saved) -ForegroundColor Green
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host " Pulizia completata." -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan

Read-Host "Premi Invio per chiudere"
