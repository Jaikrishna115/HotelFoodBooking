$ErrorActionPreference = 'Stop'
$serverInfoPath = Join-Path $PSScriptRoot '.local\server-info.json'
if (-not (Test-Path -LiteralPath $serverInfoPath)) {
    Write-Host 'No background website server is registered. Use Ctrl+C in its terminal if you started it manually.'
    exit 0
}
$serverInfo = Get-Content -Raw -LiteralPath $serverInfoPath | ConvertFrom-Json
$runningServer = Get-Process -Id $serverInfo.processId -ErrorAction SilentlyContinue
if (-not $runningServer) { Write-Host 'The background website is already stopped.'; exit 0 }
$expectedPython = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'Hotelbooking\Scripts\python.exe'))
if ($serverInfo.pythonPath -ne $expectedPython -or $runningServer.Path -ne $expectedPython -or $runningServer.StartTime.ToUniversalTime().Ticks.ToString() -ne $serverInfo.startTicks) {
    throw 'The saved process does not match this website server. No process was stopped.'
}
Stop-Process -Id $runningServer.Id
Write-Host 'The background website is stopped. Saved PostgreSQL data is retained.'
