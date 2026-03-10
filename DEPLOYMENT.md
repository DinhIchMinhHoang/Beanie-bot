# CI/CD Deployment Setup

## Overview
This project uses GitHub Actions to automatically deploy the Beanie Bot to your Azure VM whenever you push changes to the `main` branch.

## Setup Instructions

### 1. Initialize Git Repository (if not already done)
```powershell
cd D:\00_Workspace\AI_Lab\Discord_Bots\beanie-bot
git init
git add .
git commit -m "Initial commit"
```

### 2. Create GitHub Repository
1. Go to https://github.com/new
2. Create a new repository (e.g., `beanie-bot`)
3. **Do NOT** add README, .gitignore, or license (we already have these)
4. Click **Create repository**

### 3. Push to GitHub
```powershell
git remote add origin https://github.com/YOUR_USERNAME/beanie-bot.git
git branch -M main
git push -u origin main
```

### 4. Configure GitHub Secrets
Go to your repository on GitHub → **Settings** → **Secrets and variables** → **Actions**

Click **New repository secret** and add these three secrets:

| **Name** | **Value** |
|----------|-----------|
| `VM_HOST` | `20.6.132.164` |
| `VM_USERNAME` | `Bean` |
| `VM_PASSWORD` | Your VM password |

### 5. Upload Deployment Script to VM

First, upload `deploy.sh` to your VM:

```powershell
scp deploy.sh Bean@20.6.132.164:~/beanie-bot/
```

Then make it executable on the VM:
```bash
ssh Bean@20.6.132.164
cd ~/beanie-bot
chmod +x deploy.sh
```

### 6. Test Deployment

**Option A: Push to GitHub** (triggers automatic deployment)
```powershell
git add .
git commit -m "Update bot"
git push
```

**Option B: Manual trigger from GitHub**
- Go to your repository → **Actions** tab
- Select **Deploy Beanie Bot to Azure VM**
- Click **Run workflow**

**Option C: Local deployment script**
```powershell
# Run from Windows
.\deploy-local.ps1
```

## How It Works

### Automated (GitHub Actions)
1. You push code to GitHub `main` branch
2. GitHub Actions triggers workflow
3. Workflow uploads changed files to VM
4. Runs `deploy.sh` which:
   - Backs up state files
   - Stops the bot service
   - Updates dependencies
   - Restarts the bot service
   - Shows status and recent logs

### Manual (Local Script)
1. Run `.\deploy-local.ps1` from PowerShell
2. Script uploads files via SCP
3. Runs deployment script on VM via SSH
4. Bot restarts automatically

## Useful Commands

### On VM (via SSH)
```bash
# View live logs
sudo journalctl -u beanie-bot -f

# Check status
sudo systemctl status beanie-bot

# Restart bot
sudo systemctl restart beanie-bot

# Manual deployment
cd ~/beanie-bot && bash deploy.sh
```

### On Local Machine
```powershell
# Quick deploy
.\deploy-local.ps1

# SSH into VM
ssh Bean@20.6.132.164

# Upload single file
scp main.py Bean@20.6.132.164:~/beanie-bot/
```

## Files NOT Deployed
The following files remain untouched during deployment (to preserve state):
- `.env` (environment variables)
- `*.json.bak` (backup files)
- `.venv/` (virtual environment)
- `archive_*.json` (unless explicitly updated)

## Troubleshooting

### GitHub Actions fails
- Check **Actions** tab for error logs
- Verify secrets are set correctly
- Ensure VM is running and accessible

### Local script fails
- Ensure you can SSH manually: `ssh Bean@20.6.132.164`
- Check VM password is correct
- Verify network connectivity

### Bot doesn't start after deployment
```bash
# Check logs
sudo journalctl -u beanie-bot -n 50

# Try manual start
cd ~/beanie-bot
source .venv/bin/activate
python main.py
```
