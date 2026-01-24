"""
Steam login implementation using protobuf messages
Based on steamguard-cli's working authentication flow
"""
import asyncio
import aiohttp
import base64
import time
import logging
import secrets
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes
from steam_protobuf import SteamProtobufAuth


class SteamProtobufLogin:
    """Steam login using protobuf messages like steamguard-cli"""
    
    def __init__(self):
        self.session = None
        self.protobuf = SteamProtobufAuth()
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def send_protobuf_request(self, service: str, method: str, version: int, 
                                  data: bytes, access_token: str = None, use_get: bool = False) -> bytes:
        """Send a protobuf request to Steam API"""
        # Build URL in exact steamguard-cli format
        url = f"{self.protobuf.base_url}/{service}/{method}/v{version}"
        
        headers = {
            'User-Agent': 'steamguard-cli'
        }
        
        if use_get:
            # For GET requests, use URL-safe base64 and query parameters
            encoded_data = base64.urlsafe_b64encode(data).decode('ascii')
            params = {'input_protobuf_encoded': encoded_data}
            
            if access_token:
                params['access_token'] = access_token
            
            async with self.session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    # Check for Steam-specific error headers
                    x_eresult = response.headers.get('x-eresult')
                    x_error_message = response.headers.get('x-error_message')
                    
                    if x_eresult and x_eresult != '1':  # 1 = success
                        raise Exception(f"Steam API error {x_eresult}: {x_error_message or 'Unknown error'}")
                    
                    return await response.read()
                else:
                    raise Exception(f"Steam API HTTP error: {response.status}")
        else:
            # For POST requests, use standard base64 and form data
            encoded_data = base64.b64encode(data).decode('ascii')
            
            # Create form data
            form_data = aiohttp.FormData()
            form_data.add_field('input_protobuf_encoded', encoded_data)
            
            if access_token:
                form_data.add_field('access_token', access_token)
            
            async with self.session.post(url, data=form_data, headers=headers) as response:
                if response.status == 200:
                    # Check for Steam-specific error headers
                    x_eresult = response.headers.get('x-eresult')
                    x_error_message = response.headers.get('x-error_message')
                    
                    if x_eresult and x_eresult != '1':  # 1 = success
                        raise Exception(f"Steam API error {x_eresult}: {x_error_message or 'Unknown error'}")
                    
                    return await response.read()
                else:
                    raise Exception(f"Steam API HTTP error: {response.status}")
    
    async def get_rsa_key(self, account_name: str) -> Dict[str, Any]:
        """Get RSA key for password encryption"""
        try:
            logging.info(f"Getting RSA key for {account_name}")
            
            # Create protobuf request
            request_data = self.protobuf.create_rsa_request(account_name)
            
            # Send request (RSA key requests use GET)
            response_data = await self.send_protobuf_request(
                "IAuthenticationService", "GetPasswordRSAPublicKey", 1, request_data, use_get=True
            )
            
            # Parse response
            result = self.protobuf.parse_rsa_response(response_data)
            
            if result["publickey_mod"] and result["publickey_exp"]:
                logging.info("✅ Successfully got RSA key via protobuf")
                return {
                    "publickey_mod": result["publickey_mod"],
                    "publickey_exp": result["publickey_exp"],
                    "timestamp": str(result["timestamp"])
                }
            else:
                raise Exception("Invalid RSA response")
                
        except Exception as e:
            logging.error(f"Error getting RSA key: {e}")
            return None
    
    def encrypt_password(self, password: str, rsa_mod: str, rsa_exp: str) -> str:
        """Encrypt password using RSA public key"""
        try:
            # Convert hex strings to integers
            modulus = int(rsa_mod, 16)
            exponent = int(rsa_exp, 16)
            
            # Create RSA public key
            public_numbers = rsa.RSAPublicNumbers(exponent, modulus)
            public_key = public_numbers.public_key()
            
            # Encrypt password
            encrypted = public_key.encrypt(
                password.encode('utf-8'),
                padding.PKCS1v15()
            )
            
            return base64.b64encode(encrypted).decode('utf-8')
            
        except Exception as e:
            logging.error(f"Error encrypting password: {e}")
            return ""
    
    async def begin_auth_session(self, account_name: str, encrypted_password: str, 
                               encryption_timestamp: str) -> Dict[str, Any]:
        """Begin authentication session"""
        try:
            logging.info(f"Beginning auth session for {account_name}")
            
            device_name = f"Steam Authenticator Linux-{secrets.token_hex(4)}"
            
            # Create protobuf request
            request_data = self.protobuf.create_auth_request(
                account_name, encrypted_password, int(encryption_timestamp), device_name
            )
            
            # Send request
            response_data = await self.send_protobuf_request(
                "IAuthenticationService", "BeginAuthSessionViaCredentials", 1, request_data
            )
            
            # Parse response
            result = self.protobuf.parse_auth_response(response_data)
            
            if result["client_id"]:
                logging.info("✅ Successfully began auth session via protobuf")
                return {
                    "client_id": result["client_id"],
                    "request_id": result["request_id"],
                    "steamid": result["steamid"],
                    "needs_2fa": True  # Assume we need 2FA
                }
            else:
                raise Exception("Invalid auth response")
                
        except Exception as e:
            logging.error(f"Error beginning auth session: {e}")
            return {"error": str(e)}
    
    async def submit_steam_guard_code(self, client_id: int, steamid: int, code: str) -> bool:
        """Submit Steam Guard code"""
        try:
            logging.info(f"Submitting Steam Guard code")
            
            # Create protobuf request
            request_data = self.protobuf.create_steamguard_request(client_id, steamid, code)
            
            # Send request
            response_data = await self.send_protobuf_request(
                "IAuthenticationService", "UpdateAuthSessionWithSteamGuardCode", 1, request_data
            )
            
            logging.info("✅ Successfully submitted Steam Guard code")
            return True
            
        except Exception as e:
            logging.error(f"Error submitting Steam Guard code: {e}")
            return False
    
    async def poll_auth_session(self, client_id: int, request_id: bytes) -> Dict[str, Any]:
        """Poll for authentication completion"""
        try:
            # Create protobuf request
            request_data = self.protobuf.create_poll_request(client_id, request_id)
            
            # Send request
            response_data = await self.send_protobuf_request(
                "IAuthenticationService", "PollAuthSessionStatus", 1, request_data
            )
            
            # Parse response
            result = self.protobuf.parse_poll_response(response_data)
            
            if result["access_token"] or result["refresh_token"]:
                logging.info("✅ Successfully got tokens via protobuf polling")
                return {
                    "success": True,
                    "access_token": result["access_token"],
                    "refresh_token": result["refresh_token"],
                    "account_name": result["account_name"]
                }
            elif result["had_remote_interaction"]:
                return {"waiting": True}
            else:
                return {"waiting": True}
                
        except Exception as e:
            logging.error(f"Error polling auth session: {e}")
            return {"error": str(e)}
    
    async def refresh_access_token(self, refresh_token: str, steamid: int) -> Optional[str]:
        """Refresh access token using protobuf"""
        try:
            logging.info("Refreshing access token via protobuf")
            
            # Create protobuf request
            request_data = self.protobuf.create_refresh_token_request(refresh_token, steamid)
            
            # Send request
            response_data = await self.send_protobuf_request(
                "IAuthenticationService", "GenerateAccessTokenForApp", 1, request_data
            )
            
            # Parse response
            result = self.protobuf.parse_refresh_response(response_data)
            
            if result["access_token"]:
                logging.info("✅ Successfully refreshed access token via protobuf")
                return result["access_token"]
            else:
                raise Exception("No access token in response")
                
        except Exception as e:
            logging.error(f"Error refreshing access token: {e}")
            return None
    
    async def complete_login_flow(self, account_name: str, password: str, 
                                auth_code_callback=None) -> Dict[str, Any]:
        """Complete login flow with protobuf"""
        try:
            logging.info(f"Starting protobuf login flow for {account_name}")
            
            # 1. Get RSA key
            rsa_data = await self.get_rsa_key(account_name)
            if not rsa_data:
                return {"error": "Failed to get RSA key"}
            
            # 2. Encrypt password
            encrypted_password = self.encrypt_password(
                password, rsa_data["publickey_mod"], rsa_data["publickey_exp"]
            )
            if not encrypted_password:
                return {"error": "Failed to encrypt password"}
            
            # 3. Begin auth session
            auth_response = await self.begin_auth_session(
                account_name, encrypted_password, rsa_data["timestamp"]
            )
            if "error" in auth_response:
                return auth_response
            
            client_id = auth_response["client_id"]
            request_id = auth_response["request_id"]
            steamid = auth_response["steamid"]
            
            # 4. Handle 2FA if needed
            if auth_response.get("needs_2fa"):
                if auth_code_callback:
                    auth_code = await auth_code_callback()
                    if auth_code:
                        success = await self.submit_steam_guard_code(client_id, steamid, auth_code)
                        if not success:
                            return {"error": "Failed to submit Steam Guard code"}
                    else:
                        return {
                            "needs_2fa": True,
                            "client_id": client_id,
                            "request_id": request_id,
                            "steamid": steamid
                        }
                else:
                    # No callback provided, return 2FA needed
                    return {
                        "needs_2fa": True,
                        "client_id": client_id,
                        "request_id": request_id,
                        "steamid": steamid
                    }
            
            # 5. Poll for tokens
            for attempt in range(30):  # Wait up to 30 seconds
                result = await self.poll_auth_session(client_id, request_id)
                
                if result.get("success"):
                    logging.info("🎉 Protobuf login successful!")
                    return result
                elif result.get("waiting"):
                    await asyncio.sleep(1)
                    continue
                else:
                    return {"error": result.get("error", "Authentication failed")}
            
            return {"error": "Login timeout"}
            
        except Exception as e:
            logging.error(f"Error in protobuf login flow: {e}")
            return {"error": str(e)}
    
    async def complete_2fa_login(self, client_id: int, request_id: bytes, 
                               steamid: int, auth_code: str) -> Dict[str, Any]:
        """Complete login after providing 2FA code"""
        try:
            # Submit 2FA code
            success = await self.submit_steam_guard_code(client_id, steamid, auth_code)
            if not success:
                return {"error": "Invalid Steam Guard code"}
            
            # Poll for completion
            for attempt in range(10):
                result = await self.poll_auth_session(client_id, request_id)
                
                if result.get("success"):
                    return result
                elif result.get("waiting"):
                    await asyncio.sleep(1)
                    continue
                else:
                    return {"error": result.get("error", "Authentication failed")}
            
            return {"error": "Login timeout"}
            
        except Exception as e:
            logging.error(f"Error completing 2FA login: {e}")
            return {"error": str(e)}