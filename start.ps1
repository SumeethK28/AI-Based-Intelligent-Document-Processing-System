param([switch]$NoBrowser, [switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
try {
    if ((Get-Location).Path -ne $PSScriptRoot) { throw 'Open PowerShell in the project folder first, then run start.cmd.' }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv, reopen PowerShell, and run setup.cmd first.' }
    if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Run .\setup.cmd first.' }
    $statusText = & uv run --frozen --no-sync --python 3.14.6 python scripts/student_start.py status
    if ($LASTEXITCODE -ne 0) { throw 'Startup checks failed. Follow the message above before trying again.' }
    $status = $statusText | ConvertFrom-Json
    if (-not $status.has_key) { Write-Host 'AI processing is unavailable until you add your own GROQ_API_KEY in .env. Accounts and the website still work.' }
    if ($status.setup_required -and -not $NonInteractive) {
        Write-Host 'This installation needs its first Administrator. Only authorize this on your own trusted computer.'
        $authorize = Read-Host 'Authorize Administrator setup for the next 15 minutes? [y/N]'
        if ($authorize -match '^[yY]$') {
            & uv run --frozen --no-sync --python 3.14.6 python scripts/manage_security.py --database $status.database authorize-setup
            if ($LASTEXITCODE -ne 0) { throw 'Local authorization failed. No Administrator was created.' }
            Write-Host 'Privately open the credential file shown above. Copy its value into Organization setup in the website. Never share it.'
        }
    }
    Write-Host ('Website: http://127.0.0.1:' + $status.port)
    Write-Host 'Leave this window open. Press Ctrl+C here to stop. Your saved work remains available next time.'
    $arguments = @('run','--frozen','--no-sync','--python','3.14.6','python','scripts/student_start.py','start')
    if ($NoBrowser) { $arguments += '--no-browser' }
    & uv @arguments
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 130) { throw 'The website stopped with an error. Check the message above.' }
} catch {
    Write-Host ('Startup stopped: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
