"""
Pure Python implementation of Steam's protobuf authentication
Based on steamguard-cli's working implementation
"""
import base64
import struct
import io
from typing import Dict, Any, Optional, List, Union


class ProtobufWriter:
    """Simple protobuf writer for Steam authentication messages"""
    
    def __init__(self):
        self.buffer = io.BytesIO()
    
    def write_varint(self, value: int):
        """Write a variable-length integer"""
        while value >= 0x80:
            self.buffer.write(bytes([value & 0x7F | 0x80]))
            value >>= 7
        self.buffer.write(bytes([value & 0x7F]))
    
    def write_field(self, field_number: int, wire_type: int, value: Union[int, str, bytes]):
        """Write a protobuf field"""
        tag = (field_number << 3) | wire_type
        self.write_varint(tag)
        
        if wire_type == 0:  # Varint
            self.write_varint(value)
        elif wire_type == 1:  # Fixed64
            self.buffer.write(struct.pack('<Q', value))
        elif wire_type == 2:  # Length-delimited (string/bytes)
            if isinstance(value, str):
                value = value.encode('utf-8')
            self.write_varint(len(value))
            self.buffer.write(value)
        elif wire_type == 5:  # Fixed32
            self.buffer.write(struct.pack('<I', value))
    
    def write_string(self, field_number: int, value: str):
        """Write a string field"""
        if value:
            self.write_field(field_number, 2, value)
    
    def write_uint64(self, field_number: int, value: int):
        """Write a uint64 field"""
        # Always write uint64 values, even if they're 0
        self.write_field(field_number, 0, value)
    
    def write_fixed64(self, field_number: int, value: int):
        """Write a fixed64 field"""
        # Always write fixed64 values, even if they're 0
        self.write_field(field_number, 1, value)
    
    def write_bool(self, field_number: int, value: bool):
        """Write a boolean field"""
        if value:
            self.write_field(field_number, 0, 1)
    
    def write_enum(self, field_number: int, value: int):
        """Write an enum field"""
        # Don't skip zero values for enums - they can be valid
        self.write_field(field_number, 0, value)
    
    def get_bytes(self) -> bytes:
        """Get the serialized protobuf bytes"""
        return self.buffer.getvalue()


class ProtobufReader:
    """Simple protobuf reader for Steam authentication responses"""
    
    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)
        self.fields = {}
        self._parse()
    
    def read_varint(self) -> int:
        """Read a variable-length integer"""
        result = 0
        shift = 0
        while True:
            byte_data = self.buffer.read(1)
            if not byte_data:
                break
            byte_val = byte_data[0]
            result |= (byte_val & 0x7F) << shift
            if (byte_val & 0x80) == 0:
                break
            shift += 7
        return result
    
    def _parse(self):
        """Parse the protobuf data"""
        while True:
            try:
                tag = self.read_varint()
                if tag == 0:
                    break
                
                field_number = tag >> 3
                wire_type = tag & 0x7
                
                if wire_type == 0:  # Varint
                    value = self.read_varint()
                elif wire_type == 1:  # Fixed64
                    data = self.buffer.read(8)
                    if len(data) == 8:
                        value = struct.unpack('<Q', data)[0]
                    else:
                        continue
                elif wire_type == 2:  # Length-delimited
                    length = self.read_varint()
                    value = self.buffer.read(length)
                    # Try to decode as string
                    try:
                        value = value.decode('utf-8')
                    except:
                        pass  # Keep as bytes
                elif wire_type == 5:  # Fixed32
                    data = self.buffer.read(4)
                    if len(data) == 4:
                        value = struct.unpack('<I', data)[0]
                    else:
                        continue
                else:
                    # Skip unknown wire types
                    continue
                
                self.fields[field_number] = value
            except:
                break
    
    def get_string(self, field_number: int) -> str:
        """Get a string field"""
        return self.fields.get(field_number, "")
    
    def get_uint64(self, field_number: int) -> int:
        """Get a uint64 field"""
        return self.fields.get(field_number, 0)
    
    def get_bytes(self, field_number: int) -> bytes:
        """Get a bytes field"""
        value = self.fields.get(field_number, b"")
        if isinstance(value, str):
            return value.encode('utf-8')
        return value


