# Runs the EWMP desktop app in dev mode FROM THIS FOLDER, after checking that
# this folder really has the floating-widget update and nothing old is running.
#
#   powershell -ExecutionPolicy Bypass -File .\run-dev.ps1
#
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host ""
Write-Host "Folder: $PSScriptRoot"

# 1. Is the widget update in THIS folder?
$checks = @(
  @{ File = "src\main\index.ts";                        Marker = "showWidgetWindow" },
  @{ File = "src\renderer\src\screens\WidgetScreen.tsx"; Marker = "fw-card" },
  @{ File = "src\renderer\src\styles\floating-widget.css"; Marker = ".fw-card" }
)
$missing = $false
foreach ($c in $checks) {
  $found = (Test-Path $c.File) -and (Select-String -Path $c.File -Pattern $c.Marker -Quiet)
  if ($found) { Write-Host "  OK       $($c.File)" -ForegroundColor Green }
  else        { Write-Host "  MISSING  $($c.File)  (widget update not applied here)" -ForegroundColor Red; $missing = $true }
}
if ($missing) {
  Write-Host ""
  Write-Host "This folder does not have the widget update. Extract ewmp-floating-widget.zip" -ForegroundColor Red
  Write-Host "and ewmp-widget-startup-fix.zip over the project that contains this desktop-app folder." -ForegroundColor Red
  exit 1
}

# 2. Make sure no old copy (installed app or earlier dev run) is still alive:
#    a second launch would just bring that old copy back to the front.
$old = Get-Process | Where-Object { $_.ProcessName -in "electron", "ewmp-desktop-agent" }
if ($old) {
  Write-Host ""
  Write-Host "Closing $($old.Count) old EWMP/Electron process(es)..." -ForegroundColor Yellow
  $old | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}

# 3. Dependencies, then run.
if (-not (Test-Path "node_modules")) { Write-Host "Installing dependencies..."; npm install }
Write-Host ""
Write-Host "Starting... look for the line   [widget] shown at x=... y=...   below." -ForegroundColor Cyan
npm run dev
