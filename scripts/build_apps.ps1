[CmdletBinding()]
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path $PSScriptRoot -Parent
if ($env:OS -ne 'Windows_NT') { throw 'Run on Windows to build a Windows EXE.' }
. (Join-Path $PSScriptRoot 'python_env.ps1')
$BuildPython = Select-EcgPython -Root $Root -Explicit $Python
Push-Location $Root
try {
    Invoke-EcgCommand $BuildPython @('-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--noupx',
        '--name','ECG-Monitor','--distpath','dist','--workpath','build\pyinstaller','--specpath','build',
        '--paths','desktop','--collect-submodules','bleak','--hidden-import','ota_update',
        '--hidden-import','socket','--hidden-import','hashlib','--hidden-import','random',
        '--add-data','desktop\vendor;vendor','desktop\main.py')
    Write-Host "Built: $Root\dist\ECG-Monitor.exe (monitor and updater in one EXE)" -ForegroundColor Green
} finally { Pop-Location }
