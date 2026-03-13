# CI/CD Setup Guide

## Overview
This guide explains how to set up GitHub Secrets and configure CI/CD for Beanie Bot with automated testing before deployment.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   GitHub Repository                      │
│  ┌──────────────────────────────────────────────────┐  │
│  │         Push to main / Create PR                  │  │
│  └────────────────┬─────────────────────────────────┘  │
│                   │                                      │
│  ┌────────────────▼─────────────────────────────────┐  │
│  │         GitHub Actions Workflow                   │  │
│  │  ┌──────────────────────────────────────────┐    │  │
│  │  │  Job 1: Test                              │    │  │
│  │  │  • Install Python & dependencies          │    │  │
│  │  │  • Create mock .env from test values      │    │  │
│  │  │  • Run pytest (with mocked APIs)          │    │  │
│  │  │  • Generate coverage report               │    │  │
│  │  └──────────┬───────────────────────────────┘    │  │
│  │             │ ✅ Tests Pass                       │  │
│  │  ┌──────────▼───────────────────────────────┐    │  │
│  │  │  Job 2: Deploy (only on main push)        │    │  │
│  │  │  • SSH to Azure VM                        │    │  │
│  │  │  • Pull latest code                       │    │  │
│  │  │  • Install dependencies                   │    │  │
│  │  │  • Restart bot service                    │    │  │
│  │  └───────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## GitHub Secrets Setup

### Required Secrets for Deployment

1. **VM_HOST** - Your Azure VM's public IP address
2. **VM_USER** - SSH username (e.g., `Bean`)
3. **VM_PASSWORD** - SSH password for the VM

### Setting Up Secrets

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add each secret:

   **VM_HOST:**
   ```
   Name: VM_HOST
   Secret: 20.123.45.67  (your actual VM IP)
   ```

   **VM_USER:**
   ```
   Name: VM_USER
   Secret: Bean  (your SSH username)
   ```

   **VM_PASSWORD:**
   ```
   Name: VM_PASSWORD
   Secret: your_ssh_password_here
   ```

5. Click **Add secret** for each

## How Tests Work Without Real Credentials

### Problem
Tests need environment variables like `DISCORD_TOKEN` and `GEMINI_API_KEY`, but we can't commit real tokens to the repository.

### Solution: Mocking
Tests **mock all external APIs**, so they never make real calls:

#### ✅ What Gets Mocked:
- **Discord API** - Bot connections, interactions, messages
- **Gemini AI** - All AI responses
- **Azure SDK** - VM management operations
- **SSH/RCON** - Minecraft server connections
- **File I/O** - JSON file operations

#### 📝 Example Mock:
```python
# Instead of:
response = await gemini_client.generate("Hello")  # Real API call ❌

# Tests use:
mock_client.generate = AsyncMock(return_value="Mocked response")  # No API call ✅
```

### Test Environment Variables
The CI workflow creates a **fake .env** file with test values:

```bash
# From .github/workflows/deploy.yml
DISCORD_TOKEN=test_token_${github.sha}
GEMINI_API_KEY=test_key_${github.sha}
AZURE_TENANT_ID=test_tenant
# etc.
```

These values are **never used** because APIs are mocked, but they prevent import errors.

## Workflow Behavior

### On Pull Request:
1. ✅ Run tests
2. ✅ Report results
3. ❌ **Do NOT deploy** (safe for reviewing changes)

### On Push to main:
1. ✅ Run tests
2. ✅ If tests pass → Deploy to Azure VM
3. ❌ If tests fail → Stop (no deployment)

## Local Testing

### Run Tests Locally
```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=features --cov=core
```

### Local Testing with Mocks (Recommended)
```bash
# Tests use mocks by default - no real API calls
pytest tests/
```

### Local Testing with Real APIs (Not Recommended)
```bash
# Copy environment template
cp .env.example .env

# Edit .env with real tokens
# Then run:
pytest --real-apis  # (if you add this flag)
```

⚠️ **Warning**: Real API testing is not recommended because:
- Costs money (API usage)
- Slower (network latency)
- Brittle (depends on external services)
- Rate limits can cause failures

## Monitoring CI/CD

### View Test Results
1. Go to your repository
2. Click **Actions** tab
3. Click on a workflow run
4. View **Test** job logs

### View Coverage Report
1. After workflow completes
2. Download **coverage-report** artifact
3. View `.coverage` file locally:
   ```bash
   coverage report
   ```

## Troubleshooting

### Tests Fail in CI but Pass Locally
- **Cause**: Different Python version or missing dependency
- **Fix**: Check CI uses same Python version as `requirements.txt`

### "Module not found" Error
- **Cause**: Missing dependency in `requirements.txt` or `requirements-dev.txt`
- **Fix**: Add missing package to appropriate requirements file

### Deployment Fails After Tests Pass
- **Cause**: SSH connection issue or service restart failed
- **Fix**: Check GitHub Secrets are correct, verify VM is running

### Tests Pass but Bot Doesn't Work After Deploy
- **Cause**: `.env` missing on VM or service configuration issue
- **Fix**: Ensure `.env` exists on VM with real tokens (not test values)

## Best Practices

### ✅ DO:
- Always run tests locally before pushing
- Mock external APIs in tests
- Keep test coverage above 80%
- Add tests for new features
- Review test output in CI before merging PRs

### ❌ DON'T:
- Commit `.env` file (use `.env.example` as template)
- Skip tests (disable `needs: test` in deploy job)
- Make real API calls in tests
- Store secrets in code or comments
- Merge PRs with failing tests

## Deployment Rollback

If deployment breaks production:

```bash
# SSH to VM
ssh Bean@your_vm_ip

# Navigate to bot directory
cd /home/Bean/beanie-bot

# Rollback to previous commit
git log --oneline -5  # Find last working commit
git reset --hard [commit-hash]

# Restart service
sudo systemctl restart beanie-bot
```

## Additional Security

### Optional: Use GitHub Environments
For extra protection:

1. Create "production" environment in GitHub Settings
2. Add required reviewers
3. Update deploy job:
   ```yaml
   deploy:
     environment: production
     # ... rest of job
   ```

### Optional: Use Deployment Keys
Instead of password authentication:

1. Generate SSH key pair
2. Add public key to VM's `~/.ssh/authorized_keys`
3. Add private key to GitHub Secret `VM_SSH_KEY`
4. Update workflow to use key authentication

## Support

For issues:
1. Check [tests/README.md](../tests/README.md) for testing guide
2. Review workflow logs in GitHub Actions
3. Check VM logs: `journalctl -u beanie-bot -n 50`
