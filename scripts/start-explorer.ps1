[CmdletBinding(DefaultParameterSetName = 'Restart')]
param(
    [ValidateRange(1,65535)][int]$DashboardPort = 8502,
    [ValidateRange(1,65535)][int]$PostgresPort = 5434,
    [ValidatePattern('^[a-z0-9][a-z0-9_-]*$')][string]$ProjectName = 'wta-explorer',
    [string]$EnvFile,
    [string]$RepoRoot = $(if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }),
    [Parameter(Mandatory, ParameterSetName = 'Demo')][switch]$Demo,
    [Parameter(Mandatory, ParameterSetName = 'Manifest')][string]$RawManifest,
    [Parameter(Mandatory, ParameterSetName = 'Download')][string]$GtfsUrl,
    [Parameter(Mandatory, ParameterSetName = 'Manifest')]
    [Parameter(Mandatory, ParameterSetName = 'Download')]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$StartDate,
    [Parameter(Mandatory, ParameterSetName = 'Manifest')]
    [Parameter(Mandatory, ParameterSetName = 'Download')]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$EndDate
)
$ErrorActionPreference = 'Stop'
$mode = $PSCmdlet.ParameterSetName
if ($ProjectName -eq 'wta-demo') { throw 'Projekt wta-demo jest zarezerwowany dla starego demo; wybierz inny -ProjectName.' }
if ($DashboardPort -eq $PostgresPort) { throw 'Dashboard i PostgreSQL wymagają różnych portów.' }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'compose.yaml') -PathType Leaf)) { throw 'Brak compose.yaml w -RepoRoot.' }
if ($mode -in @('Manifest','Download')) {
    $first = [datetime]::ParseExact($StartDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    $last = [datetime]::ParseExact($EndDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    if ($last -lt $first -or ($last - $first).Days -ge 31) { throw 'Zakres analizy musi obejmować od 1 do 31 dni, od StartDate do EndDate.' }
}
if ($mode -eq 'Manifest') {
    $RawManifest = (Resolve-Path -LiteralPath $RawManifest).Path
    if (-not (Test-Path -LiteralPath $RawManifest -PathType Leaf)) { throw 'RawManifest musi wskazywać istniejący manifest raw.' }
}
if ($mode -eq 'Download') {
    $source = $null
    if (-not [Uri]::TryCreate($GtfsUrl, [UriKind]::Absolute, [ref]$source) -or
        $source.Scheme -ne 'https' -or $source.Host -ne 'open-data.cui.wroclaw.pl' -or
        $source.Port -ne 443 -or $source.UserInfo -or $source.Fragment -or $GtfsUrl -match '[\s\\]') {
        throw 'GtfsUrl musi być jawnym oficjalnym HTTPS URL open-data.cui.wroclaw.pl, bez loginu, fragmentu i spacji.'
    }
}
if (-not $EnvFile) { $EnvFile = if ($ProjectName -eq 'wta-explorer') { '.env.demo' } else { ".env.$ProjectName" } }
if (-not [IO.Path]::IsPathRooted($EnvFile)) { $EnvFile = Join-Path $RepoRoot $EnvFile }
$EnvFile = [IO.Path]::GetFullPath($EnvFile)
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($dockerCommand) { $dockerCommand.Source } else { 'C:\Users\jonat\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' }
if (-not $docker -or -not (Test-Path -LiteralPath $docker)) { throw 'Nie znaleziono Docker CLI. Sprawdź istniejący Docker Desktop; starter niczego nie instaluje.' }
$secretValues = @()
function Hide-Secrets([string]$Text) {
    foreach ($value in $script:secretValues) { if ($value) { $Text = $Text.Replace($value, '[REDACTED]') } }
    # Also protect credentials in native error messages containing DSNs or dotenv assignments.
    return $Text -replace '(?i)((?:password|POSTGRES_PASSWORD|WTA_LOADER_PASSWORD|WTA_READER_PASSWORD)\s*=\s*)(?:''[^'']*''|"[^"]*"|[^\s]+)', '$1[REDACTED]'
}
function Invoke-Engine {
    param([string[]]$Arguments, [switch]$Capture)
    # Windows PowerShell treats ordinary native stderr (including build progress) as errors.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& $script:docker --context desktop-linux @Arguments 2>&1)
        $nativeExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    $safeLines = @($lines | ForEach-Object { Hide-Secrets "$_" })
    if ($nativeExit -ne 0) {
        $tail = ($safeLines | Select-Object -Last 12) -join "`n"
        throw "Etap Docker zakończony błędem ($nativeExit).`n$tail"
    }
    if ($Capture) { return $safeLines }
    foreach ($line in $safeLines) { Write-Host $line }
}
function Invoke-Compose {
    param([string[]]$Arguments, [switch]$Capture)
    Invoke-Engine -Arguments ($script:composeArgs + $Arguments) -Capture:$Capture
}
function Invoke-PipelineJson([string[]]$Arguments) {
    $lines = @(Invoke-Compose -Arguments (@('run','--rm','pipeline') + $Arguments) -Capture)
    $jsonLines = @($lines | Where-Object { $_.TrimStart().StartsWith('{') })
    if ($jsonLines.Count -ne 1) { throw 'CLI nie zwróciło jednoznacznego wyniku JSON; nie wybrano manifestu ani datasetu na podstawie nazw katalogów.' }
    return $jsonLines[0] | ConvertFrom-Json
}
$previous = @{}
foreach ($key in @('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','POSTGRES_PORT','DASHBOARD_PORT','RAW_DIR','SILVER_DIR','POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD','COMPOSE_PROFILES')) {
    $previous[$key] = [Environment]::GetEnvironmentVariable($key,'Process')
}
try {
    foreach ($key in @('DOCKER_HOST','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH','POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD','COMPOSE_PROFILES')) {
        [Environment]::SetEnvironmentVariable($key,$null,'Process')
    }
    $env:DOCKER_CONTEXT = 'desktop-linux'
    $endpoint = (Invoke-Engine -Arguments @('context','inspect','desktop-linux','--format','{{.Endpoints.docker.Host}}') -Capture) -join ''
    if ($endpoint -notmatch '^(npipe:////\./pipe/|unix:///)' -or $endpoint -match '[\r\n]') { throw 'Kontekst desktop-linux nie wskazuje lokalnego silnika; zdalny Docker nie został użyty.' }
    $server = (Invoke-Engine -Arguments @('info','--format','{{.OSType}}/{{.Architecture}}') -Capture) -join ''
    if ($server -notmatch '^linux/') { throw 'Explorer wymaga dostępnego lokalnego silnika Linux Docker Desktop.' }
    Invoke-Engine -Arguments @('compose','version','--short')
    $volumes = @(Invoke-Engine -Arguments @('volume','ls','--filter',"label=com.docker.compose.project=$ProjectName",'--format','{{.Name}}') -Capture)
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        if ($volumes.Count) { throw 'Istnieją wolumeny tego projektu, ale brak pliku konfiguracji. Przywróć jego hasła; niczego nie nadpisano.' }
        if ($mode -eq 'Restart') { throw 'Brak konfiguracji istniejącej instancji. Użyj -Demo albo jawnego -RawManifest/-GtfsUrl, aby przygotować świeże środowisko.' }
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $content = foreach ($key in @('POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD')) {
                $bytes = New-Object byte[] 32
                $random.GetBytes($bytes)
                "$key=$(([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant())"
            }
        } finally { $random.Dispose() }
        # CreateNew never overwrites credentials, including if another process created the file.
        $stream = [IO.File]::Open($EnvFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($content -join "`n") + "`n")
            $stream.Write($bytes,0,$bytes.Length)
        } finally { $stream.Dispose() }
    }
    $settings = @{}
    foreach ($line in [IO.File]::ReadAllLines($EnvFile)) {
        if ($line -match '^\s*(POSTGRES_PASSWORD|WTA_LOADER_PASSWORD|WTA_READER_PASSWORD)\s*=(.*)$') {
            $value = $Matches[2].Trim()
            $secretValues += $value
            $value = $value.Trim('"').Trim("'")
            $secretValues += $value
            $settings[$Matches[1]] = $value
        }
    }
    foreach ($key in @('POSTGRES_PASSWORD','WTA_LOADER_PASSWORD','WTA_READER_PASSWORD')) {
        if (-not $settings[$key]) { throw "Konfiguracja nie zawiera niepustego $key; pliku nie zmieniono." }
    }
    if ($mode -eq 'Restart') {
        $databaseVolumes = @(Invoke-Engine -Arguments @('volume','ls','--filter',"label=com.docker.compose.project=$ProjectName",'--filter','label=com.docker.compose.volume=postgres_data','--format','{{.Name}}') -Capture)
        if (-not $databaseVolumes.Count) { throw 'Brak własnego wolumenu postgres_data istniejącej instancji. Wybierz jawnie -Demo albo źródło danych; restart nie tworzy pustej bazy.' }
    }
    $rawDir = if ($mode -eq 'Manifest') { Split-Path -Parent $RawManifest } else { Join-Path $RepoRoot 'data/raw' }
    $silverDir = Join-Path $RepoRoot 'data/silver'
    foreach ($directory in @($rawDir,$silverDir)) { New-Item -ItemType Directory -Force -Path $directory | Out-Null }
    $env:RAW_DIR = $rawDir.Replace('\','/')
    $env:SILVER_DIR = $silverDir.Replace('\','/')
    $env:DASHBOARD_PORT = "$DashboardPort"
    $env:POSTGRES_PORT = "$PostgresPort"
    $composeArgs = @('compose','--project-name',$ProjectName,'--project-directory',$RepoRoot,'--env-file',$EnvFile,'-f',(Join-Path $RepoRoot 'compose.yaml'))
    foreach ($item in @(@('dashboard',$DashboardPort,8501),@('postgres',$PostgresPort,5432))) {
        $ids = @(Invoke-Compose -Arguments @('ps','--status','running','-q',$item[0]) -Capture)
        $ownsPort = $false
        if ($ids.Count) {
            $published = (Invoke-Compose -Arguments @('port',$item[0],"$($item[2])") -Capture) -join "`n"
            $ownsPort = $published -match (':'+$item[1]+'(?:\r?\n|$)')
        }
        if (-not $ownsPort) {
            $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,[int]$item[1])
            try { $listener.Start() } catch { throw "Port $($item[1]) jest zajęty. Wybierz -DashboardPort/-PostgresPort; żaden obcy proces nie został zatrzymany." }
            finally { $listener.Stop() }
        }
    }
    if ($mode -eq 'Restart') {
        Invoke-Compose -Arguments @('build','dashboard')
    } else {
        Invoke-Compose -Arguments @('--profile','tools','build','initializer','pipeline','dashboard')
    }
    Invoke-Compose -Arguments @('up','-d','--wait','postgres')
    if ($mode -ne 'Restart') {
        Invoke-Compose -Arguments @('run','--rm','initializer')
        if ($mode -eq 'Demo') {
            $result = Invoke-PipelineJson -Arguments @('demo','--output-root','/work/data','--json')
        } else {
            if ($mode -eq 'Manifest') {
                $containerManifest = '/input/raw/' + (Split-Path -Leaf $RawManifest)
            } else {
                $download = @(Invoke-Compose -Arguments @('run','--rm','--entrypoint','python','pipeline','-m','wroclaw_transit_analytics.gtfs','--url',$GtfsUrl,'--output-dir','/work/data/raw/gtfs') -Capture)
                $manifestLines = @($download | Where-Object { $_ -match '^Manifest: (.+)$' })
                if ($manifestLines.Count -ne 1) { throw 'Pobranie nie zwróciło jednej ścieżki manifestu; nie wyszukano najnowszego katalogu.' }
                $containerManifest = $manifestLines[0].Substring('Manifest: '.Length)
            }
            $result = Invoke-PipelineJson -Arguments @('run','--raw-manifest',$containerManifest,'--start-date',$StartDate,'--end-date',$EndDate,'--output-root','/work/data','--json')
        }
        if ($result.status -ne 'PASSED' -or -not $result.raw_manifest -or -not $result.dataset_id) { throw 'Pipeline nie potwierdził przygotowania, ładowania i analizy źródła.' }
        $geometry = Invoke-PipelineJson -Arguments @('explorer-import','--raw-manifest',$result.raw_manifest,'--json')
        if ($geometry.dataset_id -ne $result.dataset_id -or $geometry.status -notin @('IMPORTED','ALREADY_IMPORTED')) { throw 'Nie potwierdzono geometrii tego samego datasetu.' }
        Write-Output "Pipeline: $($result.status); dataset: $($result.dataset_id); geometria: $($geometry.geometry_status)."
        if ($mode -eq 'Demo') { Write-Output 'DANE SYNTETYCZNE — nie rozkład Wrocławia.' }
    }
    Invoke-Compose -Arguments @('up','-d','--wait','--no-deps','dashboard')
    $url = "http://127.0.0.1:$DashboardPort"
    $response = Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -ne 200) { throw 'Usługa dashboardu nie potwierdziła gotowości.' }
    Write-Output "Explorer uruchomiony: $url"
    Write-Output 'Gotowość HTTP potwierdzona. Odbiór interfejsu wymaga sprawdzenia mapy, kursu i filtrów w przeglądarce.'
} finally {
    foreach ($key in $previous.Keys) { [Environment]::SetEnvironmentVariable($key,$previous[$key],'Process') }
}
