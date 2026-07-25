param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SettingsPath = Join-Path $ProjectDir "local_settings.json"
$ExamplePath = Join-Path $ProjectDir "local_settings.example.json"

function Read-JsonFile {
  param([string]$Path)
  if (!(Test-Path -LiteralPath $Path)) { return $null }
  try {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    Write-Warning "Cannot read ${Path}: $($_.Exception.Message)"
    return $null
  }
}

function Get-Prop {
  param($Object, [string]$Name)
  if ($null -eq $Object) { return $null }
  if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
  return $null
}

function Choose-Value {
  param($Existing, $Detected, $Default)
  if (!$Force -and $null -ne $Existing -and ![string]::IsNullOrWhiteSpace([string]$Existing)) { return $Existing }
  if ($null -ne $Detected -and ![string]::IsNullOrWhiteSpace([string]$Detected)) { return $Detected }
  return $Default
}

function Test-PythonDeps {
  param([string]$PythonExe)
  if ([string]::IsNullOrWhiteSpace($PythonExe) -or !(Test-Path -LiteralPath $PythonExe)) { return $false }
  & $PythonExe -c "import flask, mysql.connector, requests, openai" 2>$null
  return $LASTEXITCODE -eq 0
}

function Find-PythonExe {
  $candidates = @()

  $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
  if (Test-Path -LiteralPath $venvPython) { $candidates += $venvPython }

  $pathPythons = Get-Command python -All -ErrorAction SilentlyContinue |
    Where-Object { $_.Source -and (Test-Path -LiteralPath $_.Source) } |
    Select-Object -ExpandProperty Source
  $candidates += $pathPythons

  if ($env:LOCALAPPDATA) {
    $hermesPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $hermesPython) { $candidates += $hermesPython }
  }

  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if (Test-PythonDeps $candidate) {
      if ($candidate.StartsWith($ProjectDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $candidate.Substring($ProjectDir.Length).TrimStart("\")
      }
      return $candidate
    }
  }

  return $null
}

function Get-MySqlExeFromService {
  param($Service)
  if ($null -eq $Service -or [string]::IsNullOrWhiteSpace($Service.PathName)) { return $null }
  $match = [regex]::Match($Service.PathName, '"?([^"]*mysqld\.exe)"?', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
  if ($match.Success -and (Test-Path -LiteralPath $match.Groups[1].Value)) {
    return $match.Groups[1].Value
  }
  return $null
}

function Find-MySqlInfo {
  $service = Get-CimInstance Win32_Service |
    Where-Object { $_.Name -match "mysql|maria" -or $_.DisplayName -match "mysql|maria" } |
    Sort-Object @{ Expression = { if ($_.State -eq "Running") { 0 } else { 1 } } }, Name |
    Select-Object -First 1

  $binDir = $null
  $mysqlHome = $null

  $serviceExe = Get-MySqlExeFromService $service
  if ($serviceExe) {
    $binDir = Split-Path -Parent $serviceExe
    $mysqlHome = Split-Path -Parent $binDir
  }

  if (!$binDir) {
    $mysqlCmd = Get-Command mysql.exe -ErrorAction SilentlyContinue
    if ($mysqlCmd -and $mysqlCmd.Source) {
      $binDir = Split-Path -Parent $mysqlCmd.Source
      $mysqlHome = Split-Path -Parent $binDir
    }
  }

  if (!$binDir) {
    $commonHomes = @(
      "E:\MySQL",
      "D:\MySQL",
      "D:\mysql",
      "D:\dvptool\mysql",
      "C:\Program Files\MySQL\MySQL Server 8.4",
      "C:\Program Files\MySQL\MySQL Server 8.0"
    )
    foreach ($home in $commonHomes) {
      $mysqlExe = Join-Path $home "bin\mysql.exe"
      if (Test-Path -LiteralPath $mysqlExe) {
        $binDir = Split-Path -Parent $mysqlExe
        $mysqlHome = $home
        break
      }
    }
  }

  return [PSCustomObject]@{
    ServiceName = if ($service) { $service.Name } else { $null }
    Home = $mysqlHome
    BinDir = $binDir
  }
}

function Test-DbPassword {
  param([string]$MysqlExe, [string]$Password)
  if ([string]::IsNullOrWhiteSpace($MysqlExe) -or !(Test-Path -LiteralPath $MysqlExe)) { return $false }
  $oldErrorActionPreference = $ErrorActionPreference
  $oldNativePreference = $null
  if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $oldNativePreference = $Global:PSNativeCommandUseErrorActionPreference
    $Global:PSNativeCommandUseErrorActionPreference = $false
  }
  try {
    $ErrorActionPreference = "Continue"
    & $MysqlExe `
      "--host=127.0.0.1" `
      "--port=3306" `
      "--user=root" `
      "--password=$Password" `
      "--default-character-set=utf8mb4" `
      "-e" "SELECT 1" 1>$null 2>$null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $oldErrorActionPreference
    if ($null -ne $oldNativePreference) {
      $Global:PSNativeCommandUseErrorActionPreference = $oldNativePreference
    }
  }
}

