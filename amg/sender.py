import base64
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import urllib3
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_CONFIG_KEYS = ('API_URL', 'API_KEY')
_SALT_LENGTH = 16
_KDF_ITERATIONS = 480_000


def _default_config_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _find_config(explicit_path: str | None = None) -> tuple[Path, bool]:
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            raise FileNotFoundError(f'Config file not found: {p}')
        return p, p.suffix.lower() == '.enc'
    d = _default_config_dir()
    enc = d / '.env.enc'
    plain = d / '.env'
    if enc.exists():
        return enc, True
    if plain.exists():
        return plain, False
    raise FileNotFoundError(
        'No config file found. Create .env in the amg package directory '
        f'({d}) or pass --config PATH.'
    )


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode('utf-8')))


def _parse_env(text: str) -> dict[str, str]:
    config: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        config[key] = value
    return config


def encrypt_env_file(plain_path: Path, password: str) -> bytes:
    plaintext = plain_path.read_bytes()
    salt = os.urandom(_SALT_LENGTH)
    key = _derive_key(password, salt)
    token = Fernet(key).encrypt(plaintext)
    payload = {'salt': base64.urlsafe_b64encode(salt).decode(), 'token': token.decode()}
    return json.dumps(payload).encode('utf-8')


def decrypt_env_bytes(data: bytes, password: str) -> str:
    payload = json.loads(data)
    salt = base64.urlsafe_b64decode(payload['salt'])
    token = payload['token']
    key = _derive_key(password, salt)
    return Fernet(key).decrypt(token).decode('utf-8')


def load_config(explicit_path: str | None = None, password: str | None = None) -> dict[str, str]:
    path, is_encrypted = _find_config(explicit_path)
    if is_encrypted:
        pw = password if password is not None else getpass.getpass('Config password: ')
        raw = path.read_bytes()
        text = decrypt_env_bytes(raw, pw)
    else:
        text = path.read_text(encoding='utf-8')
    config = _parse_env(text)
    missing = [k for k in _CONFIG_KEYS if k not in config]
    if missing:
        raise ValueError(f'Missing config keys: {", ".join(missing)}')
    return config


def convert_to_escaped(message: str) -> str:
    normalized = message.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in normalized.split('\n')]
    return '\\r\\n'.join(lines)


def send_message(text: str, config: dict[str, str], verify_ssl: bool = False) -> dict[str, Any]:
    escaped = convert_to_escaped(text)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': config['API_KEY'],
    }
    payload = {
        'systemName': 'SITA',
        'messageType': 'IATATYPEB',
        '_apiVersion': '1',
        'rawTypeBMessage': escaped,
    }
    resp = requests.post(
        config['API_URL'],
        headers=headers,
        json=payload,
        verify=verify_ssl,
        timeout=30,
    )
    body = resp.text.strip() if resp.text.strip() else None
    result: dict[str, Any] = {
        'status_code': resp.status_code,
        'body': body,
        'success': resp.ok,
    }
    resp.raise_for_status()
    return result
