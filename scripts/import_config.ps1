param([Parameter(Mandatory=$true)][string]$OldProject)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Source = Join-Path $OldProject 'src\ota_config.h'
$Destination = Join-Path $Root 'firmware\src\ota_config.h'
if (-not (Test-Path $Source)) { throw "No configuration at $Source" }
if (Test-Path $Destination) { throw 'Destination configuration already exists. Compare files manually.' }
Copy-Item -LiteralPath $Source -Destination $Destination
Write-Host 'Copied your local firmware configuration. Original project unchanged.'
