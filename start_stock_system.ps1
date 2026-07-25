$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$AppPy = Join-Path $ProjectDir "app.py"
$MySqlDir = "D:\dvptool\mysql"
$MySqlExe = Join-Path $MySqlDir "bin\mysqld.exe"
$MySqlConfig = Join-Path $MySqlDir "my.ini"
$Url = "http://127.0.0.1:5002"

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

Set-Location $ProjectDir

if (!(Test-PortListening -Port 3306)) {
  if (!(Test-Path $MySqlExe)) { throw "未找到 MySQL: $MySqlExe" }
  Start-Process `
    -FilePath $MySqlExe `
    -ArgumentList "--defaults-file=$MySqlConfig" `
    -WorkingDirectory (Join-Path $MySqlDir "bin") `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $ProjectDir "mysql_startup.log") `
    -RedirectStandardError (Join-Path $ProjectDir "mysql_startup_err.log")

  if (!(Wait-Port -Port 3306 -Seconds 25)) {
    throw "MySQL 启动超时，请查看 mysql_startup_err.log"
  }
}

if (!(Test-PortListening -Port 5002)) {
  if (!(Test-Path $PythonExe)) { throw "未找到 Python 虚拟环境: $PythonExe" }
  Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $AppPy `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Minimized `
    -RedirectStandardOutput (Join-Path $ProjectDir "server_startup.log") `
    -RedirectStandardError (Join-Path $ProjectDir "server_startup_err.log")

  if (!(Wait-Port -Port 5002 -Seconds 25)) {
    throw "股票分析系统启动超时，请查看 server_startup_err.log"
  }
}

Start-Process $Url
