# Run only the installed project environment; do not discover or install Python.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$venvRoot = Join-Path $projectRoot '.venv'
$python = Join-Path $venvRoot 'Scripts\python.exe'
$configPath = Join-Path $venvRoot 'pyvenv.cfg'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $configPath)) {
    throw 'Project environment missing. Run .\setup.ps1 first.'
}
$config = Get-Content -LiteralPath $configPath -Raw
$homeMatch = [regex]::Match($config, '(?m)^home = (.+)\r?$')
$runtimeRoot = Join-Path $projectRoot '.python'
if (-not $homeMatch.Success -or
        -not $homeMatch.Groups[1].Value.Trim().StartsWith(
            $runtimeRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase) -or
        $config -notmatch 'include-system-site-packages = false') {
    throw 'The venv must use the private project runtime. Run .\setup.ps1.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $python -I -m discord_intel @args
    $result = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $result
