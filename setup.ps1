$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot 'Hotelbooking\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    python -m venv Hotelbooking
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& $projectPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $projectPython tools\configure_database.py
if ($LASTEXITCODE -ne 0) { throw 'Database setup is incomplete.' }
& $projectPython manage.py migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $projectPython manage.py seed_menu
if ($LASTEXITCODE -ne 0) { throw 'Menu setup failed.' }
& $projectPython manage.py bootstrap_billing
if ($LASTEXITCODE -ne 0) { throw 'Billing account setup needs attention.' }
Write-Host 'Setup complete. Run .\run.ps1, then open http://127.0.0.1:8000' -ForegroundColor Green
