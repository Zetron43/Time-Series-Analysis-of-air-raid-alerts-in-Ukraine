"""Unit tests for AirRaidAIAgent and its Function Calling tools."""

from unittest.mock import MagicMock
import pytest
from src.bot.ai_agent import AirRaidAIAgent


def test_ai_agent_unconfigured_response():
    """Agent returns instructional prompt if no API key is set."""
    agent = AirRaidAIAgent(api_key=None)
    resp = agent.answer_query("Яка зараз ситуація в Києві?", chat_id=123)
    assert "ШІ-Агент 'Вартовий Неба' готовий до підключення" in resp
    assert "GEMINI_API_KEY" in resp


def test_ai_agent_tools_execution():
    """Verifies that all tool functions execute and return valid string descriptions."""
    agent = AirRaidAIAgent(api_key="mock_key")

    # 1. Live alerts overview
    overview = agent.get_live_alerts_overview()
    assert isinstance(overview, str)
    assert "Станом на" in overview

    # 2. Regional filter
    reg_status = agent.get_live_alerts_overview(region_filter="Київ")
    assert isinstance(reg_status, str)
    assert "Київ" in reg_status or "Станом на" in reg_status

    # 3. Threat forecast
    forecast = agent.analyze_threat_forecast("Сумська", horizon="1h", raion_name="Шосткинський район")
    assert isinstance(forecast, str)
    assert "Аналітичний прогноз" in forecast
    assert "%" in forecast

    # 4. Radar status
    radar = agent.get_radar_drones_status()
    assert isinstance(radar, str)
    assert ("Радари Neptun" in radar) or ("активних" in radar)

    # 5. Tracking manager
    tracking = agent.manage_user_tracking(chat_id=99999, action="list")
    assert isinstance(tracking, str)


def test_ai_agent_mock_answer_query(monkeypatch):
    """Verifies that agent correctly invokes Gemini Chat and formats answer."""
    agent = AirRaidAIAgent(api_key="valid_test_key")

    mock_client = MagicMock()
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "🚨 У Сумській області зафіксовано 2 БпЛА курсом на захід. Ймовірність загрози 68%."
    mock_chat.send_message.return_value = mock_response
    mock_client.chats.create.return_value = mock_chat

    agent._client = mock_client

    ans = agent.answer_query("Що там по Сумщині?", chat_id=12345)
    assert ans == "🚨 У Сумській області зафіксовано 2 БпЛА курсом на захід. Ймовірність загрози 68%."
    assert mock_client.chats.create.called
    assert mock_chat.send_message.called


def test_ai_agent_auth_key_accepted():
    """Verifies that modern Google AI Studio auth keys (AQ...) are accepted."""
    agent = AirRaidAIAgent(api_key="AQ.mock_auth_key")
    assert agent.is_configured()


def test_ai_agent_invalid_key_exception_handled():
    """Verifies that API_KEY_INVALID RPC exceptions are formatted cleanly."""
    agent = AirRaidAIAgent(api_key="dummy_invalid_key")
    mock_client = MagicMock()
    mock_client.chats.create.side_effect = Exception("400 INVALID_ARGUMENT. API_KEY_INVALID. Please pass a valid API key.")
    agent._client = mock_client

    resp = agent.answer_query("Привіт", chat_id=123)
    assert "Помилка ключа Gemini API" in resp
    assert "Google AI Studio" in resp

