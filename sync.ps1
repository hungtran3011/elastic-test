$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirement.txt

$paramElasticsearchUrl = $env:ELASTICSEARCH_URL
if (-not $paramElasticsearchUrl -or $paramElasticsearchUrl.Trim() -eq "") {
  $env:ELASTICSEARCH_URL = "http://localhost:9201"
}

# One-time sync of all story IDs in list.txt
python scraper.py
