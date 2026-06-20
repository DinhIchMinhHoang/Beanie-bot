"""
Tests for the Economy feature.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from features.economy import EconomyFeature, ShopView, SHOP_ITEMS, ITEMS_BY_CATEGORY

TEST_GUILD_ID = 999888777666555


class TestEconomyFeature:
    """Test suite for Economy Feature."""

    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.user = MagicMock()
        bot.user.id = 123456789
        bot.guilds = []
        bot.add_cog = AsyncMock()
        return bot

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.get_storage = None
        config.get_guild_config = MagicMock()
        return config

    @pytest.fixture
    def mock_voice_feature(self):
        vf = MagicMock()
        vf.load_voice_stats = MagicMock(return_value={})
        vf.get_user_rank = MagicMock(return_value=("Iron", None, [], 1.0))
        return vf

    @pytest.fixture
    def economy_feature(self, mock_bot, mock_config, mock_voice_feature):
        return EconomyFeature(mock_bot, mock_config, mock_voice_feature)

    def test_shop_items_structure(self):
        """Verify shop items have required fields."""
        for key, info in SHOP_ITEMS.items():
            assert "name" in info, f"Missing name in {key}"
            assert "type" in info, f"Missing type in {key}"
            assert "value" in info, f"Missing value in {key}"
            assert "cost" in info, f"Missing cost in {key}"
            assert "category" in info, f"Missing category in {key}"
            assert info["cost"] > 0, f"Zero cost in {key}"

    def test_items_by_category_integrity(self):
        """Verify all items are categorized correctly."""
        total_categorized = sum(len(items) for items in ITEMS_BY_CATEGORY.values())
        assert total_categorized == len(SHOP_ITEMS)

    @pytest.mark.asyncio
    async def test_eco_cmd_no_storage(self, economy_feature):
        """Test /eco when storage is unavailable."""
        interaction = AsyncMock()
        interaction.guild.id = TEST_GUILD_ID
        interaction.user.id = 123456
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await economy_feature.eco_cmd.callback(economy_feature, interaction)

        interaction.response.defer.assert_called_once()
        interaction.followup.send.assert_called_once()
        assert "Your Economy" in interaction.followup.send.call_args[1]["embed"].title

    @pytest.mark.asyncio
    async def test_shop_cmd(self, economy_feature):
        """Test /shop sends ephemeral message with view."""
        interaction = AsyncMock()
        interaction.guild.id = TEST_GUILD_ID
        interaction.user.id = 123456
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await economy_feature.shop_cmd.callback(economy_feature, interaction)

        interaction.response.defer.assert_called_once()
        interaction.followup.send.assert_called_once()
        args = interaction.followup.send.call_args[1]
        assert "embed" in args
        assert "view" in args
        assert isinstance(args["view"], ShopView)

    @pytest.mark.asyncio
    async def test_gift_cmd_self(self, economy_feature):
        """Test /gift to yourself is rejected."""
        interaction = AsyncMock()
        interaction.guild.id = TEST_GUILD_ID
        interaction.user.id = 123456
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        target_user = MagicMock()
        target_user.id = 123456  # Same as sender

        await economy_feature.gift_cmd.callback(economy_feature, interaction, target_user, 100)

        interaction.followup.send.assert_called_once()
        assert "cannot gift" in interaction.followup.send.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_gift_cmd_negative(self, economy_feature):
        """Test /gift with 0 or negative amount."""
        interaction = AsyncMock()
        interaction.guild.id = TEST_GUILD_ID
        interaction.user.id = 123456
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        target_user = MagicMock()
        target_user.id = 789012

        await economy_feature.gift_cmd.callback(economy_feature, interaction, target_user, 0)

        interaction.followup.send.assert_called_once()
        assert "positive" in interaction.followup.send.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_gift_cmd_too_small(self, economy_feature):
        """Test /gift under 10 minimum."""
        interaction = AsyncMock()
        interaction.guild.id = TEST_GUILD_ID
        interaction.user.id = 123456
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        target_user = MagicMock()
        target_user.id = 789012

        await economy_feature.gift_cmd.callback(economy_feature, interaction, target_user, 5)

        interaction.followup.send.assert_called_once()
        assert "minimum" in interaction.followup.send.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_richest_cmd_no_storage(self, economy_feature):
        """Test /richest when storage is unavailable."""
        interaction = AsyncMock()
        interaction.guild.id = TEST_GUILD_ID
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await economy_feature.richest_cmd.callback(economy_feature, interaction)

        interaction.followup.send.assert_called_once()
        assert "unavailable" in interaction.followup.send.call_args[0][0].lower()


class TestShopView:
    """Test suite for Shop View UI."""

    @pytest.fixture
    def mock_cog(self):
        cog = MagicMock()
        cog.get_balance = MagicMock(return_value=1000.0)
        cog._get_storage = MagicMock(return_value=None)
        cog._build_shop_embed = MagicMock(return_value=MagicMock())
        cog._build_category_embed = MagicMock(return_value=MagicMock())
        return cog

    @pytest.fixture
    def shop_view(self, mock_cog):
        return ShopView(mock_cog, 123456, TEST_GUILD_ID)

    def test_shop_view_initial_state(self, shop_view):
        """Test ShopView starts with category view."""
        assert shop_view.current_category is None
        assert len(shop_view.children) > 0

    @pytest.mark.asyncio
    async def test_shop_view_interaction_check_wrong_user(self, shop_view):
        """Test interaction check rejects wrong user."""
        interaction = AsyncMock()
        interaction.user.id = 999999  # Different from 123456

        result = await shop_view.interaction_check(interaction)

        assert result is False
        interaction.response.send_message.assert_called_once()

    async def test_shop_view_interaction_check_correct_user(self, shop_view):
        """Test interaction check accepts correct user."""
        interaction = AsyncMock()
        interaction.user.id = 123456

        result = await shop_view.interaction_check(interaction)

        assert result is True
