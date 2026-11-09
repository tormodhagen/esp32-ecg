[CmdletBinding()]
param(
    [string]$DeviceAddress = '',
    [string]$BleAddress = '',
    [string]$Environment = 'esp32dev',
    [string]$Python = '',
    [string]$Pio = '',
    [switch]$BuildOnly,
    [switch]$DirectHttp
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'python_env.ps1')
$Firmware = Join-Path $Root 'firmware'
if (-not (Test-Path (Join-Path $Firmware 'src\ota_config.h'))) { throw 'Copy your existing ota_config.h into firmware\src first.' }
$SelectedPython = Select-EcgPython -Root $Root -Explicit $Python
if (-not $Pio) {
    if (Test-Path 'C:\pio\penv\Scripts\platformio.exe') { $Pio = 'C:\pio\penv\Scripts\platformio.exe' }
    else {
        $command = Get-Command platformio -ErrorAction SilentlyContinue
        if (-not $command) { $command = Get-Command pio -ErrorAction SilentlyContinue }
        if ($command) { $Pio = $command.Source }
    }
}
Invoke-EcgCommand $SelectedPython @((Join-Path $Firmware 'embed_web.py'))
if ($Pio) {
    Invoke-EcgCommand $Pio @('run','-d',$Firmware,'-e',$Environment)
} else {
    Invoke-EcgCommand $SelectedPython @('-m','pip','install','platformio')
    Invoke-EcgCommand $SelectedPython @('-m','platformio','run','-d',$Firmware,'-e',$Environment)
}
$Image = Join-Path $Firmware ".pio\build\$Environment\firmware.bin"
if (-not (Test-Path $Image)) { throw "Firmware output not found: $Image" }
Write-Host "Built firmware: $Image" -ForegroundColor Green
if (-not $BuildOnly) {
    Write-Host 'Close the live ECG connection. Starting OTA upload of the newly built image.'
    $Arguments = @((Join-Path $Root 'desktop\ota_update.py'),'--project',$Firmware,'--environment',$Environment,'--firmware',$Image)
    if ($DeviceAddress) { $Arguments += @('--host',$DeviceAddress) }
    if ($BleAddress) { $Arguments += @('--address',$BleAddress) }
    if ($DirectHttp) {
        if (-not $DeviceAddress) { throw '-DirectHttp requires -DeviceAddress.' }
        $Arguments += '--http-upload'
    }
    Invoke-EcgCommand $SelectedPython $Arguments
}
