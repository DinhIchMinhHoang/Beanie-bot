# Testing Guide for Beanie Bot

## Overview
This project uses **pytest** with **pytest-asyncio** to handle async Discord bot testing. Tests are automatically run in CI/CD before deployment.

## Setup

### 1. Install Test Dependencies
```bash
pip install -r requirements-dev.txt
```

### 2. Environment Variables for Testing
Tests use **mocked external APIs** so you don't need real credentials. However, for local testing with actual APIs:

```bash
cp .env.example .env
# Edit .env with your actual tokens
```

**Important**: `.env` is gitignored and should NEVER be committed to the repository.

## Running Tests

### Run All Tests
```bash
pytest
```

### Run with Coverage Report
```bash
pytest --cov=features --cov=core --cov-report=term-missing
```

### Run Specific Test File
```bash
pytest tests/test_birthday.py
```

### Run Specific Test
```bash
pytest tests/test_birthday.py::TestBirthdayFeature::test_birthday_cmd_add_success
```

### Run Only Unit Tests
```bash
pytest -m unit
```

### Run with Verbose Output
```bash
pytest -v
```

## Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures and mocks
├── test_birthday.py         # Birthday feature tests
├── test_voice_track.py      # Voice tracking tests
├── test_ai_chat.py          # AI chat tests
├── test_config.py           # Configuration tests
└── README.md               # This file
```

## Writing Tests

### Async Test Example
```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_my_async_function(mock_bot, mock_interaction):
    """Test async Discord command."""
    # Arrange
    mock_interaction.user.id = 123456
    
    # Act
    await my_feature.my_command(mock_interaction, "test")
    
    # Assert
    mock_interaction.response.send_message.assert_called_once()
```

### Using Fixtures
Fixtures are defined in `conftest.py`:

- `mock_bot` - Mocked Discord bot
- `mock_interaction` - Mocked Discord interaction
- `mock_member` - Mocked Discord member
- `mock_config` - Mocked BotConfig
- `mock_gemini_client` - Mocked Gemini AI client
- `mock_azure_client` - Mocked Azure compute client
- `temp_json_files` - Temporary JSON files for testing

### Mocking External APIs

**Discord API:**
```python
@pytest.mark.asyncio
async def test_with_discord_mock(mock_bot, mock_interaction):
    # mock_bot and mock_interaction are already set up
    await my_feature.command(mock_interaction)
    mock_interaction.response.send_message.assert_called()
```

**Gemini AI:**
```python
@pytest.mark.asyncio
async def test_ai_response(ai_chat_feature, mock_gemini_client):
    # Mock Gemini response
    mock_response = MagicMock()
    mock_response.text = "Hello!"
    mock_gemini_client.models.generate_content = AsyncMock(return_value=mock_response)
    
    # Test your feature
    # ...
```

**File I/O:**
```python
from unittest.mock import mock_open, patch

def test_load_data():
    test_data = '{"user_id": "123456"}'
    with patch('builtins.open', mock_open(read_data=test_data)):
        result = feature.load_birthdays()
        assert "123456" in result
```

## CI/CD Integration

### GitHub Actions Workflow
Tests run automatically on:
- Push to `main` branch
- Pull requests to `main`

**Workflow steps:**
1. ✅ Checkout code
2. ✅ Set up Python 3.11
3. ✅ Install dependencies
4. ✅ Create mock `.env` file (from test values, not secrets)
5. ✅ Run pytest with coverage
6. ✅ Upload coverage report
7. 🚀 Deploy to Azure VM (only if tests pass)

### GitHub Secrets Required
For deployment (not for tests):
- `VM_HOST` - Azure VM IP address
- `VM_USER` - SSH username
- `VM_PASSWORD` - SSH password

### Test Environment Variables
Tests use **mock values** that are auto-generated in CI:
```bash
DISCORD_TOKEN=test_token_${github.sha}
GEMINI_API_KEY=test_key_${github.sha}
# etc.
```

## Best Practices

### ✅ DO:
- Mock external APIs (Discord, Gemini, Azure, SSH, RCON)
- Test business logic, not API implementations
- Use `@pytest.mark.asyncio` for async tests
- Use descriptive test names
- Test both success and failure cases
- Check error messages and edge cases

### ❌ DON'T:
- Make real API calls in tests
- Commit `.env` file to repository
- Test Discord.py internals
- Create tests that depend on external services
- Skip mocking for expensive operations

## Coverage Goals

Aim for:
- **80%+ code coverage** for features
- **100% coverage** for critical paths (birthday checks, voice tracking, rank calculations)
- Test all command handlers
- Test all error paths

## Debugging Failed Tests

### View Full Traceback
```bash
pytest --tb=long
```

### Run Single Failing Test
```bash
pytest tests/test_birthday.py::test_name -v --tb=short
```

### Print Debug Output
```bash
pytest -s  # Shows print() statements
```

### Run with pdb Debugger
```bash
pytest --pdb  # Drops into debugger on failure
```

## Common Issues

### "Event loop is closed"
- Ensure `asyncio_mode = auto` in `pytest.ini`
- Use `@pytest.mark.asyncio` decorator

### "Mock not called"
- Check if mock was properly patched
- Verify mock is used in tested code path
- Use `assert_called_once()` vs `assert_called()`

### Import Errors
- Ensure all dependencies in `requirements.txt` and `requirements-dev.txt`
- Check Python path includes project root

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)
- [discord.py testing guide](https://discordpy.readthedocs.io/en/stable/ext/test/index.html)
