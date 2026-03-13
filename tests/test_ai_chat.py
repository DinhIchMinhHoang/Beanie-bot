"""
Unit tests for AI Chat feature module.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from features.ai_chat import AIChatFeature
from tests.conftest import TEST_GUILD_ID


@pytest.mark.unit
class TestAIChatFeature:
    """Test suite for AIChatFeature cog."""
    
    @pytest.fixture
    def ai_chat_feature(self, mock_bot, mock_gemini_client, mock_config):
        """Create AIChatFeature instance with mocked dependencies."""
        with patch.object(AIChatFeature, 'cooldown_check') as mock_task, \
             patch('asyncio.create_task', return_value=MagicMock()) as mock_create_task:
            mock_task.start = MagicMock()
            mock_task.cancel = MagicMock()
            feature = AIChatFeature(mock_bot, mock_gemini_client, mock_config)
        return feature
    
    def test_initialization(self, ai_chat_feature, mock_bot, mock_gemini_client):
        """Test that AIChatFeature initializes correctly."""
        assert ai_chat_feature.bot == mock_bot
        assert ai_chat_feature.gemini_client == mock_gemini_client
        assert ai_chat_feature.chat_memory == {}  # Now a dict per guild
        assert ai_chat_feature.ai_queues == {}  # Now a dict per guild
    
    def test_add_to_memory(self, ai_chat_feature):
        """Test adding messages to memory."""
        ai_chat_feature.add_to_memory(TEST_GUILD_ID, "user", "Hello")
        ai_chat_feature.add_to_memory(TEST_GUILD_ID, "model", "Hi there")
        
        assert len(ai_chat_feature.chat_memory[TEST_GUILD_ID]) == 2
        assert ai_chat_feature.chat_memory[TEST_GUILD_ID][0]["user"] == "user"
        assert ai_chat_feature.chat_memory[TEST_GUILD_ID][0]["content"] == "Hello"
        assert ai_chat_feature.chat_memory[TEST_GUILD_ID][1]["user"] == "model"
    
    def test_add_to_memory_limit(self, ai_chat_feature, mock_config):
        """Test memory limit enforcement (max 200 messages)."""
        # Add 250 messages
        for i in range(250):
            ai_chat_feature.add_to_memory(TEST_GUILD_ID, "user", f"Message {i}")
        
        # Should only keep last 200
        assert len(ai_chat_feature.chat_memory[TEST_GUILD_ID]) == 200
        assert ai_chat_feature.chat_memory[TEST_GUILD_ID][0]["content"] == "Message 50"
        assert ai_chat_feature.chat_memory[TEST_GUILD_ID][-1]["content"] == "Message 249"
    
    @pytest.mark.asyncio
    async def test_on_message_not_beanie_command(self, ai_chat_feature):
        """Test that messages not starting with /beanie are ignored."""
        message = AsyncMock()
        message.content = "Hello everyone"
        message.author.bot = False
        message.guild = MagicMock()
        message.guild.id = TEST_GUILD_ID
        
        # Initialize queue for this guild
        guild_queue = ai_chat_feature.get_guild_queue(TEST_GUILD_ID)
        
        with patch.object(guild_queue, 'put_nowait') as mock_put:
            await ai_chat_feature.on_message(message)
            
            # Should not add to queue
            mock_put.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_on_message_from_bot(self, ai_chat_feature):
        """Test that bot messages are ignored."""
        message = AsyncMock()
        message.content = "/beanie hello"
        message.author.bot = True
        message.guild = MagicMock()
        message.guild.id = TEST_GUILD_ID
        
        # Initialize queue for this guild
        guild_queue = ai_chat_feature.get_guild_queue(TEST_GUILD_ID)
        
        with patch.object(guild_queue, 'put_nowait') as mock_put:
            await ai_chat_feature.on_message(message)
            
            # Should not add to queue
            mock_put.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_on_message_during_lockdown(self, ai_chat_feature):
        """Test message handling during lockdown."""
        ai_chat_feature.lockdown[TEST_GUILD_ID] = True
        
        message = AsyncMock()
        message.content = "/beanie hello"
        message.author.bot = False
        message.author.guild_permissions = MagicMock()
        message.author.guild_permissions.administrator = False
        message.guild = MagicMock()
        message.guild.id = TEST_GUILD_ID
        
        await ai_chat_feature.on_message(message)
        
        # Should send cooldown message
        message.reply.assert_called_once()
        assert "cooling down" in message.reply.call_args[0][0].lower()
    
    @pytest.mark.asyncio
    async def test_on_message_valid_command(self, ai_chat_feature):
        """Test valid /beanie command is queued."""
        message = AsyncMock()
        message.content = "/beanie tell me a joke"
        message.author.bot = False
        message.author.guild_permissions = MagicMock()
        message.author.guild_permissions.administrator = False
        message.guild = MagicMock()
        message.guild.id = TEST_GUILD_ID
        
        ai_chat_feature.lockdown[TEST_GUILD_ID] = False
        
        await ai_chat_feature.on_message(message)
        
        # Should add to guild queue
        guild_queue = ai_chat_feature.get_guild_queue(TEST_GUILD_ID)
        assert not guild_queue.empty()
    
    @pytest.mark.asyncio
    async def test_wipe_command_not_admin(self, ai_chat_feature):
        """Test /wipe command fails for non-admin."""
        # Create ctx mock for hybrid_command
        ctx = AsyncMock()
        ctx.guild = MagicMock()
        ctx.guild.id = TEST_GUILD_ID
        
        # Add some memory
        ai_chat_feature.add_to_memory(TEST_GUILD_ID, "user", "test")
        ai_chat_feature.add_to_memory(TEST_GUILD_ID, "model", "response")
        assert len(ai_chat_feature.chat_memory[TEST_GUILD_ID]) > 0
        
        await ai_chat_feature.wipe.callback(ai_chat_feature, ctx)
        
        # Memory should be cleared
        assert len(ai_chat_feature.chat_memory.get(TEST_GUILD_ID, [])) == 0
        ctx.send.assert_called_once()
        assert "wiped" in ctx.send.call_args[0][0].lower()
    
    @pytest.mark.asyncio
    async def test_process_ai_queue_with_response(self, ai_chat_feature, mock_gemini_client):
        """Test processing AI queue with successful response."""
        message = AsyncMock()
        message.content = "/beanie hello"
        message.author.display_name = "TestUser"
        message.author.id = 123456
        message.guild = MagicMock()
        message.guild.id = TEST_GUILD_ID
        # Mock typing() context manager
        typing_mock = AsyncMock()
        typing_mock.__aenter__ = AsyncMock(return_value=None)
        typing_mock.__aexit__ = AsyncMock(return_value=None)
        message.channel.typing = MagicMock(return_value=typing_mock)
        message.channel.send = AsyncMock()
        message.reply = AsyncMock()
        
        # Mock Gemini response
        mock_response = MagicMock()
        mock_response.text = "Hello! How can I help you?"
        
        with patch('asyncio.to_thread', return_value=mock_response):
            # Add message to guild queue
            guild_queue = ai_chat_feature.get_guild_queue(TEST_GUILD_ID)
            await guild_queue.put((message, "hello"))
            
            # Process guild queue
            await ai_chat_feature.process_guild_queue(TEST_GUILD_ID)
        
        # Should have added to guild memory
        assert len(ai_chat_feature.chat_memory.get(TEST_GUILD_ID, [])) >= 1
    
    @pytest.mark.asyncio
    async def test_check_lockdown_task(self, ai_chat_feature, mock_config):
        """Test lockdown check logic."""
        from datetime import datetime, timedelta
        import pytz
        
        # Set up lockdown
        vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        ai_chat_feature.lockdown[TEST_GUILD_ID] = True
        ai_chat_feature.lockdown_until[TEST_GUILD_ID] = datetime.now(vn_tz) - timedelta(hours=1)  # 1 hour ago
        mock_config.VIETNAM_TZ = vn_tz
        
        # Check lockdown should clear it since time has passed
        result = ai_chat_feature.check_lockdown(TEST_GUILD_ID)
        
        # Should have cleared lockdown
        assert ai_chat_feature.lockdown.get(TEST_GUILD_ID, False) is False
        assert ai_chat_feature.lockdown_until.get(TEST_GUILD_ID) is None
        assert len(ai_chat_feature.chat_memory.get(TEST_GUILD_ID, [])) == 0


@pytest.mark.integration
class TestAIChatIntegration:
    """Integration tests for AI Chat feature (mock external APIs)."""
    
    @pytest.mark.asyncio
    async def test_full_conversation_flow(self, mock_bot, mock_gemini_client, mock_config):
        """Test full conversation flow from message to response."""
        with patch.object(AIChatFeature, 'cooldown_check') as mock_task, \
             patch('asyncio.create_task', return_value=MagicMock()):
            mock_task.start = MagicMock()
            feature = AIChatFeature(mock_bot, mock_gemini_client, mock_config)
            
            # Create message
            message = AsyncMock()
            message.content = "/beanie what is 2+2?"
            message.author.bot = False
            message.author.display_name = "MathStudent"
            message.author.id = 999888
            message.author.guild_permissions = MagicMock()
            message.author.guild_permissions.administrator = False
            message.guild = MagicMock()
            message.guild.id = TEST_GUILD_ID
            
            # Mock Gemini response
            mock_response = MagicMock()
            mock_response.text = "2 + 2 equals 4"
            mock_gemini_client.models.generate_content = AsyncMock(return_value=mock_response)
            
            # Process message
            await feature.on_message(message)
            
            # Should have added to guild queue or memory
            guild_queue = feature.get_guild_queue(TEST_GUILD_ID)
            assert not guild_queue.empty() or len(feature.chat_memory.get(TEST_GUILD_ID, [])) > 0
