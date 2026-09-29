# Smoke: check every derived output in build/derived against its contract (scripts/check_artifacts.py: the
# drillhole.project/v2 projects, the stage outputs, the categorical and learned lanes, the scenario matrix).
#   .\scripts\smoke.ps1 [--derived DIR]
# Uses .venv-gpu when it exists, because the learned outputs are audited with onnx.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = $null
foreach ($venv in @(".venv-gpu", ".venv-pipeline")) {
  foreach ($exe in @("Scripts\python.exe", "bin/python")) {
    $candidate = Join-Path $venv $exe
    if (-not $py -and (Test-Path $candidate)) { $py = $candidate }
  }
}
if (-not $py) { $py = if ($env:PYTHON) { $env:PYTHON } else { "python" } }
& $py scripts/check_artifacts.py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
