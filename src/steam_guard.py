import base64
import hashlib
import hmac
import json
import time
from typing import Optional, Dict, Any
from pathlib import Path
import secrets
from datetime import datetime
from cryptography.fernet import Fernet
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
            
            self.avatar_url = account_data.get("avatar_url", "")
        else:
            self.account_name = ""
            self.shared_secret = ""
            self.identity_secret = ""
            self.device_id = self.generate_device_id()
            self.steamid = ""
            self.session_data = {}
            self.avatar_url = ""
    
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
        return {
            "account_name": self.account_name,
            "shared_secret": self.shared_secret,
            "identity_secret": self.identity_secret,
            "device_id": self.device_id,
            "steamid": self.steamid,
            "session": self.session_data,
            "avatar_url": self.avatar_url
        }


class Manifest:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.encryption_key = None
        self.accounts = []
        self.load()
    
    def generate_encryption_key(self, password: str) -> bytes:
        """Generate encryption key from password"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'steam_auth_linux',  # In production, use a random salt
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))
    
    def encrypt_data(self, data: str, password: str) -> str:
        """Encrypt data with password"""
        key = self.generate_encryption_key(password)
        f = Fernet(key)
        return f.encrypt(data.encode()).decode()
    
    def decrypt_data(self, encrypted_data: str, password: str) -> str:
        """Decrypt data with password"""
        key = self.generate_encryption_key(password)
        f = Fernet(key)
        return f.decrypt(encrypted_data.encode()).decode()
    
    def load(self):
        """Load manifest from file"""
        if not self.manifest_path.exists():
            self.save()
            return
        
        try:
            with open(self.manifest_path, 'r') as f:
                data = json.load(f)
                
            if data.get("encrypted", False):
                # Handle encrypted manifest
                pass
            else:
                # Load accounts
                self.accounts = []
                for account_data in data.get("accounts", []):
                    account = SteamGuardAccount(account_data)
                    self.accounts.append(account)
        except Exception as e:
            print(f"Error loading manifest: {e}")
            self.accounts = []
    
    def save(self):
        """Save manifest to file"""
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
        self.save()
    
    def remove_account(self, account_name: str):
        """Remove account from manifest"""
        self.accounts = [a for a in self.accounts if a.account_name != account_name]
        self.save()
    
    def get_account(self, account_name: str) -> Optional[SteamGuardAccount]:
        """Get account by name"""
        for account in self.accounts:
            if account.account_name == account_name:
                return account
        return None