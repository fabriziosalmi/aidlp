from unittest.mock import patch
from src.dlp_engine import VaultTermProvider


def test_vault_provider_success():
    # Mock hvac client
    with patch('src.dlp_engine.hvac.Client') as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.is_authenticated.return_value = True

        # Mock read_secret_version response
        mock_client_instance.secrets.kv.v2.read_secret_version.return_value = {
            'data': {
                'data': {
                    'term1': 'secret1',
                    'term2': ['secret2', 'secret3']
                }
            }
        }

        provider = VaultTermProvider(url="http://localhost:8200", token="token", path="secret/data")
        terms = provider.get_terms()

        assert "secret1" in terms
        assert "secret2" in terms
        assert "secret3" in terms
        assert len(terms) == 3


def test_vault_provider_unauthenticated():
    with patch('src.dlp_engine.hvac.Client') as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.is_authenticated.return_value = False

        provider = VaultTermProvider(url="http://localhost:8200", token="token", path="secret/data")
        terms = provider.get_terms()

        assert terms == []


def test_vault_provider_exception():
    with patch('src.dlp_engine.hvac.Client') as MockClient:
        mock_client_instance = MockClient.return_value
        mock_client_instance.is_authenticated.return_value = True
        mock_client_instance.secrets.kv.v2.read_secret_version.side_effect = Exception("Vault error")

        provider = VaultTermProvider(url="http://localhost:8200", token="token", path="secret/data")
        terms = provider.get_terms()

        assert terms == []
