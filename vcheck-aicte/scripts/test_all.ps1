# Runs every automated test (Windows PowerShell). Engine + API take about a minute; UI tests need Playwright (see README).
$ErrorActionPreference = "Stop"
if (Test-Path ".\.venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
Set-Location backend
python -m unittest discover -s tests -t .
python -m unittest tests_api.test_api
if (python -c "import playwright" 2>$null) { python -m unittest tests_ui.test_ui } else { Write-Host "Skipping UI tests: pip install -r requirements-dev.txt ; playwright install chromium" }
Set-Location ..
