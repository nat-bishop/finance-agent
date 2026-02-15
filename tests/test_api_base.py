"""Tests for finance_agent.api_base -- BaseAPIClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from finance_agent.api_base import BaseAPIClient

# ── _to_dict ─────────────────────────────────────────────────────


def test_to_dict_with_to_dict():
    obj = MagicMock()
    obj.to_dict.return_value = {"a": 1}
    assert BaseAPIClient._to_dict(obj) == {"a": 1}


def test_to_dict_with_model_dump():
    obj = MagicMock(spec=[])
    # Need to add model_dump explicitly since spec=[] removes everything
    obj.model_dump = MagicMock(return_value={"b": 2})
    assert BaseAPIClient._to_dict(obj) == {"b": 2}


def test_to_dict_passthrough():
    assert BaseAPIClient._to_dict({"c": 3}) == {"c": 3}
    assert BaseAPIClient._to_dict([1, 2, 3]) == [1, 2, 3]
    assert BaseAPIClient._to_dict("string") == "string"


# ── Rate limiting delegation ─────────────────────────────────────


def test_rate_read_calls_limiter():
    client = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    with patch.object(client._limiter, "acquire_read_sync") as mock:
        client._rate_read()
        mock.assert_called_once()


def test_rate_write_calls_limiter():
    client = BaseAPIClient(reads_per_sec=10, writes_per_sec=5)
    with patch.object(client._limiter, "acquire_write_sync") as mock:
        client._rate_write()
        mock.assert_called_once()
