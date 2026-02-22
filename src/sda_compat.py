"""
SDA (Steam Desktop Authenticator) compatibility module.

Reads and decrypts maFiles encrypted by jessecar96's SteamDesktopAuthenticator.
Encryption scheme: PBKDF2(SHA1, 50k iterations, 8-byte salt) → AES-256-CBC (PKCS7).
Salt and IV are stored per-account in manifest.json.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


import os
import secrets as _secrets

SDA_PBKDF2_ITERATIONS = 50000
SDA_KEY_SIZE = 32  # 256 bits
SDA_IV_SIZE = 16   # 128 bits
SDA_SALT_SIZE = 8  # 64 bits


def derive_sda_key(passkey: str, salt_b64: str) -> bytes:
    """Derive encryption key using SDA's scheme: PBKDF2-HMAC-SHA1, 50k iterations."""
    salt = base64.b64decode(salt_b64)
    # SDA uses Rfc2898DeriveBytes which defaults to SHA1
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=SDA_KEY_SIZE,
        salt=salt,
        iterations=SDA_PBKDF2_ITERATIONS,
    )
    return kdf.derive(passkey.encode('utf-8'))


def decrypt_sda_data(passkey: str, salt_b64: str, iv_b64: str, encrypted_b64: str) -> Optional[str]:
    """
    Decrypt data encrypted by SDA's FileEncryptor.

    Args:
        passkey: The encryption passkey
        salt_b64: Base64-encoded 8-byte salt from manifest entry
        iv_b64: Base64-encoded 16-byte IV from manifest entry
        encrypted_b64: Base64-encoded ciphertext (the .maFile contents)

    Returns:
        Decrypted JSON string, or None if passkey is invalid
    """
    try:
        key = derive_sda_key(passkey, salt_b64)
        iv = base64.b64decode(iv_b64)
        ciphertext = base64.b64decode(encrypted_b64)

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()

        # Remove PKCS7 padding
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()

        return plaintext.decode('utf-8')
    except Exception as e:
        logging.debug(f"SDA decryption failed: {e}")
        return None


