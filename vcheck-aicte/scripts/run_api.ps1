# Starts the V-Check API from the project root (Windows PowerShell).
$ErrorActionPreference = "Stop"
if (Test-Path ".\.venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
Set-Location backend
python -m vcheck_api
