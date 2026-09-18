"""Encrypt a .env file to .env.enc with a master password (PBKDF2 + Fernet).

Usage:
    python -m amg.encrypt_config [--input PATH] [--output PATH]

The default input is amg/.env; the default output is amg/.env.enc.
You will be prompted for a master password (hidden input, entered twice to confirm).
"""
import argparse
import getpass
import sys
from pathlib import Path

from amg.sender import encrypt_env_file, _default_config_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Encrypt an AMG .env config file')
    default_dir = _default_config_dir()
    parser.add_argument('--input', default=str(default_dir / '.env'),
                        help='Path to plaintext .env (default: amg/.env)')
    parser.add_argument('--output', default=str(default_dir / '.env.enc'),
                        help='Path to encrypted .env.enc (default: amg/.env.enc)')
    args = parser.parse_args(argv)
    src = Path(args.input)
    dst = Path(args.output)
    if not src.exists():
        print(f'Error: {src} not found.', file=sys.stderr)
        return 1
    print(f'Encrypting {src} -> {dst}')
    pw1 = getpass.getpass('Enter master password: ')
    pw2 = getpass.getpass('Confirm master password: ')
    if pw1 != pw2:
        print('Error: passwords do not match.', file=sys.stderr)
        return 1
    if len(pw1) < 4:
        print('Error: password must be at least 4 characters.', file=sys.stderr)
        return 1
    encrypted = encrypt_env_file(src, pw1)
    dst.write_bytes(encrypted)
    print(f'Encrypted config written to {dst}')
    print('You can now delete the plaintext .env file.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