class SteamProtobufAuth:
    """Steam authentication using protobuf messages"""
    
    # Enums from steamguard-cli
    PLATFORM_TYPE_MOBILE = 3
    SESSION_GUARD_TYPE_DEVICE_CODE = 3
    SESSION_PERSISTENCE_PERSISTENT = 1
    
    def __init__(self):
        self.base_url = "https://api.steampowered.com"
    
    def create_rsa_request(self, account_name: str) -> bytes:
        """Create GetPasswordRSAPublicKey request"""
        writer = ProtobufWriter()
        writer.write_string(1, account_name)  # account_name field
        return writer.get_bytes()
    
    def create_auth_request(self, account_name: str, encrypted_password: str, 
                          encryption_timestamp: int, device_name: str) -> bytes:
        """Create BeginAuthSessionViaCredentials request"""
        writer = ProtobufWriter()
        writer.write_string(1, device_name)  # device_friendly_name
        writer.write_string(2, account_name)  # account_name
        writer.write_string(3, encrypted_password)  # encrypted_password
        writer.write_uint64(4, encryption_timestamp)  # encryption_timestamp
        writer.write_bool(5, True)  # remember_login (deprecated but still set)
        writer.write_enum(6, self.PLATFORM_TYPE_MOBILE)  # platform_type
        writer.write_enum(7, self.SESSION_PERSISTENCE_PERSISTENT)  # persistence
        writer.write_string(8, "Mobile")  # website_id
        writer.write_uint64(11, 0)  # language (0 = English)
        writer.write_enum(12, 2)  # qos_level (2 = default priority)
        return writer.get_bytes()
    
    def create_steamguard_request(self, client_id: int, steamid: int, code: str) -> bytes:
        """Create UpdateAuthSessionWithSteamGuardCode request"""
        writer = ProtobufWriter()
        writer.write_uint64(1, client_id)  # client_id
        writer.write_fixed64(2, steamid)  # steamid - MUST be fixed64!
        writer.write_string(3, code)  # code
        writer.write_enum(4, self.SESSION_GUARD_TYPE_DEVICE_CODE)  # code_type
        writer.write_bool(7, True)  # persistence (field 7)
        writer.write_enum(11, 0)  # language = 0 (English)
        writer.write_enum(12, 2)  # qos_level = 2 (default priority)
        return writer.get_bytes()
    
    def create_poll_request(self, client_id: int, request_id: bytes) -> bytes:
        """Create PollAuthSessionStatus request"""
        writer = ProtobufWriter()
        writer.write_uint64(1, client_id)  # client_id
        writer.write_field(2, 2, request_id)  # request_id (bytes)
        return writer.get_bytes()
    
    def create_refresh_token_request(self, refresh_token: str, steamid: int) -> bytes:
        """Create GenerateAccessTokenForApp request"""
        writer = ProtobufWriter()
        writer.write_string(1, refresh_token)  # refresh_token
        writer.write_fixed64(2, steamid)  # steamid - fixed64 in protobuf definition
        return writer.get_bytes()
    
    def parse_rsa_response(self, data: bytes) -> Dict[str, Any]:
        """Parse GetPasswordRSAPublicKey response"""
        reader = ProtobufReader(data)
        return {
            "publickey_mod": reader.get_string(1),
            "publickey_exp": reader.get_string(2),
            "timestamp": reader.get_uint64(3)
        }
    
    def parse_auth_response(self, data: bytes) -> Dict[str, Any]:
        """Parse BeginAuthSessionViaCredentials response"""
        reader = ProtobufReader(data)
        return {
            "client_id": reader.get_uint64(1),
            "request_id": reader.get_bytes(2),
            "interval": reader.get_uint64(3),
            "steamid": reader.get_uint64(5),  # steamid in response is uint64
            "weak_token": reader.get_string(6)
        }
    
    def parse_poll_response(self, data: bytes) -> Dict[str, Any]:
        """Parse PollAuthSessionStatus response"""
        reader = ProtobufReader(data)
        return {
            "refresh_token": reader.get_string(3),
            "access_token": reader.get_string(4),
            "had_remote_interaction": bool(reader.get_uint64(5)),
            "account_name": reader.get_string(6),
            "new_guard_data": reader.get_string(7)
        }
    
    def parse_refresh_response(self, data: bytes) -> Dict[str, Any]:
        """Parse GenerateAccessTokenForApp response"""
        reader = ProtobufReader(data)
        return {
            "access_token": reader.get_string(1),
            "refresh_token": reader.get_string(2)
        }