function Find-DbPassword {
  param([string]$MysqlBinDir)
  $mysqlExe = if ($MysqlBinDir) { Join-Path $MysqlBinDir "mysql.exe" } else { $null }
  foreach ($password in @("", "root")) {
    if (Test-DbPassword $mysqlExe $password) { return $password }
  }
  return $null
}

function Find-CloudSyncDir {
  $envDir = [Environment]::GetEnvironmentVariable("STOCK_CLOUD_SYNC_DIR")
  if (![string]::IsNullOrWhiteSpace($envDir)) { return $envDir }

  foreach ($dropboxRoot in @(
    (Join-Path $env:USERPROFILE "Dropbox"),
    "D:\Dropbox",
    "E:\Dropbox",
    "F:\Dropbox"
  )) {
    if (![string]::IsNullOrWhiteSpace($dropboxRoot) -and (Test-Path -LiteralPath $dropboxRoot)) {
      $target = Join-Path $dropboxRoot "stock-cloud-sync"
      New-Item -ItemType Directory -Force -Path $target | Out-Null
      return $target
    }
  }

  foreach ($oneDriveEnv in @("OneDrive", "OneDriveConsumer", "OneDriveCommercial")) {
    $oneDriveRoot = [Environment]::GetEnvironmentVariable($oneDriveEnv)
    if (![string]::IsNullOrWhiteSpace($oneDriveRoot) -and (Test-Path -LiteralPath $oneDriveRoot)) {
      $target = Join-Path $oneDriveRoot "stock-cloud-sync"
      New-Item -ItemType Directory -Force -Path $target | Out-Null
      return $target
    }
  }

  foreach ($drive in @("D", "E", "F", "C")) {
    $candidate = "${drive}:\stock-cloud-sync"
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }

  $driveInfo = Get-PSDrive -PSProvider FileSystem |
    Where-Object { $_.Name -ne "C" -and $_.Free -gt 1GB } |
    Sort-Object Name |
    Select-Object -First 1
  $target = if ($driveInfo) { "$($driveInfo.Name):\stock-cloud-sync" } else { Join-Path $ProjectDir "stock-cloud-sync" }
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  return $target
}

$existing = Read-JsonFile $SettingsPath
$example = Read-JsonFile $ExamplePath
$mysql = Find-MySqlInfo
$pythonExe = Find-PythonExe
$cloudSyncDir = Find-CloudSyncDir
$dbPassword = Find-DbPassword $mysql.BinDir

$settings = [ordered]@{
  app_port = [int](Choose-Value (Get-Prop $existing "app_port") $null (Choose-Value (Get-Prop $example "app_port") $null 5002))
  app_url = Choose-Value (Get-Prop $existing "app_url") $null (Choose-Value (Get-Prop $example "app_url") $null "http://127.0.0.1:5002")
  cloud_sync_dir = Choose-Value (Get-Prop $existing "cloud_sync_dir") $cloudSyncDir "D:\stock-cloud-sync"
  mysql_service_name = Choose-Value (Get-Prop $existing "mysql_service_name") $mysql.ServiceName "MySQL"
  mysql_home = Choose-Value (Get-Prop $existing "mysql_home") $mysql.Home ""
  mysql_bin_dir = Choose-Value (Get-Prop $existing "mysql_bin_dir") $mysql.BinDir ""
  python_exe = Choose-Value (Get-Prop $existing "python_exe") $pythonExe ""
  db_host = Choose-Value (Get-Prop $existing "db_host") $null "127.0.0.1"
  db_port = [int](Choose-Value (Get-Prop $existing "db_port") $null 3306)
  db_user = Choose-Value (Get-Prop $existing "db_user") $null "root"
  db_password = Choose-Value (Get-Prop $existing "db_password") $dbPassword ""
  db_name = Choose-Value (Get-Prop $existing "db_name") $null "stock_analysis"
}

$json = $settings | ConvertTo-Json -Depth 4
$json | Set-Content -LiteralPath $SettingsPath -Encoding UTF8

Write-Host ""
Write-Host "local_settings.json is ready:" -ForegroundColor Green
Write-Host "  $SettingsPath"
Write-Host ""
Write-Host "Detected settings:"
Write-Host "  Python:     $($settings.python_exe)"
Write-Host "  MySQL svc:  $($settings.mysql_service_name)"
Write-Host "  MySQL bin:  $($settings.mysql_bin_dir)"
Write-Host "  Cloud dir:  $($settings.cloud_sync_dir)"
Write-Host "  DB user:    $($settings.db_user)"
Write-Host "  DB pass:    $(if ([string]::IsNullOrEmpty($settings.db_password)) { '<empty>' } else { '<set>' })"
Write-Host ""
Write-Host "Next step: run stock.bat or start_stock_system.ps1."
