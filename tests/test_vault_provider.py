import pytest

from unittest.mock import patch
from src.dlp_engine import TermFetchError, VaultTermProvider


def _provider():
    return VaultTermProvider(
        url="http://localhost:8200", token="token", path="secret/data"
    )


def test_vault_provider_success():
    # Mock hvac client
    with patch("src.dlp_engine.hvac.Client") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.is_authenticated.return_value = True

        # Mock read_secret_version response
        mock_client_instance.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"term1": "secret1", "term2": ["secret2", "secret3"]}}
        }

        terms = _provider().get_terms()

        assert "secret1" in terms
        assert "secret2" in terms
        assert "secret3" in terms
        assert len(terms) == 3


def test_vault_provider_unauthenticated_raises():
    """A failed fetch must NOT be reported as 'no terms'.

    Returning [] here would install an empty keyword set upstream and
    silently forward secrets in the clear.
    """
    with patch("src.dlp_engine.hvac.Client") as MockClient:
        MockClient.return_value.is_authenticated.return_value = False

        with pytest.raises(TermFetchError):
            _provider().get_terms()


def test_vault_provider_exception_raises():
    with patch("src.dlp_engine.hvac.Client") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.is_authenticated.return_value = True
        mock_client_instance.secrets.kv.v2.read_secret_version.side_effect = Exception(
            "Vault error"
        )

        with pytest.raises(TermFetchError):
            _provider().get_terms()


def test_vault_provider_serves_cache_after_outage():
    """Once a good fetch happened, a later outage falls back to it."""
    with patch("src.dlp_engine.hvac.Client") as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.is_authenticated.return_value = True
        read = mock_client_instance.secrets.kv.v2.read_secret_version
        read.return_value = {"data": {"data": {"term1": "secret1"}}}

        provider = _provider()
        assert provider.get_terms() == ["secret1"]

        # Vault goes away; the provider must keep serving the last good list
        # instead of emptying the term set.
        read.side_effect = Exception("Vault unreachable")
        assert provider.get_terms() == ["secret1"]
