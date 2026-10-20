param([switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
try {
    if ((Get-Location).Path -ne $PSScriptRoot) { throw 'Open PowerShell in the project folder first, then run setup.cmd.' }
    foreach ($file in @('pyproject.toml','uv.lock','frontend/package-lock.json','.env.example')) {
        if (-not (Test-Path -LiteralPath $file)) { throw 'This is not a complete project folder. Clone the repository again.' }
    }
    foreach ($tool in @('git','uv','node','npm')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "Install $tool first, then close and reopen PowerShell. See the Student Quick Start for download links."
        }
    }
    $nodeVersion = & node -p 'process.versions.node'
    if ($LASTEXITCODE -ne 0) { throw 'Node.js could not start. Reinstall Node.js LTS.' }
    $version = [version]$nodeVersion
    if (-not (($version.Major -eq 20 -and $version -ge [version]'20.19.0') -or $version -ge [version]'22.12.0')) {
        throw 'Install a current Node.js LTS release (22.12 or newer), then reopen PowerShell.'
    }
    Write-Host 'Installing Python 3.14.6 and the locked application packages...'
    & uv sync --frozen --python 3.14.6
    if ($LASTEXITCODE -ne 0) { throw 'Python setup failed. Check your internet connection and rerun setup.cmd.' }
    & npm.cmd --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend package installation failed. Check your internet connection and rerun setup.cmd.' }
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'React build failed. Keep the error above and ask your project maintainer for help.' }
    & uv run --frozen --python 3.14.6 python scripts/student_start.py configure
    if ($LASTEXITCODE -ne 0) { throw 'Configuration needs attention. Follow the message above, then rerun setup.cmd.' }
    if (-not $NonInteractive) {
        Write-Host 'To enable AI processing, privately edit GROQ_API_KEY in .env. Never share this file.'
        $edit = Read-Host 'Open .env in Notepad now? [y/N]'
        if ($edit -match '^[yY]$') { Start-Process notepad.exe -ArgumentList '.env' -Wait }
    }
    Write-Host 'Setup complete. Run .\start.cmd to open the website.'
} catch {
    Write-Host ('Setup stopped: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
