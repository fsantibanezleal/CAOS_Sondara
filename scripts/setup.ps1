# Create the virtual environments and install each lane's pinned requirements. Idempotent. No global installs.
# .ps1 parity of setup.sh (the same environments; -Gpu for .venv-gpu, docs/guides/03_gpu-lane.md).
#   .\scripts\setup.ps1 [-Gpu]
param([switch]$Gpu)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Get-VenvPy($dir) {
  $p = Join-Path $dir "Scripts\python.exe"
  if (-not (Test-Path $p)) { $p = Join-Path $dir "bin/python" }
  return $p
}

function Install-Lane($dir, $requirements) {
  if (-not (Test-Path $dir)) { & $py -m venv $dir; if ($LASTEXITCODE -ne 0) { throw "venv $dir failed" } }
  $vp = Get-VenvPy $dir
  & $vp -m pip install --upgrade pip -q
  if ($LASTEXITCODE -ne 0) { throw "pip upgrade in $dir failed" }
  & $vp -m pip install -q @requirements
  if ($LASTEXITCODE -ne 0) { throw "install in $dir failed" }
  Write-Host "[setup] $dir ready."
}

Write-Host "[setup] .venv-pipeline (offline lane)"
Install-Lane ".venv-pipeline" @("-r", "requirements-precompute.txt", "-r", "requirements-dev.txt")
Write-Host "[setup] .venv (runtime lane)"
Install-Lane ".venv" @("-r", "requirements.txt")
if ($Gpu) {
  Write-Host "[setup] .venv-gpu (offline lane with PyTorch CUDA 12.6)"
  Install-Lane ".venv-gpu" @("-r", "requirements-gpu.txt")
}
Write-Host "[setup] done. Next: .\scripts\precompute.ps1 acquire (docs/guides/01_precompute-pipeline.md)"
