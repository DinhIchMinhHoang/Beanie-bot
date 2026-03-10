# Local deployment script - Run this from your Windows machine
# Deploys Beanie Bot to Azure VM using SCP/SSH

param(
    [string]$VMHost = "20.6.132.164",
    [string]$VMUser = "Bean"
)

Write-Host "==================================" -ForegroundColor Cyan
Write-Host "Beanie Bot Deployment to Azure VM" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

$LocalPath = "D:\00_Workspace\AI_Lab\Discord_Bots\beanie-bot"
$RemotePath = "~/beanie-bot"

# Files to deploy
$FilesToDeploy = @(
    "main.py",
    "requirements.txt",
    "birthdays.json",
    "competitors.json",
    "entry_settings.json",
    "state.json",
    "voice_stats.json"
)

# Folders to deploy
$FoldersToSync = @(
    "sfx"
)

Write-Host "`n1. Uploading files to VM..." -ForegroundColor Yellow

# Upload individual files
foreach ($file in $FilesToDeploy) {
    Write-Host "   Uploading $file..." -ForegroundColor Gray
    scp "$LocalPath\$file" "${VMUser}@${VMHost}:${RemotePath}/"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   Failed to upload $file" -ForegroundColor Red
        exit 1
    }
}

# Upload folders
foreach ($folder in $FoldersToSync) {
    Write-Host "   Uploading $folder/ folder..." -ForegroundColor Gray
    scp -r "$LocalPath\$folder" "${VMUser}@${VMHost}:${RemotePath}/"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   Failed to upload $folder/" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n2. Running deployment script on VM..." -ForegroundColor Yellow
ssh "${VMUser}@${VMHost}" "bash ~/beanie-bot/deploy.sh"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n==================================" -ForegroundColor Green
    Write-Host "Deployment completed successfully!" -ForegroundColor Green
    Write-Host "==================================" -ForegroundColor Green
} else {
    Write-Host "`n==================================" -ForegroundColor Red
    Write-Host "Deployment failed!" -ForegroundColor Red
    Write-Host "==================================" -ForegroundColor Red
    exit 1
}
