# Run one offline stage (pass-through args). E.g.:  ./scripts/precompute.ps1 ingest --family rocklea
# Uses .venv-gpu when it exists (it holds the pipeline packages and PyTorch, which the learned lane needs), else
# .venv-pipeline, where the learned lane stops with a message (pass --lane continuous or --lane categorical).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$vp = $null
foreach ($venv in @(".venv-gpu", ".venv-pipeline")) {
  foreach ($exe in @("Scripts\python.exe", "bin/python")) {
    $candidate = Join-Path $venv $exe
    if (-not $vp -and (Test-Path $candidate)) { $vp = $candidate }
  }
}
if (-not $vp) { throw "no .venv-gpu or .venv-pipeline; run scripts/setup.ps1 first" }
& $vp data-pipeline/run.py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
