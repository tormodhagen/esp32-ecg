param([string]$Python = 'python')
$Root = Split-Path $PSScriptRoot -Parent
& $Python (Join-Path $Root 'desktop\main.py')
