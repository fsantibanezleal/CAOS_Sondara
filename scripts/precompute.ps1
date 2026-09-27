# Run one offline stage (pass-through args). E.g.:  ./scripts/precompute.ps1 ingest --family rocklea
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$vp = Join-Path ".venv-pipeline" "Scripts\python.exe"
if (-not (Test-Path $vp)) { $vp = Join-Path ".venv-pipeline" "bin/python" }
& python data-pipeline/run.py @args
