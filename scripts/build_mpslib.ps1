# Build MPSlib's SNESIM executables from the pinned commit, through WSL (the executables are Linux programs).
# .ps1 parity of build_mpslib.sh: same argument, same target, same receipt.
#   .\scripts\build_mpslib.ps1 [TARGET]     TARGET defaults to $env:SONDARA_MPSLIB, else build\mpslib
# Needs WSL with git, make and g++ in the default distribution (or $env:SONDARA_WSL_DISTRO).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$target = if ($args.Count -gt 0) { $args[0] } elseif ($env:SONDARA_MPSLIB) { $env:SONDARA_MPSLIB } else { "build\mpslib" }
New-Item -ItemType Directory -Force $target | Out-Null

function To-Wsl($path) {
  $full = (Resolve-Path $path).Path
  $drive = $full.Substring(0, 1).ToLower()
  return "/mnt/$drive" + ($full.Substring(2) -replace "\\", "/")
}

$repo = To-Wsl "."
$dest = To-Wsl $target
$distro = @()
if ($env:SONDARA_WSL_DISTRO) { $distro = @("-d", $env:SONDARA_WSL_DISTRO) }
& wsl.exe @distro --exec bash "$repo/scripts/build_mpslib.sh" "$dest"
if ($LASTEXITCODE -ne 0) { throw "MPSlib build failed (exit $LASTEXITCODE)" }
