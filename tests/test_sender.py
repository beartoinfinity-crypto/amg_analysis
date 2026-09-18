import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from amg import sender


SAMPLE_ENV = (
    'API_URL=https://chilunsing.com/v1/amg\n'
    'API_KEY=Basic UkVTVF9BTUc6a1VrZXp0cUtRTDVXMYYTTT=\n'
)


def test_parse_env_basic():
    config = sender._parse_env(SAMPLE_ENV)
    assert config['API_URL'] == 'https://chilunsing.com/v1/amg'
    assert config['API_KEY'] == 'Basic UkVTVF9BTUc6a1VrZXp0cUtRTDVXMYYTTT='


def test_parse_env_ignores_comments_and_blanks():
    text = '# comment\n\nAPI_URL=https://example.com\n  \n# another\n'
    assert sender._parse_env(text) == {'API_URL': 'https://example.com'}


def test_parse_env_handles_quotes():
    text = 'API_URL="https://example.com"\nAPI_PASSWORD=\'secret\'\n'
    config = sender._parse_env(text)
    assert config['API_URL'] == 'https://example.com'
    assert config['API_PASSWORD'] == 'secret'


def test_parse_env_skips_malformed_lines():
    text = 'API_URL=https://example.com\nNO_EQUALS_HERE\nAPI_KEY=ok\n'
    config = sender._parse_env(text)
    assert config == {'API_URL': 'https://example.com', 'API_KEY': 'ok'}


def test_encrypt_decrypt_roundtrip(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text(SAMPLE_ENV, encoding='utf-8')
    password = 'test-password-123'
    encrypted = sender.encrypt_env_file(env_file, password)
    decrypted_text = sender.decrypt_env_bytes(encrypted, password)
    assert 'API_URL=https://chilunsing.com/v1/amg' in decrypted_text
    assert 'API_KEY=Basic' in decrypted_text
    config = sender._parse_env(decrypted_text)
    assert config['API_KEY'] == 'Basic UkVTVF9BTUc6a1VrZXp0cUtRTDVXMYYTTT='


def test_decrypt_wrong_password_fails(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text(SAMPLE_ENV, encoding='utf-8')
    encrypted = sender.encrypt_env_file(env_file, 'correct-password')
    with pytest.raises(Exception):
        sender.decrypt_env_bytes(encrypted, 'wrong-password')


def test_load_config_from_env(tmp_path, monkeypatch):
    env_file = tmp_path / '.env'
    env_file.write_text(SAMPLE_ENV, encoding='utf-8')
    monkeypatch.setattr(sender, '_default_config_dir', lambda: tmp_path)
    config = sender.load_config()
    assert config['API_URL'] == 'https://chilunsing.com/v1/amg'
    assert config['API_KEY'] == 'Basic UkVTVF9BTUc6a1VrZXp0cUtRTDVXMYYTTT='


def test_load_config_from_enc(tmp_path, monkeypatch):
    env_file = tmp_path / '.env'
    env_file.write_text(SAMPLE_ENV, encoding='utf-8')
    enc_file = tmp_path / '.env.enc'
    enc_file.write_bytes(sender.encrypt_env_file(env_file, 'enc-password'))
    env_file.unlink()
    monkeypatch.setattr(sender, '_default_config_dir', lambda: tmp_path)
    config = sender.load_config(password='enc-password')
    assert config['API_KEY'] == 'Basic UkVTVF9BTUc6a1VrZXp0cUtRTDVXMYYTTT='


def test_load_config_explicit_path(tmp_path):
    env_file = tmp_path / 'custom.env'
    env_file.write_text(SAMPLE_ENV, encoding='utf-8')
    config = sender.load_config(explicit_path=str(env_file))
    assert config['API_URL'] == 'https://chilunsing.com/v1/amg'


def test_load_config_missing_keys(tmp_path, monkeypatch):
    env_file = tmp_path / '.env'
    env_file.write_text('INCOMPLETE=yes\n', encoding='utf-8')
    monkeypatch.setattr(sender, '_default_config_dir', lambda: tmp_path)
    with pytest.raises(ValueError, match='Missing config keys'):
        sender.load_config()


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        sender.load_config(explicit_path='/nonexistent/.env')


def test_convert_to_escaped():
    assert sender.convert_to_escaped('line1\nline2\r\nline3') == 'line1\\r\\nline2\\r\\nline3'
    assert sender.convert_to_escaped('single line') == 'single line'
    assert sender.convert_to_escaped('trailing\n') == 'trailing\\r\\n'


def test_convert_to_escaped_strips_trailing_spaces():
    result = sender.convert_to_escaped('line1  \nline2')
    assert result == 'line1\\r\\nline2'


def test_send_message_success():
    config = {'API_URL': 'https://test.example.com/api', 'API_KEY': 'Basic dGVzdDp0ZXN0'}
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.text = '{"ok":true}'
    mock_resp.ok = True
    mock_resp.raise_for_status = MagicMock()
    with patch('amg.sender.requests.post', return_value=mock_resp) as mock_post:
        result = sender.send_message('PNL\nCX841/23AUG JFK\nENDPNL\n', config)
        assert result['status_code'] == 201
        assert result['success'] is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == 'https://test.example.com/api'
        assert call_kwargs[1]['json']['rawTypeBMessage'].startswith('PNL')
        assert call_kwargs[1]['headers']['Authorization'] == 'Basic dGVzdDp0ZXN0'


def test_send_message_failure():
    config = {'API_URL': 'https://test.example.com/api', 'API_KEY': 'Basic dGVzdDp0ZXN0'}
    import requests as req
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = 'Unauthorized'
    mock_resp.ok = False
    mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError('401')
    with patch('amg.sender.requests.post', return_value=mock_resp):
        with pytest.raises(req.exceptions.HTTPError):
            sender.send_message('test', config)
