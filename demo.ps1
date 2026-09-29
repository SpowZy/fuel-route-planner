# One command: install, load the data, start the server, open the demo.
#   .\demo.ps1            uses port 8000
#   .\demo.ps1 -Port 8080
param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
}

uv sync
uv run python manage.py migrate --noinput
uv run python manage.py import_stations

$server = Start-Process uv -ArgumentList "run", "python", "manage.py", "runserver", "$Port", "--noreload" -PassThru -NoNewWindow
$url = "http://127.0.0.1:$Port"
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod "$url/api/v1/health/" | Out-Null; break } catch { Start-Sleep -Milliseconds 500 }
}

Start-Process $url
Write-Host ""
Write-Host "Demo:     $url"
Write-Host "API:      $url/api/v1/route/?start=New York, NY&finish=Los Angeles, CA"
Write-Host "Postman:  import postman/fuel-route-planner.postman_collection.json and run the collection"
Write-Host "Stop:     Ctrl+C"
Wait-Process -Id $server.Id
