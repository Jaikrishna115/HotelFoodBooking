$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$serverInfoPath = Join-Path $PSScriptRoot '.local\server-info.json'
if (Test-Path -LiteralPath $serverInfoPath) {
    $serverInfo = Get-Content -Raw -LiteralPath $serverInfoPath | ConvertFrom-Json
    $runningServer = Get-Process -Id $serverInfo.processId -ErrorAction SilentlyContinue
    if ($runningServer -and $runningServer.Path -eq $serverInfo.pythonPath -and $runningServer.StartTime.ToUniversalTime().Ticks.ToString() -eq $serverInfo.startTicks) {
        Write-Host 'The website is already running: http://127.0.0.1:8000' -ForegroundColor Green
        Write-Host 'To restart it in this terminal, run .\stop.ps1, then .\run.ps1.'
        exit 0
    }
}
$projectPython = Join-Path $PSScriptRoot 'Hotelbooking\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run .\setup.ps1 first.' }
& $projectPython tools\check_database.py
if ($LASTEXITCODE -ne 0) { throw 'Fix the .env database details or run .\setup.ps1.' }
& $projectPython manage.py check
if ($LASTEXITCODE -ne 0) { throw 'Website checks failed.' }
Write-Host 'Open http://127.0.0.1:8000 in your browser. Keep this terminal open.' -ForegroundColor Green
& $projectPython manage.py runserver 127.0.0.1:8000
