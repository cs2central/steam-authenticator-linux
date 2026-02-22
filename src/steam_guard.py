import base64
import hashlib
import hmac
import json
import time
from typing import Optional, Dict, Any
from pathlib import Path
import secrets
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SteamGuardAccount:
    STEAM_GUARD_CODE_CHARS = "23456789BCDFGHJKMNPQRTVWXY"

    def __init__(self, account_data: Optional[Dict[str, Any]] = None):
        if account_data:
            self.account_name = account_data.get("account_name", "")
            self.shared_secret = account_data.get("shared_secret", "")
            self.identity_secret = account_data.get("identity_secret", "")
            self.device_id = account_data.get("device_id", "")

            # Handle different Steam ID formats
            self.steamid = self._extract_steamid(account_data)

            # Handle different session formats
            self.session_data = self._extract_session_data(account_data)

            # SDA legacy fields (preserved for compatibility)
            self.revocation_code = account_data.get("revocation_code", "")
            self.serial_number = account_data.get("serial_number", "")
            self.uri = account_data.get("uri", "")
            self.server_time = account_data.get("server_time", "")
            self.token_gid = account_data.get("token_gid", "")

            # Profile data (fetched from Steam Web API)
            self.avatar_url = account_data.get("avatar_url", "")
            self.display_name = account_data.get("display_name", "")
            self.total_games = account_data.get("total_games", 0)
            self.vac_banned = account_data.get("vac_banned", False)
            self.trade_banned = account_data.get("trade_banned", False)
            self.game_bans = account_data.get("game_bans", 0)
            self.profile_visibility = account_data.get("profile_visibility", 0)
            self.last_api_refresh = account_data.get("last_api_refresh", "")
        else:
            self.account_name = ""
            self.shared_secret = ""
            self.identity_secret = ""
            self.device_id = self.generate_device_id()
            self.steamid = ""
            self.session_data = {}
            # SDA legacy fields
            self.revocation_code = ""
            self.serial_number = ""
            self.uri = ""
            self.server_time = ""
            self.token_gid = ""
            # Profile data defaults
            self.avatar_url = ""
            self.display_name = ""
            self.total_games = 0
            self.vac_banned = False
            self.trade_banned = False
            self.game_bans = 0
            self.profile_visibility = 0
            self.last_api_refresh = ""
    
    def _extract_steamid(self, account_data: Dict[str, Any]) -> str:
        """Extract Steam ID from various possible locations in the account data"""
        # Try direct steamid field first
        steamid = account_data.get("steamid", "")
        if steamid:
            return str(steamid)
        
        # Try Session.SteamID (from Windows Steam Desktop Authenticator)
        session = account_data.get("Session", {})
        if session and "SteamID" in session:
            return str(session["SteamID"])
        
        # Try session.steamid (our format)
        session_alt = account_data.get("session", {})
        if session_alt and "steamid" in session_alt:
            return str(session_alt["steamid"])
        
        return ""
    
    def _extract_session_data(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and normalize session data from various formats"""
        session_data = {}
        
        # Check for Windows Steam Desktop Authenticator format
        windows_session = account_data.get("Session", {})
        if windows_session:
            # Convert Windows format to our format
            if "AccessToken" in windows_session:
                session_data["access_token"] = windows_session["AccessToken"]
            if "RefreshToken" in windows_session:
                session_data["refresh_token"] = windows_session["RefreshToken"]
            if "SessionID" in windows_session:
                session_data["session_id"] = windows_session["SessionID"]
        
        # Check for our format
        our_session = account_data.get("session", {})
        if our_session:
            session_data.update(our_session)
        
        return session_data
    
    def check_token_expiration(self) -> Dict[str, Any]:
        """Check if tokens in session data are expired"""
        result = {
            "access_token_valid": False,
            "refresh_token_valid": False,
            "access_token_expires": None,
            "refresh_token_expires": None
        }
        
        def decode_jwt_payload(token: str) -> Optional[Dict]:
            try:
                parts = token.split('.')
                if len(parts) == 3:
                    payload = parts[1]
                    # Add padding if needed
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.b64decode(payload)
                    return json.loads(decoded)
            except:
                pass
            return None
        
        # Check access token
        access_token = self.session_data.get("access_token", "")
        if access_token:
            access_payload = decode_jwt_payload(access_token)
            if access_payload and 'exp' in access_payload:
                exp_time = datetime.fromtimestamp(access_payload['exp'])
                result["access_token_expires"] = exp_time
                result["access_token_valid"] = exp_time > datetime.now()
        
        # Check refresh token
        refresh_token = self.session_data.get("refresh_token", "")
        if refresh_token:
            refresh_payload = decode_jwt_payload(refresh_token)
            if refresh_payload and 'exp' in refresh_payload:
                exp_time = datetime.fromtimestamp(refresh_payload['exp'])
                result["refresh_token_expires"] = exp_time
                result["refresh_token_valid"] = exp_time > datetime.now()
        
        return result
    
    @staticmethod
    def generate_device_id() -> str:
        """Generate a random Android-style device ID"""
        return f"android:{secrets.token_hex(8)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(6)}"
    
    def generate_steam_guard_code(self, timestamp: Optional[int] = None) -> str:
        """Generate a Steam Guard code for the given timestamp"""
        if not self.shared_secret:
            return ""
        
        if timestamp is None:
            timestamp = int(time.time())
        
        # Steam uses 30-second intervals
        time_bytes = (timestamp // 30).to_bytes(8, byteorder='big')
        
        # Decode the shared secret from base64
        secret = base64.b64decode(self.shared_secret)
        
        # Generate HMAC
        hmac_obj = hmac.new(secret, time_bytes, hashlib.sha1)
        hash_bytes = hmac_obj.digest()
        
        # Get the offset from the last nibble
        offset = hash_bytes[19] & 0xF
        
        # Get 4 bytes starting at the offset
        code_int = int.from_bytes(hash_bytes[offset:offset + 4], byteorder='big') & 0x7FFFFFFF
        
        # Generate 5-character code using Steam's character set
        code = ""
        for _ in range(5):
            code += self.STEAM_GUARD_CODE_CHARS[code_int % len(self.STEAM_GUARD_CODE_CHARS)]
            code_int //= len(self.STEAM_GUARD_CODE_CHARS)
        
        return code
    
    def get_time_until_next_code(self) -> int:
        """Get seconds until the next code"""
        return 30 - (int(time.time()) % 30)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert account to dictionary for storage"""
        data = {
            "account_name": self.account_name,
            "shared_secret": self.shared_secret,
            "identity_secret": self.identity_secret,
            "device_id": self.device_id,
            "steamid": self.steamid,
            "session": self.session_data,
            # Profile data from Steam Web API
            "avatar_url": self.avatar_url,
            "display_name": self.display_name,
            "total_games": self.total_games,
            "vac_banned": self.vac_banned,
            "trade_banned": self.trade_banned,
            "game_bans": self.game_bans,
            "profile_visibility": self.profile_visibility,
            "last_api_refresh": self.last_api_refresh,
        }
        # Include SDA legacy fields if present (for round-trip compatibility)
        if self.revocation_code:
            data["revocation_code"] = self.revocation_code
        if self.serial_number:
            data["serial_number"] = self.serial_number
        if self.uri:
            data["uri"] = self.uri
        if self.server_time:
            data["server_time"] = self.server_time
        if self.token_gid:
            data["token_gid"] = self.token_gid
        return data

    def get_display_name_or_username(self) -> str:
        """Get display name if available, otherwise account name"""
        if self.display_name:
            # Sanitize: strip control characters, limit length
            sanitized = ''.join(c for c in self.display_name if c.isprintable())
            sanitized = sanitized.strip()
            if sanitized:
                return sanitized[:64]
        return self.account_name if self.account_name else "Unknown"

    def get_avatar_initial(self) -> str:
        """Get the first character of display name or account name for avatar fallback"""
        name = self.display_name if self.display_name else self.account_name
        if name:
            # Find first alphanumeric character
            for c in name:
                if c.isalnum():
                    return c.upper()
        return "?"


class Manifest:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.encryption_key = None
        self.accounts = []
        self.load()
    
    @staticmethod
    def generate_salt() -> str:
        """Generate a cryptographically random salt (32 bytes, base64-encoded)."""
        return base64.b64encode(secrets.token_bytes(32)).decode()

    @staticmethod
    def derive_key(password: str, salt_b64: str) -> bytes:
        """Derive a 32-byte AES-256 key from password + salt using PBKDF2-HMAC-SHA256."""
        salt = base64.b64decode(salt_b64)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        return kdf.derive(password.encode())

    @staticmethod
    def encrypt_data(data: str, password: str, salt_b64: str) -> str:
        """Encrypt data with AES-256-GCM. Returns base64(nonce + ciphertext + tag)."""
        key = Manifest.derive_key(password, salt_b64)
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(12)  # 96-bit nonce for GCM
        ciphertext = aesgcm.encrypt(nonce, data.encode('utf-8'), None)
        # Concatenate nonce + ciphertext (which includes the 16-byte tag)
        return base64.b64encode(nonce + ciphertext).decode()

    @staticmethod
    def decrypt_data(encrypted_b64: str, password: str, salt_b64: str) -> str:
        """Decrypt AES-256-GCM encrypted data. Input is base64(nonce + ciphertext + tag)."""
        key = Manifest.derive_key(password, salt_b64)
        raw = base64.b64decode(encrypted_b64)
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')

    @staticmethod
    def _legacy_derive_key(password: str) -> bytes:
        """Legacy key derivation (fixed salt, Fernet). Used only for migration."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'steam_auth_linux',
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    @staticmethod
    def _legacy_decrypt(encrypted_data: str, password: str) -> Optional[str]:
        """Decrypt data encrypted with the legacy Fernet scheme. For migration only."""
        try:
            from cryptography.fernet import Fernet
            key = Manifest._legacy_derive_key(password)
            f = Fernet(key)
            return f.decrypt(encrypted_data.encode()).decode()
        except Exception:
            return None
    
    def load(self, password: Optional[str] = None):
        """Load manifest from file. If encrypted, password is required."""
        if not self.manifest_path.exists():
            self.save()
            return

        try:
            with open(self.manifest_path, 'r') as f:
                data = json.load(f)

            if data.get("encrypted", False):
                if not password:
                    # Caller must provide password to load encrypted manifest
                    self.accounts = []
                    return

                salt = data.get("encryption_salt", "")
                encrypted_accounts = data.get("accounts_encrypted", "")
                legacy_accounts = data.get("accounts", [])

                if encrypted_accounts and salt:
                    # New AES-256-GCM format
                    try:
                        decrypted_json = self.decrypt_data(encrypted_accounts, password, salt)
                        accounts_data = json.loads(decrypted_json)
                        self.accounts = [SteamGuardAccount(a) for a in accounts_data]
                        self.encryption_key = password
                        return
                    except Exception:
                        pass

                # Try legacy Fernet decryption for backward compatibility
                if legacy_accounts and isinstance(legacy_accounts, str):
                    decrypted = self._legacy_decrypt(legacy_accounts, password)
                    if decrypted:
                        accounts_data = json.loads(decrypted)
                        self.accounts = [SteamGuardAccount(a) for a in accounts_data]
                        self.encryption_key = password
                        # Migrate to new format on next save
                        self.save(password)
                        return

                self.accounts = []
            else:
                # Unencrypted — load accounts directly
                self.accounts = []
                for account_data in data.get("accounts", []):
                    account = SteamGuardAccount(account_data)
                    self.accounts.append(account)
        except Exception as e:
            print(f"Error loading manifest: {e}")
            self.accounts = []

    def save(self, password: Optional[str] = None):
        """Save manifest to file. If password provided, encrypts account data."""
        password = password or self.encryption_key

        if password:
            # Read existing salt or generate new one
            salt = None
            if self.manifest_path.exists():
                try:
                    with open(self.manifest_path, 'r') as f:
                        existing = json.load(f)
                    salt = existing.get("encryption_salt")
                except Exception:
                    pass

            if not salt:
                salt = self.generate_salt()

            accounts_json = json.dumps([account.to_dict() for account in self.accounts])
            encrypted = self.encrypt_data(accounts_json, password, salt)

            data = {
                "encrypted": True,
                "encryption_salt": salt,
                "accounts_encrypted": encrypted,
                "accounts": []
            }
        else:
            data = {
                "encrypted": False,
                "accounts": [account.to_dict() for account in self.accounts]
            }

        with open(self.manifest_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_account(self, account: SteamGuardAccount):
        """Add account to manifest"""
        # Remove existing account with same name
        self.accounts = [a for a in self.accounts if a.account_name != account.account_name]
        self.accounts.append(account)
        self.save(self.encryption_key)

    def remove_account(self, account_name: str):
        """Remove account from manifest"""
        self.accounts = [a for a in self.accounts if a.account_name != account_name]
        self.save(self.encryption_key)
    
    def get_account(self, account_name: str) -> Optional[SteamGuardAccount]:
        """Get account by name"""
        for account in self.accounts:
            if account.account_name == account_name:
                return account
        return None