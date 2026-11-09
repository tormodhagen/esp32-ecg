# Shared environment selection. Only the selected environment is modified.
function Invoke-EcgCommand {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Program" }
}
function Select-EcgPython {
    param([string]$Root, [string]$Explicit = '')
    $requirements = Join-Path $Root 'requirements.txt'
    $probe = Join-Path $Root 'scripts\probe_env.py'
    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($Explicit) { $candidates.Add($Explicit) }
    else {
        if ($env:VIRTUAL_ENV) { $candidates.Add((Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe')) }
        $roots = @($Root, (Split-Path $Root -Parent))
        # Scan sibling projects, not dependency trees or the entire disk.
        $roots += @(Get-ChildItem -LiteralPath (Split-Path $Root -Parent) -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
        foreach ($base in ($roots | Select-Object -Unique)) {
            foreach ($dir in @(Get-ChildItem -LiteralPath $base -Directory -Force -ErrorAction SilentlyContinue)) {
                if (Test-Path (Join-Path $dir.FullName 'pyvenv.cfg')) {
                    $path = Join-Path $dir.FullName 'Scripts\python.exe'
                    if (Test-Path $path) { $candidates.Add($path) }
                }
            }
            foreach ($name in @('.venv','.build-venv','venv','env')) {
                $path = Join-Path $base "$name\Scripts\python.exe"
                if (Test-Path -LiteralPath $path) { $candidates.Add($path) }
            }
        }
        if ($env:WORKON_HOME -and (Test-Path $env:WORKON_HOME)) {
            foreach ($dir in Get-ChildItem $env:WORKON_HOME -Directory) {
                $path = Join-Path $dir.FullName 'Scripts\python.exe'
                if (Test-Path $path) { $candidates.Add($path) }
            }
        }
    }
    $results = @()
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        try {
            $output = & $candidate $probe $requirements 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $info = ($output -join "`n") | ConvertFrom-Json
            if (-not $info.compatible) { continue }
            # Automatic selection only reuses virtual environments.
            if (-not $Explicit -and -not $info.venv) { continue }
            Write-Host ("Found {0}/{1} requirements: {2}" -f $info.matched,$info.total,$info.python)
            $results += $info
        } catch { Write-Host "Skipping unusable interpreter: $candidate" }
    }
    if ($results.Count -eq 0) {
        if ($Explicit) { throw 'Specified Python could not be inspected. Use a 64-bit Python 3.10+ environment with pip.' }
        $launcher = Get-Command python -ErrorAction SilentlyContinue
        if (-not $launcher) { $launcher = Get-Command py -ErrorAction SilentlyContinue }
        if (-not $launcher) { throw 'No usable Python found. Install 64-bit Python 3.12 or pass -Python once.' }
        $destination = Join-Path $Root '.build-venv'
        if (Test-Path $destination) { $destination = Join-Path $Root ('.build-venv-' + (Get-Date -Format yyyyMMddHHmmss)) }
        Invoke-EcgCommand $launcher.Source @('-m','venv',$destination)
        $selected = Join-Path $destination 'Scripts\python.exe'
    } else {
        $selected = ($results | Sort-Object -Property matched -Descending | Select-Object -First 1).python
    }
    Write-Host "Using Python: $selected" -ForegroundColor Cyan
    # pip only changes dependencies that do not satisfy the version constraints.
    Invoke-EcgCommand $selected @('-m','pip','install','-r',$requirements)
    $check = & $selected $probe $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Environment verification failed.' }
    $info = ($check -join "`n") | ConvertFrom-Json
    if (-not $info.compatible -or $info.missing.Count -gt 0) { throw 'Selected environment still has unmet requirements.' }
    return [string]$selected
}
