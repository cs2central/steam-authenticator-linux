"""
Steam Account Linker - Links new Steam accounts to the authenticator
Based on steamguard-cli implementation
"""
import asyncio
import aiohttp
import base64
import uuid
import time
import logging
import struct
import hmac
import hashlib
from typing import Dict, Any, Optional
from steam_protobuf import SteamProtobufAuth
from steam_protobuf_login import SteamProtobufLogin


class AccountLinker:
    """Links a new Steam account to generate 2FA secrets"""

    def __init__(self):
        self.session = None
        self.protobuf = SteamProtobufAuth()
        self.device_id = f"android:{uuid.uuid4()}"
        self.access_token = None
        self.steamid = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def set_tokens(self, access_token: str, steamid: int):
        """Set the access token and steamid from login"""
        self.access_token = access_token
        self.steamid = steamid

    async def add_authenticator(self) -> Dict[str, Any]:
        """
        Step 1: Request to add authenticator to account
        Returns the secrets if successful, or error info
        """
        if not self.access_token or not self.steamid:
            return {"error": "Not logged in"}

        try:
            # Build the protobuf request for AddAuthenticator
            request_data = self._build_add_authenticator_request()

            # Send request
            response = await self._send_twofactor_request(
                "AddAuthenticator", 1, request_data
            )

            if not response:
                return {"error": "No response from Steam"}

            # Parse response
            result = self._parse_add_authenticator_response(response)

            if result.get("status") == 29:  # AuthenticatorPresent
                return {"error": "authenticator_present", "message": "Account already has an authenticator"}
            elif result.get("status") == 2:  # MustProvidePhoneNumber
                return {"error": "no_phone", "message": "Account needs a phone number"}
            elif result.get("status") == 84:  # MustConfirmEmail
                return {"error": "confirm_email", "message": "Please confirm the email Steam sent you, then try again"}
            elif result.get("status") != 1:  # Not OK
                return {"error": "steam_error", "message": f"Steam error code: {result.get('status')}"}

            return {
                "success": True,
                "shared_secret": result.get("shared_secret"),
                "identity_secret": result.get("identity_secret"),
                "revocation_code": result.get("revocation_code"),
                "serial_number": result.get("serial_number"),
                "token_gid": result.get("token_gid"),
                "account_name": result.get("account_name"),
                "uri": result.get("uri"),
                "server_time": result.get("server_time"),
                "phone_number_hint": result.get("phone_number_hint"),
                "confirm_type": result.get("confirm_type", 1),  # 1=SMS, 3=Email
            }

        except Exception as e:
            logging.error(f"AddAuthenticator error: {e}")
            return {"error": "exception", "message": str(e)}

    async def finalize_authenticator(self, sms_code: str, shared_secret: str, server_time: int) -> Dict[str, Any]:
        """
        Step 2: Finalize the authenticator with SMS/email code
        May need to be called multiple times if Steam requests more codes
        """
        if not self.access_token or not self.steamid:
            return {"error": "Not logged in"}

        try:
            # Try up to 30 times (Steam may request multiple codes)
            for attempt in range(30):
                # Generate authenticator code for the current server_time
                auth_code = self._generate_auth_code(shared_secret, server_time)

                # Build request with absolute timestamp (not divided by 30)
                request_data = self._build_finalize_request(auth_code, server_time, sms_code)

                logging.debug(f"Finalize attempt {attempt+1}, server_time={server_time}, code={auth_code}")

                response = await self._send_twofactor_request(
                    "FinalizeAddAuthenticator", 1, request_data
                )

                if not response:
                    return {"error": "No response from Steam"}

                result = self._parse_finalize_response(response)
                logging.debug(f"Finalize response: {result}")

                if result.get("success"):
                    return {"success": True}

                status = result.get("status", 0)
                if status == 89:  # BadSMSCode
                    return {"error": "bad_code", "message": "Invalid SMS/email code"}
                elif status != 0 and status != 1:
                    return {"error": "steam_error", "message": f"Steam error: {status}"}

                # Not yet successful, try with updated server_time
                new_server_time = result.get("server_time", 0)
                if new_server_time > 0:
                    server_time = new_server_time
                else:
                    server_time += 30
                await asyncio.sleep(0.5)
                continue

            return {"error": "timeout", "message": "Too many attempts, please try again"}

        except Exception as e:
            logging.error(f"FinalizeAuthenticator error: {e}")
            return {"error": "exception", "message": str(e)}

    async def query_status(self) -> Dict[str, Any]:
        """Check if authenticator is active"""
        try:
            request_data = self._build_status_request()
            response = await self._send_twofactor_request("QueryStatus", 1, request_data)

            if response:
                result = self._parse_status_response(response)
                return {"active": result.get("state", 0) > 0}

            return {"active": False}
        except Exception as e:
            logging.error(f"QueryStatus error: {e}")
            return {"active": False}

    def _generate_auth_code(self, shared_secret: str, server_time: int) -> str:
        """Generate a Steam Guard code from shared_secret"""
        # Steam's character set for codes
        chars = "23456789BCDFGHJKMNPQRTVWXY"

        # Decode the shared secret
        secret = base64.b64decode(shared_secret)

        # Calculate time interval
        time_bytes = (server_time // 30).to_bytes(8, byteorder='big')

        # Generate HMAC-SHA1
        mac = hmac.new(secret, time_bytes, hashlib.sha1)
        digest = mac.digest()

        # Get offset from last nibble
        offset = digest[19] & 0x0F

        # Extract 4 bytes and convert to code
        code_int = int.from_bytes(digest[offset:offset+4], byteorder='big') & 0x7FFFFFFF

        # Generate 5 character code
        code = ""
        for _ in range(5):
            code += chars[code_int % len(chars)]
            code_int //= len(chars)

        return code

    def _build_add_authenticator_request(self) -> bytes:
        """Build protobuf request for AddAuthenticator

        Proto definition (CTwoFactor_AddAuthenticator_Request):
            field 1: steamid (fixed64)
            field 4: authenticator_type (uint32)
            field 5: device_identifier (string)
            field 8: version (uint32)
        """
        data = b""
        # Field 1: steamid (fixed64, wire type 1, tag = (1 << 3) | 1 = 0x09)
        data += b"\x09" + struct.pack('<Q', self.steamid)
        # Field 4: authenticator_type = 1 (uint32, wire type 0, tag = (4 << 3) | 0 = 0x20)
        data += b"\x20\x01"
        # Field 5: device_identifier (string, wire type 2, tag = (5 << 3) | 2 = 0x2a)
        device_bytes = self.device_id.encode('utf-8')
        data += b"\x2a" + self._encode_varint(len(device_bytes)) + device_bytes
        # Field 8: version = 2 (uint32, wire type 0, tag = (8 << 3) | 0 = 0x40)
        data += b"\x40\x02"
        return data

    def _build_finalize_request(self, auth_code: str, auth_time: int, sms_code: str) -> bytes:
        """Build protobuf request for FinalizeAddAuthenticator"""
        data = b""
        # Field 1: steamid (fixed64, wire type 1)
        data += b"\x09" + struct.pack('<Q', self.steamid)
        # Field 2: authenticator_code (string)
        code_bytes = auth_code.encode('utf-8')
        data += b"\x12" + self._encode_varint(len(code_bytes)) + code_bytes
        # Field 3: authenticator_time (uint64)
        data += b"\x18" + self._encode_varint(auth_time)
        # Field 4: activation_code (string) - the SMS code
        sms_bytes = sms_code.encode('utf-8')
        data += b"\x22" + self._encode_varint(len(sms_bytes)) + sms_bytes
        # Field 6: validate_sms_code = true (bool)
        data += b"\x30\x01"
        return data

    def _build_status_request(self) -> bytes:
        """Build protobuf request for QueryStatus"""
        data = b""
        # Field 1: steamid (fixed64, wire type 1)
        data += b"\x09" + struct.pack('<Q', self.steamid)
        return data

    def _encode_varint(self, value: int) -> bytes:
        """Encode an integer as a protobuf varint"""
        result = b""
        while value > 127:
            result += bytes([(value & 0x7F) | 0x80])
            value >>= 7
        result += bytes([value & 0x7F])
        return result

    def _parse_add_authenticator_response(self, data: bytes) -> Dict[str, Any]:
        """Parse AddAuthenticator response"""
        """Parse based on CTwoFactor_AddAuthenticator_Response proto:
            field 1: shared_secret (bytes)
            field 2: serial_number (fixed64)
            field 3: revocation_code (string)
            field 4: uri (string)
            field 5: server_time (uint64)
            field 6: account_name (string)
            field 7: token_gid (string)
            field 8: identity_secret (bytes)
            field 9: secret_1 (bytes)
            field 10: status (int32)
            field 11: phone_number_hint (string)
            field 12: confirm_type (int32)
        """
        result = {}
        pos = 0

        while pos < len(data):
            tag, pos = self._decode_varint(data, pos)
            if tag == 0:
                break
            field_num = tag >> 3
            wire_type = tag & 0x07

            if wire_type == 0:  # Varint
                value, pos = self._decode_varint(data, pos)
                if field_num == 5:
                    result["server_time"] = value
                elif field_num == 10:
                    result["status"] = value
                elif field_num == 12:
                    result["confirm_type"] = value
            elif wire_type == 1:  # Fixed64
                value = struct.unpack('<Q', data[pos:pos+8])[0]
                pos += 8
                if field_num == 2:
                    result["serial_number"] = value
            elif wire_type == 2:  # Length-delimited (bytes or string)
                length, pos = self._decode_varint(data, pos)
                value = data[pos:pos+length]
                pos += length

                if field_num == 1:
                    result["shared_secret"] = base64.b64encode(value).decode('utf-8')
                elif field_num == 3:
                    result["revocation_code"] = value.decode('utf-8', errors='replace')
                elif field_num == 4:
                    result["uri"] = value.decode('utf-8', errors='replace')
                elif field_num == 6:
                    result["account_name"] = value.decode('utf-8', errors='replace')
                elif field_num == 7:
                    result["token_gid"] = value.decode('utf-8', errors='replace')
                elif field_num == 8:
                    result["identity_secret"] = base64.b64encode(value).decode('utf-8')
                elif field_num == 11:
                    result["phone_number_hint"] = value.decode('utf-8', errors='replace')
            elif wire_type == 5:  # Fixed32
                pos += 4
            else:
                continue

        return result

    def _parse_finalize_response(self, data: bytes) -> Dict[str, Any]:
        """Parse FinalizeAddAuthenticator response

        Proto definition (CTwoFactor_FinalizeAddAuthenticator_Response):
            field 1: success (bool)
            field 3: server_time (uint64)
            field 4: status (int32)
        """
        result = {"success": False, "status": 0, "server_time": 0}
        pos = 0

        while pos < len(data):
            if pos >= len(data):
                break

            tag, pos = self._decode_varint(data, pos)
            if tag == 0:
                break
            field_num = tag >> 3
            wire_type = tag & 0x07

            if wire_type == 0:  # Varint
                value, pos = self._decode_varint(data, pos)
                if field_num == 1:
                    result["success"] = value == 1
                elif field_num == 3:
                    result["server_time"] = value
                elif field_num == 4:
                    result["status"] = value
            elif wire_type == 2:  # Length-delimited (skip)
                length, pos = self._decode_varint(data, pos)
                pos += length
            elif wire_type == 1:  # Fixed64
                pos += 8
            elif wire_type == 5:  # Fixed32
                pos += 4
            else:
                continue

        return result

    def _parse_status_response(self, data: bytes) -> Dict[str, Any]:
        """Parse QueryStatus response"""
        result = {}
        pos = 0

        while pos < len(data):
            if pos >= len(data):
                break

            tag_byte = data[pos]
            field_num = tag_byte >> 3
            wire_type = tag_byte & 0x07
            pos += 1

            if wire_type == 0:  # Varint
                value, pos = self._decode_varint(data, pos)
                if field_num == 1:
                    result["state"] = value
            else:
                break

        return result

    def _decode_varint(self, data: bytes, pos: int) -> tuple:
        """Decode a protobuf varint"""
        result = 0
        shift = 0
        while pos < len(data):
            byte = data[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
        return result, pos

    async def _send_twofactor_request(self, method: str, version: int, data: bytes) -> Optional[bytes]:
        """Send a request to ITwoFactorService"""
        url = f"https://api.steampowered.com/ITwoFactorService/{method}/v{version}/"

        # Encode data as base64
        encoded_data = base64.b64encode(data).decode('ascii')

        form_data = aiohttp.FormData()
        form_data.add_field('input_protobuf_encoded', encoded_data)
        form_data.add_field('access_token', self.access_token)

        headers = {
            'User-Agent': 'steamguard-cli'
        }

        try:
            logging.debug(f"Sending {method} to {url}, protobuf hex: {data.hex()}")
            async with self.session.post(url, data=form_data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    body = await response.text()
                    logging.error(f"Steam API error: {response.status}, body: {body[:500]}")
                    return None
        except Exception as e:
            logging.error(f"Request error: {e}")
            return None


async def link_account(username: str, password: str, sms_callback) -> Dict[str, Any]:
    """
    Complete account linking flow

    sms_callback: async function that returns the SMS/email code entered by user

    Returns account data dict on success, or error dict on failure
    """
    # Step 1: Login to get access token
    async with SteamProtobufLogin() as login:
        login_result = await login.complete_login_flow(username, password)

        if login_result.get("error"):
            return {"error": "login_failed", "message": login_result.get("error")}

        if login_result.get("needs_2fa"):
            return {"error": "already_has_2fa", "message": "Account already has 2FA enabled. Use import instead."}

        if not login_result.get("success"):
            return {"error": "login_failed", "message": "Could not login to Steam"}

        access_token = login_result.get("access_token")
        if not access_token:
            return {"error": "token_error", "message": "No access token received"}
        # Extract steamid from JWT
        import json
        token_parts = access_token.split('.')
        if len(token_parts) >= 2:
            payload = json.loads(base64.b64decode(token_parts[1] + '=='))
            steamid = int(payload.get("sub", 0))
        else:
            return {"error": "token_error", "message": "Could not parse access token"}

    # Step 2: Add authenticator
    async with AccountLinker() as linker:
        linker.set_tokens(access_token, steamid)

        add_result = await linker.add_authenticator()

        if add_result.get("error"):
            return add_result

        # Store the secrets temporarily
        shared_secret = add_result.get("shared_secret")
        identity_secret = add_result.get("identity_secret")
        revocation_code = add_result.get("revocation_code")
        server_time = add_result.get("server_time", int(time.time()))

        # Step 3: Get SMS/email code from user
        sms_code = await sms_callback(add_result.get("phone_number_hint"), add_result.get("confirm_type"))

        if not sms_code:
            return {"error": "cancelled", "message": "Setup cancelled"}

        # Step 4: Finalize
        final_result = await linker.finalize_authenticator(sms_code, shared_secret, server_time)

        if final_result.get("error"):
            return final_result

        # Step 5: Verify status
        status = await linker.query_status()

        if not status.get("active"):
            return {"error": "not_active", "message": "Authenticator was not activated. Please try again."}

        # Success! Return account data
        return {
            "success": True,
            "account_name": username,
            "steamid": str(steamid),
            "shared_secret": shared_secret,
            "identity_secret": identity_secret,
            "revocation_code": revocation_code,
            "device_id": linker.device_id,
            "token_gid": add_result.get("token_gid"),
            "uri": add_result.get("uri"),
            "Session": {
                "access_token": access_token,
                "refresh_token": login_result.get("refresh_token", ""),
            }
        }
