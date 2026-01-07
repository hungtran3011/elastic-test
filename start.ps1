param(
  [switch]$SkipDocker,
  [int]$Port = 8000,
  [string]$ElasticsearchUrl = "http://localhost:9201"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirement.txt

$env:ELASTICSEARCH_URL = $ElasticsearchUrl

if (-not $SkipDocker) {
  docker compose up -d --build
}

python -m uvicorn web_app:app --host 0.0.0.0 --port $Port
