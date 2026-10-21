param([switch]$CPU)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimeVigia = $env:VIGIAAI_PYTHON
if (-not $runtimeVigia -and (Test-Path -LiteralPath '.runtime-python')) {
    $runtimeVigia = (Get-Content -LiteralPath '.runtime-python' -Raw).Trim()
}
if (-not $runtimeVigia) { $runtimeVigia = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $runtimeVigia)) {
    throw 'Python do VigiaAI não encontrado. Configure VIGIAAI_PYTHON conforme docs/APRIMORAMENTO_IA.md.'
}
if ($CPU) { $env:VIGIAAI_DEVICE = 'cpu' }
& $runtimeVigia (Join-Path $PSScriptRoot 'main.py')
exit $LASTEXITCODE
