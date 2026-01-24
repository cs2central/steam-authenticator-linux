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
            # Generate authenticator code from shared_secret
            auth_code = self._generate_auth_code(shared_secret, server_time)

            # Calculate time for request
            auth_time = server_time // 30

            # Build request
            request_data = self._build_finalize_request(auth_code, auth_time, sms_code)

            # Try up to 30 times (Steam may request multiple codes)
            for attempt in range(30):
                response = await self._send_twofactor_request(
                    "FinalizeAddAuthenticator", 1, request_data
                )

                if not response:
                    return {"error": "No response from Steam"}

                result = self._parse_finalize_response(response)

                if result.get("status") != 1:
                    if result.get("status") == 89:  # BadSMSCode
                        return {"error": "bad_code", "message": "Invalid SMS/email code"}
                    return {"error": "steam_error", "message": f"Steam error: {result.get('status')}"}

                if result.get("success"):
                    return {"success": True}

                if result.get("want_more"):
                    # Steam wants another code, update server_time and retry
                    server_time = result.get("server_time", server_time + 30)
                    auth_code = self._generate_auth_code(shared_secret, server_time)
                    auth_time = server_time // 30
                    request_data = self._build_finalize_request(auth_code, auth_time, sms_code)
                    await asyncio.sleep(0.5)
                    continue

                break

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
        """Build protobuf request for AddAuthenticator"""
        # Simple protobuf encoding
        data = b""
        # Field 1: steamid (uint64)
        data += b"\x08" + self._encode_varint(self.steamid)
        # Field 2: authenticator_type = 1 (uint32)
        data += b"\x10\x01"
        # Field 3: device_identifier (string)
        device_bytes = self.device_id.encode('utf-8')
        data += b"\x1a" + self._encode_varint(len(device_bytes)) + device_bytes
        # Field 4: sms_phone_id = "1" (string)
        data += b"\x22\x01\x31"
        # Field 7: version = 2 (uint32)
        data += b"\x38\x02"
        return data

    def _build_finalize_request(self, auth_code: str, auth_time: int, sms_code: str) -> bytes:
        """Build protobuf request for FinalizeAddAuthenticator"""
        data = b""
        # Field 1: steamid (uint64)
        data += b"\x08" + self._encode_varint(self.steamid)
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
        # Field 1: steamid (uint64)
        data += b"\x08" + self._encode_varint(self.steamid)
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
        result = {}
        pos = 0

        while pos < len(data):
            if pos >= len(data):
                break

            # Read field tag
            tag_byte = data[pos]
            field_num = tag_byte >> 3
            wire_type = tag_byte & 0x07
            pos += 1

            if wire_type == 0:  # Varint
                value, pos = self._decode_varint(data, pos)
                if field_num == 1:
                    result["status"] = value
                elif field_num == 5:
                    result["server_time"] = value
                elif field_num == 12:
                    result["confirm_type"] = value
            elif wire_type == 2:  # Length-delimited
                length, pos = self._decode_varint(data, pos)
                value = data[pos:pos+length]
                pos += length

                if field_num == 2:
                    result["shared_secret"] = base64.b64encode(value).decode('utf-8')
                elif field_num == 3:
                    result["serial_number"] = value.decode('utf-8')
                elif field_num == 4:
                    result["revocation_code"] = value.decode('utf-8')
                elif field_num == 6:
                    result["token_gid"] = value.decode('utf-8')
                elif field_num == 7:
                    result["identity_secret"] = base64.b64encode(value).decode('utf-8')
                elif field_num == 9:
                    result["account_name"] = value.decode('utf-8')
                elif field_num == 11:
                    result["phone_number_hint"] = value.decode('utf-8')
                elif field_num == 8:
                    result["uri"] = value.decode('utf-8')
            else:
                # Skip unknown wire types
                break

        return result

    def _parse_finalize_response(self, data: bytes) -> Dict[str, Any]:
        """Parse FinalizeAddAuthenticator response"""
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
                    result["status"] = value
                elif field_num == 2:
                    result["server_time"] = value
                elif field_num == 3:
                    result["want_more"] = value == 1
                elif field_num == 4:
                    result["success"] = value == 1
            else:
                break

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
            async with self.session.post(url, data=form_data, headers=headers) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    logging.error(f"Steam API error: {response.status}")
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
