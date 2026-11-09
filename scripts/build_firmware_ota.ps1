# Convenience entry point: build, then OTA upload. Arguments are forwarded unchanged.
& (Join-Path $PSScriptRoot 'build_firmware.ps1') @args
