$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalSettingsPath = Join-Path $ProjectDir "local_settings.json"
$LocalSettings = $null
if (Test-Path -LiteralPath $LocalSettingsPath) {
  try {
    $LocalSettings = Get-Content -LiteralPath $LocalSettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    Write-Warning "Failed to read local_settings.json: $($_.Exception.Message)"
  }
}

function Get-Setting {
  param(
    [string]$Name,
    [string]$EnvName,
    $Default = $null
  )
  $envValue = [Environment]::GetEnvironmentVariable($EnvName)
  if (![string]::IsNullOrWhiteSpace($envValue)) { return $envValue }
  if ($LocalSettings -and $LocalSettings.PSObject.Properties.Name -contains $Name) {
    $value = $LocalSettings.$Name
    if ($null -ne $value -and ![string]::IsNullOrWhiteSpace([string]$value)) { return $value }
  }
  return $Default
}

function Resolve-LocalPath {
  param([string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) { return $Path }
  if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
  return Join-Path $ProjectDir $Path
}

$Port = [int](Get-Setting "app_port" "STOCK_APP_PORT" 5002)
$Url = Get-Setting "app_url" "STOCK_APP_URL" "http://127.0.0.1:$Port"
$AppPy = Join-Path $ProjectDir "app.py"

$cloudSyncDir = Get-Setting "cloud_sync_dir" "STOCK_CLOUD_SYNC_DIR" $null
if ($cloudSyncDir) { $env:STOCK_CLOUD_SYNC_DIR = Resolve-LocalPath $cloudSyncDir }

$mysqlBinDir = Get-Setting "mysql_bin_dir" "MYSQL_BIN_DIR" $null
if ($mysqlBinDir) { $env:MYSQL_BIN_DIR = Resolve-LocalPath $mysqlBinDir }

$dbSettings = @{
  "db_host" = "STOCK_DB_HOST"
  "db_port" = "STOCK_DB_PORT"
  "db_user" = "STOCK_DB_USER"
  "db_password" = "STOCK_DB_PASSWORD"
  "db_name" = "STOCK_DB_NAME"
}
foreach ($item in $dbSettings.GetEnumerator()) {
  $value = Get-Setting $item.Key $item.Value $null
  if ($null -ne $value) { [Environment]::SetEnvironmentVariable($item.Value, [string]$value, "Process") }
}

$env:STOCK_APP_PORT = [string]$Port
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

function Test-PortListening {
  param([int]$Port)
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -ne $conn
}

function Wait-Port {
  param([int]$Port, [int]$Seconds)
  for ($i = 0; $i -lt $Seconds; $i++) {
    if (Test-PortListening -Port $Port) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

function Resolve-Python {
  $candidates = @()

  $configuredPython = Get-Setting "python_exe" "STOCK_PYTHON" $null
  if ($configuredPython) { $candidates += (Resolve-LocalPath $configuredPython) }

  $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) { $candidates += $venvPython }

  $pathPythons = Get-Command python -All -ErrorAction SilentlyContinue |
    Where-Object { $_.Source -and (Test-Path -LiteralPath $_.Source) } |
    Select-Object -ExpandProperty Source
  $candidates += $pathPythons

  $hermesPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $hermesPython) { $candidates += $hermesPython }

  $candidates = $candidates | Where-Object { $_ } | Select-Object -Unique
  foreach ($candidate in $candidates) {
    if (!(Test-Path -LiteralPath $candidate)) { continue }
    & $candidate -c "import flask, mysql.connector, requests, openai" 2>$null
    if ($LASTEXITCODE -eq 0) { return $candidate }
  }

  throw "No usable Python was found. Set python_exe in local_settings.json or install dependencies."
}

function Start-MySqlIfNeeded {
  if (Test-PortListening -Port 3306) { return }

  $serviceName = Get-Setting "mysql_service_name" "MYSQL_SERVICE_NAME" $null
  if ($serviceName) {
    Start-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (Wait-Port -Port 3306 -Seconds 25) { return }
  }

  $service = Get-CimInstance Win32_Service |
    Where-Object { $_.Name -match "mysql|maria" -or $_.DisplayName -match "mysql|maria" } |
    Select-Object -First 1

  if ($service) {
    Start-Service -Name $service.Name -ErrorAction SilentlyContinue
    if (Wait-Port -Port 3306 -Seconds 25) { return }
  }

  $mysqlDirs = @()
  $mysqlHome = Get-Setting "mysql_home" "MYSQL_HOME" $null
  if ($mysqlHome) { $mysqlDirs += (Resolve-LocalPath $mysqlHome) }
  if ($env:MYSQL_BIN_DIR) { $mysqlDirs += (Split-Path -Parent $env:MYSQL_BIN_DIR) }
  $mysqlDirs += @(
    "E:\MySQL",
    "D:\MySQL",
    "D:\mysql",
    "D:\dvptool\mysql",
    "C:\Program Files\MySQL\MySQL Server 8.4",
    "C:\Program Files\MySQL\MySQL Server 8.0"
  )

  foreach ($mysqlDir in ($mysqlDirs | Where-Object { $_ } | Select-Object -Unique)) {
    $mysqlExe = Join-Path $mysqlDir "bin\mysqld.exe"
    if (!(Test-Path -LiteralPath $mysqlExe)) { continue }

    $args = @()
    $myIni = Join-Path $mysqlDir "my.ini"
    $dataDir = Join-Path $mysqlDir "Data"
    if (Test-Path -LiteralPath $myIni) {
      $args += "--defaults-file=$myIni"
    } elseif (Test-Path -LiteralPath $dataDir) {
      $args += "--datadir=$dataDir"
    }

    Start-Process `
      -FilePath $mysqlExe `
      -ArgumentList $args `
      -WorkingDirectory (Join-Path $mysqlDir "bin") `
      -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $ProjectDir "mysql_startup.log") `
      -RedirectStandardError (Join-Path $ProjectDir "mysql_startup_err.log")

    if (Wait-Port -Port 3306 -Seconds 25) { return }
  }

  throw "MySQL is not listening on port 3306. Set mysql_service_name/mysql_home/mysql_bin_dir in local_settings.json."
}

Set-Location $ProjectDir

Start-MySqlIfNeeded

if (!(Test-PortListening -Port $Port)) {
  $pythonExe = Resolve-Python
  Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $AppPy `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Minimized `
    -RedirectStandardOutput (Join-Path $ProjectDir "server_startup.log") `
    -RedirectStandardError (Join-Path $ProjectDir "server_startup_err.log")

  if (!(Wait-Port -Port $Port -Seconds 25)) {
    throw "Stock analysis system startup timed out. Check server_startup_err.log."
  }
}

Start-Process $Url
