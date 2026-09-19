# install_task.ps1 — 计划任务方式守护 yachiyo-tts-bridge（方案二，免 NSSM）
# 用法: powershell -ExecutionPolicy Bypass -File install_task.ps1 [-PythonExe python.exe]
# 行为: 1) 若 E:/DATA/YachiyoRuntime/bridge/config.json 不存在则从 config.example.json 生成并提示手填 token
#       2) 注册开机自启计划任务 YachiyoBridge：每小时触发 + 失败后每 60s 重试（任务不存在时重启 bridge.py）
# 注: 计划任务无崩溃即重启语义，进程退出后最长 60s 由下一轮触发拉起；要秒级守护请用 install_nssm.ps1
param(
    [string]$PythonExe = "python.exe",
    [string]$ConfigDir = "E:/DATA/YachiyoRuntime/bridge",
    [string]$TaskName = "YachiyoBridge"
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
    Write-Warning "$ConfigPath 仍有 CHANGE_ME 占位（token 等），请手填后再安装任务。"
    exit 1
}

# 2) 注册计划任务：开机启动 + 每小时兜底触发（New-Item 不覆盖已跑进程则重启）
$BridgePy = Join-Path $RepoBridge "bridge.py"
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$BridgePy`" --config `"$ConfigPath`"" -WorkingDirectory $ConfigDir
$TriggerBoot = New-ScheduledTaskTrigger -AtStartup
$TriggerHourly = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 60 -RestartInterval (New-TimeSpan -Seconds 60) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($TriggerBoot, $TriggerHourly) -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "计划任务 $TaskName 已注册并启动。" -ForegroundColor Green
Write-Host "重复触发的重启保护: bridge.py 绑定 127.0.0.1:9881，已跑实例会使新实例端口冲突退出，不影响服务。"
Write-Host "验证: curl http://127.0.0.1:9881/health"
