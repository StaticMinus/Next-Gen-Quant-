"""
tests/test_webapp_server.py
===========================
Tests for Next Generation WebApp server endpoints:
1. GET /api/telemetry
2. POST /api/close_position
"""

import json
import pytest
import requests
import time
from unittest.mock import patch
from src.integrations.webapp_server import launch_server_in_thread


@pytest.fixture(scope="module")
def webapp_url():
    port = 8899
    thread = launch_server_in_thread(port=port)
    time.sleep(0.5)
    yield f"http://localhost:{port}"


@patch("src.integrations.ctrader_mcp_client.ctrader_client.get_enriched_positions")
@patch("src.integrations.ctrader_mcp_client.ctrader_client.get_balance")
def test_webapp_telemetry_get(mock_bal, mock_pos, webapp_url):
    mock_pos.return_value = []
    mock_bal.return_value = {"balance": 6000.0, "equity": 6000.0, "freeMargin": 5700.0}
    resp = requests.get(f"{webapp_url}/api/telemetry", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert "capital" in data
    assert "equity" in data
    assert "active_positions" in data
    assert isinstance(data["active_positions"], list)


@patch("src.integrations.ctrader_mcp_client.ctrader_client.close_position")
@patch("src.integrations.ctrader_mcp_client.ctrader_client.get_enriched_positions")
@patch("src.integrations.ctrader_mcp_client.ctrader_client.get_balance")
def test_webapp_close_position_post(mock_bal, mock_pos, mock_close, webapp_url):
    mock_close.return_value = {"status": "success"}
    mock_pos.return_value = []
    mock_bal.return_value = {"balance": 6000.0, "equity": 6000.0, "freeMargin": 5700.0}

    resp = requests.post(
        f"{webapp_url}/api/close_position",
        json={"position_id": 3069593, "client": "david"},
        timeout=5
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["position_id"] == 3069593
    mock_close.assert_called_with(3069593)
