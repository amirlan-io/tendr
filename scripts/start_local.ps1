# Run from Windows PowerShell: powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

foreach ($Command in @("node", "npm.cmd", "docker")) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Missing $Command. Install Node.js LTS and Docker Desktop, then open a new PowerShell window."
    }
}
$NodeVersion = [version]((& node -p "process.versions.node").Trim())
if ($NodeVersion -lt [version]"22.12.0") {
    throw "Node.js 22.12 or newer is required. Install the current LTS release."
}
function Test-DockerEngine {
    # Windows PowerShell 5.1 turns native stderr into NativeCommandError under Stop.
    # A missing engine is an expected startup state, not an unhandled exception.
    try {
        & docker info *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
if (-not (Test-DockerEngine)) {
    $DesktopPath = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $DesktopPath)) {
        throw "Open Docker Desktop manually and wait for Engine running, then run this script again."
    }
    Write-Host "Starting Docker Desktop. Complete any first-run prompts in its window."
    Start-Process -FilePath $DesktopPath
    $EngineReady = $false
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        if (Test-DockerEngine) { $EngineReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $EngineReady) {
        throw "Docker engine is not ready. Check the Docker Desktop window for WSL/virtualization errors and use Linux containers. Run this script again after Engine running."
    }
}
function Find-FreeLocalPort([int]$FirstPort) {
    for ($Candidate = $FirstPort; $Candidate -lt $FirstPort + 20; $Candidate++) {
        if (-not (Get-NetTCPConnection -LocalPort $Candidate -State Listen -ErrorAction SilentlyContinue)) {
            return $Candidate
        }
    }
    throw "No free local port found starting at $FirstPort."
}
$ApiPort = Find-FreeLocalPort 8000
$WebPort = Find-FreeLocalPort 5173
$env:TENDR_LOCAL_API_PORT = [string]$ApiPort
$env:TENDR_LOCAL_WEB_PORT = [string]$WebPort
# The new frontend terminal inherits this value for its Vite API proxy.
$env:TENDR_API_PORT = [string]$ApiPort
$ApiUrl = "http://127.0.0.1:$ApiPort"
$WebUrl = "http://127.0.0.1:$WebPort"
Write-Host "Selected API port $ApiPort and frontend port $WebPort. Existing processes are left running."


Push-Location (Join-Path $ProjectRoot "web")
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
} finally { Pop-Location }

& docker compose -f infra/docker-compose.local.yml up -d --build
if ($LASTEXITCODE -ne 0) { throw "Docker startup failed. Read the error above; existing data was not deleted." }
$Ready = $false
for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
    try {
        $Response = Invoke-RestMethod "$ApiUrl/api/health/live" -TimeoutSec 2
        if ($Response.status -eq "ok") { $Ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $Ready) {
    & docker compose -f infra/docker-compose.local.yml logs --tail 40 api migrate
    throw "API is not ready. Read the container logs above."
}
$WebDirectory = Join-Path $ProjectRoot "web"
Start-Process -FilePath "cmd.exe" -ArgumentList @("/k", ('cd /d "{0}" && npm run dev -- --host 127.0.0.1 --port {1} --strictPort' -f $WebDirectory, $WebPort))
$WebReady = $false
for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
    try {
        $Response = Invoke-WebRequest "$WebUrl/" -UseBasicParsing -TimeoutSec 2
        if ($Response.StatusCode -eq 200) { $WebReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
if (-not $WebReady) { throw "Frontend did not start. Read the separate terminal window." }
Start-Process "$WebUrl/#pricing"
Write-Host "Frontend: $WebUrl/#pricing"
Write-Host "API: $ApiUrl/api/health/live"
Write-Host "Keep the frontend terminal open. Stop backend: docker compose -f infra/docker-compose.local.yml down"
