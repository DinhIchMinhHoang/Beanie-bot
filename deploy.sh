#!/bin/bash
# Deployment script for Beanie Bot on Azure VM

set -e  # Exit on error

echo "==================================="
echo "Beanie Bot Deployment Script"
echo "==================================="

# Navigate to bot directory
cd ~/beanie-bot

echo "1. Backing up state files..."
cp state.json state.json.bak 2>/dev/null || true
cp birthdays.json birthdays.json.bak 2>/dev/null || true
cp voice_stats.json voice_stats.json.bak 2>/dev/null || true
cp competitors.json competitors.json.bak 2>/dev/null || true
cp entry_settings.json entry_settings.json.bak 2>/dev/null || true
cp archive_*.json archive_backup/ 2>/dev/null || true

echo "2. Stopping bot service..."
sudo systemctl stop beanie-bot

echo "3. Updating dependencies..."
source .venv/bin/activate
pip install -r requirements.txt --upgrade

echo "4. Starting bot service..."
sudo systemctl start beanie-bot

echo "5. Checking bot status..."
sleep 3
sudo systemctl status beanie-bot --no-pager -l

echo "==================================="
echo "Deployment completed!"
echo "==================================="

# Show last 20 lines of logs
echo ""
echo "Recent logs:"
sudo journalctl -u beanie-bot -n 20 --no-pager
