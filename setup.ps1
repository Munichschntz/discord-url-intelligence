# Requires uv 0.12.7+ on PATH. Python itself is downloaded only into this project.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$runtimeRoot = Join-Path $projectRoot '.python'
$venvRoot = Join-Path $projectRoot '.venv'
$version = (Get-Content -LiteralPath (Join-Path $projectRoot '.python-version') -Raw).Trim()
$uv = (Get-Command uv -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
if ((Test-Path -LiteralPath $runtimeRoot) -and
        ((Get-Item -LiteralPath $runtimeRoot).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'The .python directory must not be a junction or symbolic link.'
}

# Restore the caller's environment even if download, setup, or validation fails.
$overrides = @{
    UV_PYTHON_INSTALL_DIR = $runtimeRoot
    UV_PYTHON_INSTALL_BIN = '0'
    UV_PYTHON_INSTALL_REGISTRY = '0'
    UV_PYTHON_NO_REGISTRY = '1'
    UV_PYTHON_PREFERENCE = 'only-managed'
    UV_PROJECT_ENVIRONMENT = $venvRoot
    UV_CACHE_DIR = (Join-Path $projectRoot '.uv-cache')
    UV_LINK_MODE = 'copy'
    VIRTUAL_ENV = $null
    PYTHONHOME = $null
    PYTHONPATH = $null
}
$saved = @{}
foreach ($name in $overrides.Keys) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location -LiteralPath $projectRoot
try {
    foreach ($name in $overrides.Keys) {
        [Environment]::SetEnvironmentVariable($name, $overrides[$name], 'Process')
    }
    & $uv python install $version --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) { throw 'Project Python installation failed.' }
    # Here --system skips venv discovery; only-managed still excludes system installations.
    $python = & $uv python find --system --no-project --no-python-downloads $version
    if ($LASTEXITCODE -ne 0) { throw 'Could not find the project Python runtime.' }
    $python = [IO.Path]::GetFullPath(($python | Out-String).Trim())
    if (-not $python.StartsWith($runtimeRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to use a Python runtime outside this project.'
    }

    # Keep an old environment intact when changing its base runtime. Never delete it.
    if (Test-Path -LiteralPath $venvRoot) {
        if ((Get-Item -LiteralPath $venvRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'The .venv directory must not be a junction or symbolic link.'
        }
        $configPath = Join-Path $venvRoot 'pyvenv.cfg'
        if (-not (Test-Path -LiteralPath $configPath)) {
            throw 'Existing .venv is not a virtual environment; move it aside before setup.'
        }
        $config = Get-Content -LiteralPath $configPath -Raw
        $expectedHome = Split-Path -Parent $python
        $homeMatch = [regex]::Match($config, '(?m)^home = (.+)\r?$')
        # uv may point home at its stable minor-version junction. Compare real directories.
        & $python -I -c 'import os, sys; sys.exit(not (os.path.isdir(sys.argv[1]) and os.path.samefile(sys.argv[1], sys.argv[2])))' $homeMatch.Groups[1].Value.Trim() $expectedHome
        if ($LASTEXITCODE -ne 0 -or
                $config -notmatch 'include-system-site-packages = false') {
            $backup = Join-Path $projectRoot ('.venv.previous-' + [guid]::NewGuid().ToString('N'))
            # Both paths are direct children of the verified project root.
            if ((Split-Path -Parent $venvRoot) -ne $projectRoot -or
                    (Split-Path -Parent $backup) -ne $projectRoot) {
                throw 'Environment paths escaped the project directory.'
            }
            Move-Item -LiteralPath $venvRoot -Destination $backup
            Write-Host "Previous environment preserved at $backup"
        }
    }
    if (-not (Test-Path -LiteralPath $venvRoot)) {
        & $uv venv --python $python --no-python-downloads $venvRoot
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    & $uv sync --locked --group dev --python $python --no-python-downloads
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; rerun setup to retry.' }
    & (Join-Path $venvRoot 'Scripts\python.exe') -I -c 'import sys; print(sys.executable); print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0) { throw 'Project interpreter verification failed.' }
    Write-Host 'Ready. Run: .\run.ps1 --help'
} finally {
    foreach ($name in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
    Pop-Location
}
