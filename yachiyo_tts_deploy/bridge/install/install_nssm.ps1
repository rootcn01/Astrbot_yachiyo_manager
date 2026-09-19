# install_nssm.ps1 — 用 NSSM 把 yachiyo-tts-bridge 装成 Windows 服务（方案一）
# 用法: powershell -ExecutionPolicy Bypass -File install_nssm.ps1 [-NssmPath C:\Tools\nssm.exe] [-PythonExe python.exe]
# 行为: 1) 若 E:/DATA/YachiyoRuntime/bridge/config.json 不存在则从 config.example.json 生成并提示手填 token
#       2) nssm install YachiyoBridge "<python>" "<本目录>\bridge.py" --config <config>
#       3) 配置 AppStdout/AppStderr 日志 + 崩溃自动重启，并启动服务
param(
    [string]$NssmPath = "C:\Tools\nssm.exe",
    [string]$PythonExe = "python.exe",
    [string]$ConfigDir = "E:/DATA/YachiyoRuntime/bridge",
    [string]$ServiceName = "YachiyoBridge"
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoBridge = Split-Path -Parent $Here
$ConfigPath = Join-Path $ConfigDir "config.json"

# 1) 生成真实 config（若不存在）
if (-not (Test-Path $ConfigPath)) {
    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
    Copy-Item (Join-Path $RepoBridge "config.example.json") $ConfigPath
    Write-Warning "已生成 $ConfigPath —— 请先手填 token 字段（当前为 CHANGE_ME），bridge 检测到占位值会拒绝启动。"
    Write-Host "编辑完成后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}
if ((Get-Content $ConfigPath -Raw) -match "CHANGE_ME") {
    Write-Warning "$ConfigPath 仍有 CHANGE_ME 占位（token 等），请手填后再安装服务。"
    exit 1
}

# 2) 安装服务
if (-not (Test-Path $NssmPath)) { Write-Error "未找到 nssm: $NssmPath（先安装 https://nssm.cc）"; exit 1 }
& $NssmPath stop $ServiceName 2>$null | Out-Null
& $NssmPath remove $ServiceName confirm 2>$null | Out-Null
$BridgePy = Join-Path $RepoBridge "bridge.py"
& $NssmPath install $ServiceName $PythonExe "`"$BridgePy`" --config `"$ConfigPath`""
& $NssmPath set $ServiceName AppDirectory $ConfigDir
& $NssmPath set $ServiceName AppStdout (Join-Path $ConfigDir "bridge_service.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $ConfigDir "bridge_service.log")
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 10485760
& $NssmPath set $ServiceName AppRotate 5
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppExit Default Restart
& $NssmPath set $ServiceName AppRestartDelay 10000
& $NssmPath start $ServiceName
Write-Host "服务 $ServiceName 已安装并启动。日志: $ConfigDir\bridge_service.log" -ForegroundColor Green
Write-Host "验证: curl http://127.0.0.1:9881/health"