def read_sda_manifest(folder_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read and parse an SDA manifest.json file.

    Returns dict with keys:
        encrypted: bool
        entries: list of {filename, steamid, encryption_iv, encryption_salt}
        (plus SDA settings like periodic_checking, etc.)
    Returns None if manifest not found or invalid.
    """
    manifest_path = Path(folder_path) / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Validate it looks like an SDA manifest (has entries array)
        if "entries" not in data:
            return None

        return data
    except (json.JSONDecodeError, Exception) as e:
        logging.error(f"Failed to read SDA manifest: {e}")
        return None


def is_sda_folder(folder_path: Path) -> bool:
    """Check if a folder contains SDA-format maFiles (has manifest.json with entries)."""
    manifest = read_sda_manifest(folder_path)
    return manifest is not None and "entries" in manifest


def verify_sda_passkey(folder_path: Path, passkey: str) -> bool:
    """Verify an SDA passkey by attempting to decrypt the first account."""
    manifest = read_sda_manifest(folder_path)
    if not manifest or not manifest.get("encrypted", False):
        return True  # Not encrypted, no passkey needed

    entries = manifest.get("entries", [])
    if not entries:
        return True

    entry = entries[0]
    salt = entry.get("encryption_salt")
    iv = entry.get("encryption_iv")
    filename = entry.get("filename")

    if not salt or not iv or not filename:
        return False

    file_path = Path(folder_path) / filename
    if not file_path.exists():
        return False

    try:
        encrypted_content = file_path.read_text(encoding='utf-8').strip()
        result = decrypt_sda_data(passkey, salt, iv, encrypted_content)
        if result is None:
            return False
        # Try parsing as JSON to double-check
        json.loads(result)
        return True
    except Exception:
        return False


def encrypt_sda_data(passkey: str, salt_b64: str, iv_b64: str, plaintext: str) -> str:
    """
    Encrypt data using SDA's FileEncryptor scheme (AES-256-CBC, PKCS7).

    Args:
        passkey: The encryption passkey
        salt_b64: Base64-encoded 8-byte salt
        iv_b64: Base64-encoded 16-byte IV
        plaintext: The JSON string to encrypt

    Returns:
        Base64-encoded ciphertext
    """
    key = derive_sda_key(passkey, salt_b64)
    iv = base64.b64decode(iv_b64)

    # PKCS7 padding
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode('utf-8')) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(ciphertext).decode('ascii')


def generate_sda_salt() -> str:
    """Generate a random 8-byte salt, returned as base64."""
    return base64.b64encode(os.urandom(SDA_SALT_SIZE)).decode('ascii')


def generate_sda_iv() -> str:
    """Generate a random 16-byte IV, returned as base64."""
    return base64.b64encode(os.urandom(SDA_IV_SIZE)).decode('ascii')


def export_sda_accounts(
    accounts: List[Dict[str, Any]],
    passkey: Optional[str] = None
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Export accounts as SDA-compatible manifest + encrypted/plain .maFile data.

    Args:
        accounts: List of account dicts (from SteamGuardAccount.to_dict())
        passkey: If provided, encrypt files with this passkey (SDA-compatible)

    Returns:
        Tuple of (manifest_dict, files_dict) where files_dict maps filename -> content
    """
    is_encrypted = passkey is not None and len(passkey) > 0
    entries = []
    files = {}

    for account_data in accounts:
        steamid = str(account_data.get("steamid", account_data.get("account_name", "unknown")))
        filename = f"{steamid}.maFile"
        plaintext = json.dumps(account_data, indent=2)

        if is_encrypted:
            salt_b64 = generate_sda_salt()
            iv_b64 = generate_sda_iv()
            encrypted = encrypt_sda_data(passkey, salt_b64, iv_b64, plaintext)
            files[filename] = encrypted
            entries.append({
                "encryption_iv": iv_b64,
                "encryption_salt": salt_b64,
                "filename": filename,
                "steamid": int(steamid) if steamid.isdigit() else 0
            })
        else:
            files[filename] = plaintext
            entries.append({
                "encryption_iv": None,
                "encryption_salt": None,
                "filename": filename,
                "steamid": int(steamid) if steamid.isdigit() else 0
            })

    manifest = {
        "encrypted": is_encrypted,
        "first_run": True,
        "entries": entries,
        "periodic_checking": False,
        "periodic_checking_interval": 5,
        "periodic_checking_checkall": False,
        "auto_confirm_market_transactions": False,
        "auto_confirm_trades": False
    }

    return manifest, files


def import_sda_accounts(folder_path: Path, passkey: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Import all accounts from an SDA maFiles folder.

    Args:
        folder_path: Path to the SDA maFiles directory
        passkey: Encryption passkey (required if manifest says encrypted)

    Returns:
        Tuple of (list of account dicts, list of error messages)
    """
    folder_path = Path(folder_path)
    manifest = read_sda_manifest(folder_path)
    accounts = []
    errors = []

    if manifest is None:
        errors.append("No valid SDA manifest.json found")
        return accounts, errors

    is_encrypted = manifest.get("encrypted", False)
    if is_encrypted and not passkey:
        errors.append("Manifest is encrypted but no passkey provided")
        return accounts, errors

    entries = manifest.get("entries", [])
    if not entries:
        errors.append("No account entries in manifest")
        return accounts, errors

    for entry in entries:
        filename = entry.get("filename", "")
        steamid = entry.get("steamid")
        salt = entry.get("encryption_salt")
        iv = entry.get("encryption_iv")

        file_path = folder_path / filename
        if not file_path.exists():
            errors.append(f"File not found: {filename}")
            continue

        try:
            file_content = file_path.read_text(encoding='utf-8').strip()

            if is_encrypted:
                if not salt or not iv:
                    errors.append(f"Missing salt/IV for {filename}")
                    continue
                decrypted = decrypt_sda_data(passkey, salt, iv, file_content)
                if decrypted is None:
                    errors.append(f"Failed to decrypt {filename} (bad passkey?)")
                    continue
                account_data = json.loads(decrypted)
            else:
                account_data = json.loads(file_content)

            accounts.append(account_data)

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {filename}: {e}")
        except Exception as e:
            errors.append(f"Error reading {filename}: {e}")

    return accounts, errors
