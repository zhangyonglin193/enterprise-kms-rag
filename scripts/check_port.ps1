# KMS 端口排查脚本 (Windows PowerShell)
# 用法: .\check_port.ps1 [端口号]
# 不指定端口则扫描 KMS 端口范围 6342-6350

param(
    [Parameter(Mandatory=$false)]
    [int]$Port = 0
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KMS 端口排查工具 (Windows PowerShell)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Get-PortInfo {
    param([int]$TargetPort)
    
    $connections = Get-NetTCPConnection -LocalPort $TargetPort -ErrorAction SilentlyContinue
    
    if ($connections) {
        Write-Host "端口 $TargetPort 被占用:" -ForegroundColor Red
        foreach ($conn in $connections) {
            $process = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            $processName = if ($process) { $process.ProcessName } else { "Unknown" }
            $processPath = if ($process) { $process.Path } else { "N/A" }
            
            Write-Host "  PID: $($conn.OwningProcess)" -ForegroundColor Yellow
            Write-Host "  进程: $processName" -ForegroundColor Yellow
            Write-Host "  路径: $processPath" -ForegroundColor Yellow
            Write-Host "  状态: $($conn.State)" -ForegroundColor Yellow
            Write-Host "  本地地址: $($conn.LocalAddress):$($conn.LocalPort)" -ForegroundColor Yellow
            Write-Host "  远程地址: $($conn.RemoteAddress):$($conn.RemotePort)" -ForegroundColor Yellow
            Write-Host ""
        }
        return $true
    } else {
        Write-Host "端口 $TargetPort 空闲" -ForegroundColor Green
        return $false
    }
}

if ($Port -gt 0) {
    # 检查指定端口
    Get-PortInfo -TargetPort $Port
} else {
    # 扫描 KMS 端口范围
    Write-Host "扫描 KMS 端口范围 6341-6350..." -ForegroundColor White
    Write-Host ""
    
    $occupied = @()
    $free = @()
    
    for ($p = 6341; $p -le 6350; $p++) {
        $connections = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue
        if ($connections) {
            $process = Get-Process -Id $connections[0].OwningProcess -ErrorAction SilentlyContinue
            $processName = if ($process) { $process.ProcessName } else { "Unknown" }
            $occupied += "$p ($processName)"
        } else {
            $free += $p
        }
    }
    
    Write-Host "已占用端口:" -ForegroundColor Red
    if ($occupied.Count -eq 0) {
        Write-Host "  (无)" -ForegroundColor Gray
    } else {
        foreach ($item in $occupied) {
            Write-Host "  $item" -ForegroundColor Red
        }
    }
    
    Write-Host ""
    Write-Host "空闲端口:" -ForegroundColor Green
    if ($free.Count -eq 0) {
        Write-Host "  (无可用端口)" -ForegroundColor Red
    } else {
        foreach ($item in $free) {
            Write-Host "  $item" -ForegroundColor Green
        }
    }
    
    Write-Host ""
    Write-Host "端口说明:" -ForegroundColor Cyan
    Write-Host "  6341 - 原赛题问答服务 (app.api)" -ForegroundColor Gray
    Write-Host "  6342 - KMS 默认端口 (可通过 KMS_PORT 环境变量覆盖)" -ForegroundColor Gray
    Write-Host "  6343-6350 - KMS 备用端口" -ForegroundColor Gray
}

Write-Host ""
Write-Host "提示: 使用以下命令终止占用进程:" -ForegroundColor Cyan
Write-Host "  Stop-Process -Id <PID> -Force" -ForegroundColor Gray
Write-Host ""
