param(
    [ValidateRange(1,65535)][int]$DashboardPort = 8501,
    [ValidateRange(1,65535)][int]$PostgresPort = 5433,
    [string]$RepoRoot = $(if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path })
)
$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Brak Docker CLI lub daemona. Uruchom istniejący Docker Desktop i ponów start demo.'
}
& docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
$nativeExit = $LASTEXITCODE
if ($nativeExit -ne 0) { throw 'Brak Docker CLI lub daemona. Uruchom istniejący Docker Desktop i ponów start demo.' }
& docker compose version --short | Out-Null
$nativeExit = $LASTEXITCODE
if ($nativeExit -ne 0) { throw 'Brak działającego Docker Compose.' }
$config = Join-Path $RepoRoot '.env.demo'
if (-not (Test-Path -LiteralPath $config)) {
    # Refuse to invent credentials for an existing volume whose configuration was lost.
    $volumes = & docker volume ls --filter 'label=com.docker.compose.project=wta-demo' --format '{{.Name}}'
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) { throw 'Nie można sprawdzić wolumenów demo.' }
    if ($volumes) { throw 'Istnieje wolumen wta-demo, ale brak .env.demo. Przywróć jego konfigurację; haseł nie zmieniono.' }
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $values = @{}
    foreach ($key in @('POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD')) {
        $bytes = New-Object byte[] 32
        $random.GetBytes($bytes)
        $values[$key] = ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
    }
    $random.Dispose()
    $content = ($values.Keys | Sort-Object | ForEach-Object { "$_=$($values[$_])" }) -join "`n"
    [System.IO.File]::WriteAllText($config, $content + "`n", [System.Text.UTF8Encoding]::new($false))
}
$inputDir = Join-Path $RepoRoot 'data/silver'
New-Item -ItemType Directory -Force -Path $inputDir | Out-Null
$composeArgs = @('compose','--project-name','wta-demo','--project-directory',$RepoRoot,'--env-file',$config,'-f',(Join-Path $RepoRoot 'compose.yaml'))
# Explicit task environment overrides .env and is restored when the script exits.
$previous = @{}
foreach ($key in @('POSTGRES_PORT','DASHBOARD_PORT','SILVER_DIR','POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD','COMPOSE_PROFILES')) {
    $previous[$key] = [Environment]::GetEnvironmentVariable($key,'Process')
}
function Invoke-DemoDocker {
    param([string[]]$Arguments)
    & docker @composeArgs @Arguments
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) { throw "Etap Docker zakończony błędem ($nativeExit)." }
}
try {
    foreach ($key in @('POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD','COMPOSE_PROFILES')) {
        [Environment]::SetEnvironmentVariable($key,$null,'Process')
    }
    $env:POSTGRES_PORT = "$PostgresPort"
    $env:DASHBOARD_PORT = "$DashboardPort"
    $env:SILVER_DIR = $inputDir.Replace('\','/')
    foreach ($item in @(@('dashboard',$DashboardPort),@('postgres',$PostgresPort))) {
        $service = $item[0]
        $serviceIds = & docker @composeArgs ps --status running -q $service
        $nativeExit = $LASTEXITCODE
        if ($nativeExit -ne 0) { throw 'Nie można sprawdzić usług demo.' }
        $ownsPort = $false
        if ($serviceIds) {
            $containerPort = if ($service -eq 'postgres') { 5432 } else { 8501 }
            $published = & docker @composeArgs port $service $containerPort
            $nativeExit = $LASTEXITCODE
            if ($nativeExit -ne 0) { throw 'Nie można sprawdzić portu usługi demo.' }
            $ownsPort = "$published" -match (':' + $item[1] + '$')
        }
        if (-not $ownsPort) {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,[int]$item[1])
            try { $listener.Start() } catch { throw "Port $($item[1]) jest zajęty. Wybierz -DashboardPort lub -PostgresPort; żaden proces nie został zatrzymany." }
            finally { $listener.Stop() }
        }
    }
    Invoke-DemoDocker -Arguments @('--profile','tools','build')
    Invoke-DemoDocker -Arguments @('up','-d','--wait','postgres')
    Invoke-DemoDocker -Arguments @('run','--rm','initializer')
    Invoke-DemoDocker -Arguments @('run','--rm','pipeline','demo','--json')
    Invoke-DemoDocker -Arguments @('up','-d','--wait','dashboard')
    $url = "http://127.0.0.1:$DashboardPort"
    $response = Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -ne 200) { throw 'Dashboard nie jest gotowy.' }
    Write-Output "Demo gotowe: $url"
    Write-Output 'DANE SYNTETYCZNE — nie rozkład Wrocławia'
} finally {
    foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key,$previous[$key],'Process') }
}
