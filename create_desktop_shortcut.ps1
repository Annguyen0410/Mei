# Create a desktop shortcut to the built Mei.exe with the app icon.
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe  = Join-Path $root "dist\Mei.exe"
$icon = Join-Path $root "icon.ico"

if (-not (Test-Path $exe)) {
    Write-Host "Not found: $exe" -ForegroundColor Red
    Write-Host "Build first with: .\build_exe.bat" -ForegroundColor Yellow
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Mei.lnk"

# Remove any stale LiteBrowser shortcut so only the new Mei icon remains.
$oldLnk = Join-Path $desktop "LiteBrowser.lnk"
if (Test-Path $oldLnk) { Remove-Item $oldLnk -Force }

$ws  = New-Object -ComObject WScript.Shell
$sc  = $ws.CreateShortcut($lnk)
$sc.TargetPath       = $exe
$sc.WorkingDirectory = Split-Path -Parent $exe
if (Test-Path $icon) { $sc.IconLocation = $icon }
$sc.Description = "Mei Tea Room Edition"
$sc.Save()

Write-Host "Shortcut created: $lnk" -ForegroundColor Green
Write-Host "Double-click to open Mei as a desktop app." -ForegroundColor Green
