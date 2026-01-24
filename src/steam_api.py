import aiohttp
import asyncio
import json
import time
import base64
import hashlib
import hmac
import re
from typing import Optional, Dict, Any, List
from urllib.parse import quote
import logging


class SteamAPI:
    STEAM_API_BASE = "https://steamcommunity.com"
    STEAM_LOGIN_BASE = "https://login.steampowered.com"
    
    def __init__(self):
        self.session = None
        self.cookies = {}
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def generate_confirmation_hash_for_time(self, time_stamp: int, tag: str, identity_secret: str) -> str:
        """Generate confirmation hash using steamguard-cli approach"""
        try:
            decode = base64.b64decode(identity_secret)
            
            # Build time bytes (8 bytes, big-endian)
            time_bytes = time_stamp.to_bytes(8, byteorder='big')
            
            # Create HMAC with identity secret
            hmac_obj = hmac.new(decode, time_bytes, hashlib.sha1)
            if tag:
                hmac_obj.update(tag.encode('utf-8'))
            
            hash_bytes = hmac_obj.digest()
            return base64.b64encode(hash_bytes).decode('utf-8')
        except Exception as e:
            logging.error(f"Error generating confirmation hash: {e}")
            return ""
    
    async def get_confirmations(self, account) -> List[Dict[str, Any]]:
        """Fetch trade confirmations using steamguard-cli approach"""
        if not account.identity_secret:
            logging.error("No identity secret available")
            return []
        
        if not account.steamid:
            logging.error("No Steam ID available - account not properly configured")
            return []
        
        # Check token expiration status first
        token_status = account.check_token_expiration()
        access_token = account.session_data.get("access_token", "")
        refresh_token = account.session_data.get("refresh_token", "")
        
        logging.info(f"Account {account.account_name} tokens: access_token={'Yes' if access_token else 'No'} ({len(access_token)} chars), refresh_token={'Yes' if refresh_token else 'No'} ({len(refresh_token)} chars)")
        
        # Only try to refresh if refresh token is still valid
        if refresh_token and token_status.get("refresh_token_valid", False):
            # Check if access token is missing or expired
            if not token_status.get("access_token_valid", False):
                logging.info(f"Access token expired, attempting refresh with valid refresh token")
                from steam_protobuf_login import SteamProtobufLogin
                async with SteamProtobufLogin() as steam_login:
                    new_token = await steam_login.refresh_access_token(
                        refresh_token,
                        int(account.steamid)
                    )
                    if new_token and new_token != refresh_token:
                        account.session_data["access_token"] = new_token
                        account.session_data["token_timestamp"] = int(time.time())
                        # Save the updated account
                        from mafile_manager import MaFileManager
                        manager = MaFileManager()
                        await manager.save_account(account)
                        logging.info("✅ Successfully refreshed and saved access token")
                    else:
                        logging.warning("⚠️ Token refresh failed - tokens may be permanently expired")
        elif not token_status.get("refresh_token_valid", False):
            refresh_exp = token_status.get("refresh_token_expires")
            if refresh_exp:
                logging.warning(f"Refresh token expired on {refresh_exp.strftime('%Y-%m-%d')} - need fresh login")
            else:
                logging.warning(f"No valid refresh token available for account {account.account_name}")
        
        try:
            # Get current time
            time_stamp = int(time.time())
            conf_key = self.generate_confirmation_hash_for_time(time_stamp, "conf", account.identity_secret)
            
            if not conf_key:
                logging.error("Failed to generate confirmation key")
                return []
            
            params = {
                "p": account.device_id,
                "a": account.steamid,
                "k": conf_key,
                "t": str(time_stamp),
                "m": "react",
                "tag": "conf"
            }
            
            # Build cookies based on steamguard-cli approach
            cookies = {}
            current_access_token = account.session_data.get("access_token")
            if current_access_token:
                # Use steamLoginSecure cookie format: {steam_id}||{access_token}
                steam_login_secure = f"{account.steamid}||{current_access_token}"
                cookies = {
                    "dob": "",
                    "steamid": account.steamid,
                    "steamLoginSecure": steam_login_secure
                }
                logging.debug(f"Using cookies for authentication: steamid={account.steamid}, token_length={len(current_access_token)}")
            else:
                logging.warning("No access token available for authentication")
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Referer": "https://steamcommunity.com/mobileconf/conf",
            }
            
            async with self.session.get(
                f"{self.STEAM_API_BASE}/mobileconf/getlist",
                params=params,
                headers=headers,
                cookies=cookies
            ) as response:
                if response.status == 200:
                    text = await response.text()
                    logging.debug(f"Confirmation response: {text[:500]}...")  # Log first 500 chars
                    
                    # Try to parse as JSON first (modern Steam API)
                    try:
                        data = json.loads(text)
                        if data.get("success"):
                            confirmations = self._parse_confirmations_json(data)
                            logging.info(f"Found {len(confirmations)} confirmations")
                            return confirmations
                        else:
                            # Check for authentication errors
                            if data.get("needauth"):
                                logging.warning("Authentication required - tokens are expired")
                                
                                # Check if we can refresh
                                token_status = account.check_token_expiration()
                                if token_status.get("refresh_token_valid", False):
                                    logging.info("Attempting token refresh with valid refresh token")
                                    from steam_protobuf_login import SteamProtobufLogin
                                    async with SteamProtobufLogin() as steam_login:
                                        new_token = await steam_login.refresh_access_token(
                                            account.session_data["refresh_token"],
                                            int(account.steamid)
                                        )
                                        if new_token and new_token != account.session_data.get("refresh_token"):
                                            account.session_data["access_token"] = new_token
                                            account.session_data["token_timestamp"] = int(time.time())
                                            # Save the updated account
                                            from mafile_manager import MaFileManager
                                            manager = MaFileManager()
                                            await manager.save_account(account)
                                            logging.info("Token refreshed, retrying confirmation fetch")
                                            # Retry the request with new token (but only once)
                                            return await self.get_confirmations(account)
                                
                                logging.error("Both tokens expired - need fresh login")
                                return []
                            else:
                                logging.error(f"API returned success=false: {data}")
                                return []
                    except json.JSONDecodeError:
                        # Fall back to HTML parsing for older responses
                        if "\"needauth\":true" in text or "\"success\":false" in text:
                            logging.warning("Authentication required - tokens are expired")
                            return []
                        
                        confirmations = self._parse_confirmations_html(text)
                        logging.info(f"Found {len(confirmations)} confirmations")
                        return confirmations
                elif response.status == 401:
                    logging.error("Unauthorized - session may have expired")
                    # Try automatic token refresh
                    if account.session_data.get("refresh_token"):
                        logging.info("Attempting automatic token refresh...")
                        from steam_protobuf_login import SteamProtobufLogin
                        async with SteamProtobufLogin() as steam_login:
                            new_token = await steam_login.refresh_access_token(
                                account.session_data["refresh_token"],
                                int(account.steamid)
                            )
                            if new_token:
                                account.session_data["access_token"] = new_token
                                account.session_data["token_timestamp"] = int(time.time())
                                # Save the updated account
                                from mafile_manager import MaFileManager
                                manager = MaFileManager()
                                await manager.save_account(account)
                                logging.info("Token refreshed, retrying confirmation fetch")
                                # Retry the request with new token
                                return await self.get_confirmations(account)
                    return []
                else:
                    logging.error(f"Failed to fetch confirmations: {response.status}")
                    text = await response.text()
                    logging.debug(f"Error response: {text}")
                    return []
        except Exception as e:
            logging.error(f"Error fetching confirmations: {e}")
            return []
    
    def _parse_confirmations_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse confirmations from Steam HTML response using improved pattern matching"""
        confirmations = []
        
        # Check if we got an empty response or error
        if "There are no confirmations waiting" in html or "conf_empty" in html:
            return confirmations
        
        # Look for confirmation entries using more comprehensive patterns
        # Pattern based on steamguard-cli's approach
        conf_pattern = r'data-confid="(\d+)"[^>]*data-key="(\d+)"[^>]*data-type="(\d+)"[^>]*data-creator="(\d+)"'
        matches = re.findall(conf_pattern, html)
        
        if not matches:
            # Try alternative patterns for different Steam page formats
            conf_pattern_alt = r'data-confid=\'(\d+)\'[^>]*data-key=\'(\d+)\'[^>]*data-type=\'(\d+)\'[^>]*data-creator=\'(\d+)\''
            matches = re.findall(conf_pattern_alt, html)
        
        for match in matches:
            conf_id, conf_key, conf_type, creator = match
            
            # Try to extract title and description
            # Look for the confirmation div content
            conf_div_pattern = f'data-confid="{conf_id}"[^>]*>(.*?)</div>'
            div_match = re.search(conf_div_pattern, html, re.DOTALL)
            
            title = "Trade Offer"
            description = ""
            
            if div_match:
                div_content = div_match.group(1)
                
                # Extract title from img alt or div text
                img_alt_match = re.search(r'alt="([^"]+)"', div_content)
                if img_alt_match:
                    title = img_alt_match.group(1)
                
                # Extract description from multiple div structures
                desc_matches = re.findall(r'<div[^>]*>([^<]+)</div>', div_content)
                if desc_matches:
                    # Filter out empty or very short descriptions
                    valid_descs = [d.strip() for d in desc_matches if len(d.strip()) > 3]
                    if valid_descs:
                        description = valid_descs[-1]  # Take the last meaningful description
            
            confirmation = {
                "id": conf_id,
                "key": conf_key,
                "type": self._get_confirmation_type(int(conf_type)),
                "creator": creator,
                "title": title.strip(),
                "description": description.strip(),
                "type_id": int(conf_type)
            }
            confirmations.append(confirmation)
            logging.debug(f"Parsed confirmation: {confirmation}")
        
        return confirmations
    
    async def get_trade_offer_details(self, account, trade_offer_id: str) -> Dict[str, Any]:
        """Get detailed information about a trade offer"""
        try:
            url = f"https://steamcommunity.com/tradeoffer/{trade_offer_id}/"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://steamcommunity.com/profiles/{}".format(account.steamid),
            }
            
            cookies = {}
            if account.session_data.get("access_token"):
                steam_login_secure = f"{account.steamid}||{account.session_data['access_token']}"
                cookies = {
                    "steamLoginSecure": steam_login_secure,
                    "steamid": account.steamid
                }
            
            async with self.session.get(url, headers=headers, cookies=cookies) as response:
                if response.status == 200:
                    html = await response.text()
                    return self._parse_trade_offer_html(html)
                else:
                    logging.error(f"Failed to fetch trade offer details: {response.status}")
                    return {}
                    
        except Exception as e:
            logging.error(f"Error fetching trade offer details: {e}")
            return {}
    
    def _parse_trade_offer_html(self, html: str) -> Dict[str, Any]:
        """Parse trade offer HTML to extract items"""
        import re
        
        trade_data = {
            "items_to_give": [],
            "items_to_receive": [],
            "partner_name": "",
            "trade_offer_id": ""
        }
        
        try:
            # Extract partner name
            partner_match = re.search(r'<span class="whiteLink">([^<]+)</span>', html)
            if partner_match:
                trade_data["partner_name"] = partner_match.group(1)
            
            # Extract items to give (your items)
            give_section = re.search(r'<div class="tradeoffer_items primary">.*?</div>', html, re.DOTALL)
            if give_section:
                items = re.findall(r'data-economy-item="([^"]*)"[^>]*title="([^"]*)"', give_section.group(0))
                for item_data, title in items:
                    if title:
                        trade_data["items_to_give"].append({
                            "name": title,
                            "data": item_data
                        })
            
            # Extract items to receive (their items)
            receive_section = re.search(r'<div class="tradeoffer_items secondary">.*?</div>', html, re.DOTALL)
            if receive_section:
                items = re.findall(r'data-economy-item="([^"]*)"[^>]*title="([^"]*)"', receive_section.group(0))
                for item_data, title in items:
                    if title:
                        trade_data["items_to_receive"].append({
                            "name": title,
                            "data": item_data
                        })
                        
        except Exception as e:
            logging.debug(f"Error parsing trade offer HTML: {e}")
        
        return trade_data
    
    def _parse_confirmations_json(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse confirmations from Steam JSON response"""
        confirmations = []
        
        conf_list = data.get("conf", [])
        if not conf_list:
            return confirmations
        
        for conf in conf_list:
            confirmation = {
                "id": str(conf.get("id", "")),
                "key": str(conf.get("nonce", "")),  # 'nonce' is the confirmation key
                "type": conf.get("type_name", "Unknown"),
                "creator": str(conf.get("creator_id", "")),
                "title": conf.get("headline", "Trade Offer"),
                "description": " | ".join(conf.get("summary", [])) if conf.get("summary") else "",
                "type_id": int(conf.get("type", 0))
            }
            confirmations.append(confirmation)
            logging.debug(f"Parsed JSON confirmation: {confirmation}")
        
        return confirmations
    
    def _get_confirmation_type(self, type_id: int) -> str:
        """Convert confirmation type ID to string"""
        types = {
            1: "Generic",
            2: "Trade",
            3: "Market Listing",
            5: "Account Recovery"
        }
        return types.get(type_id, "Unknown")
    
    async def respond_to_confirmation(self, account, confirmation_id: str, confirmation_key: str, accept: bool) -> bool:
        """Accept or deny a confirmation using steamguard-cli approach with automatic retry"""
        try:
            time_stamp = int(time.time())
            operation = "allow" if accept else "cancel"
            conf_key = self.generate_confirmation_hash_for_time(time_stamp, operation, account.identity_secret)
            
            if not conf_key:
                logging.error("Failed to generate confirmation key")
                return False
            
            params = {
                "op": operation,
                "p": account.device_id,
                "a": account.steamid,
                "k": conf_key,
                "t": str(time_stamp),
                "m": "react",
                "tag": operation,
                "cid": confirmation_id,
                "ck": confirmation_key
            }
            
            # Build cookies
            cookies = {}
            if account.session_data.get("access_token"):
                steam_login_secure = f"{account.steamid}||{account.session_data['access_token']}"
                cookies = {
                    "dob": "",
                    "steamid": account.steamid,
                    "steamLoginSecure": steam_login_secure
                }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36",
                "Accept": "*/*",
                "Referer": "https://steamcommunity.com/mobileconf/conf",
            }
            
            # Use GET request as steamguard-cli does
            async with self.session.get(
                f"{self.STEAM_API_BASE}/mobileconf/ajaxop",
                params=params,
                headers=headers,
                cookies=cookies
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    success = result.get("success", False)
                    
                    # Check for authentication errors
                    if not success and result.get("needauth"):
                        logging.warning("Authentication required - attempting token refresh")
                        if account.session_data.get("refresh_token"):
                            from steam_login import SteamLogin
                            async with SteamLogin() as steam_login:
                                new_token = await steam_login.try_refresh_token(
                                    account.steamid,
                                    account.session_data["refresh_token"]
                                )
                                if new_token:
                                    account.session_data["access_token"] = new_token
                                    account.session_data["token_timestamp"] = int(time.time())
                                    # Save the updated account
                                    from mafile_manager import MaFileManager
                                    manager = MaFileManager()
                                    await manager.save_account(account)
                                    logging.info("Token refreshed, retrying confirmation response")
                                    # Retry the request with new token
                                    return await self.respond_to_confirmation(account, confirmation_id, confirmation_key, accept)
                        
                        logging.error("Session expired and token refresh failed")
                        return False
                    
                    logging.info(f"Confirmation response result: {result}")
                    return success
                elif response.status == 401:
                    logging.error("Unauthorized - attempting token refresh")
                    if account.session_data.get("refresh_token"):
                        from steam_login import SteamLogin
                        async with SteamLogin() as steam_login:
                            new_token = await steam_login.try_refresh_token(
                                account.steamid,
                                account.session_data["refresh_token"]
                            )
                            if new_token:
                                account.session_data["access_token"] = new_token
                                account.session_data["token_timestamp"] = int(time.time())
                                # Save the updated account
                                from mafile_manager import MaFileManager
                                manager = MaFileManager()
                                await manager.save_account(account)
                                logging.info("Token refreshed, retrying confirmation response")
                                # Retry the request with new token
                                return await self.respond_to_confirmation(account, confirmation_id, confirmation_key, accept)
                    return False
                else:
                    logging.error(f"Failed to respond to confirmation: {response.status}")
                    text = await response.text()
                    logging.debug(f"Error response: {text}")
                    return False
        except Exception as e:
            logging.error(f"Error responding to confirmation: {e}")
            return False
    
    async def login_with_qr(self) -> Dict[str, Any]:
        """Start QR code login process"""
        try:
            # This would implement the QR login flow
            # For now, return a placeholder
            return {
                "success": False,
                "message": "QR login not yet implemented"
            }
        except Exception as e:
            print(f"Error in QR login: {e}")
            return {"success": False, "message": str(e)}
    
    async def check_session_status(self, account) -> Dict[str, Any]:
        """Check if the current session is valid for confirmations"""
        try:
            # First, check token expiration dates
            token_status = account.check_token_expiration()
            
            if not token_status["access_token_valid"] and not token_status["refresh_token_valid"]:
                access_exp = token_status.get("access_token_expires")
                refresh_exp = token_status.get("refresh_token_expires")
                
                exp_msg = ""
                if access_exp:
                    exp_msg += f"Access token expired: {access_exp.strftime('%Y-%m-%d')}. "
                if refresh_exp:
                    exp_msg += f"Refresh token expired: {refresh_exp.strftime('%Y-%m-%d')}."
                
                return {
                    "status": "expired",
                    "message": f"Both tokens expired. {exp_msg}",
                    "can_refresh": False,
                    "needs_fresh_tokens": True
                }
            
            elif not token_status["access_token_valid"] and token_status["refresh_token_valid"]:
                return {
                    "status": "refresh_needed", 
                    "message": "Access token expired but refresh token valid",
                    "can_refresh": True,
                    "needs_fresh_tokens": False
                }
            
            # If tokens look valid, test them with Steam
            time_stamp = int(time.time())
            conf_key = self.generate_confirmation_hash_for_time(time_stamp, "conf", account.identity_secret)
            
            params = {
                "p": account.device_id,
                "a": account.steamid,
                "k": conf_key,
                "t": str(time_stamp),
                "m": "react",
                "tag": "conf"
            }
            
            cookies = {}
            if account.session_data.get("access_token"):
                steam_login_secure = f"{account.steamid}||{account.session_data['access_token']}"
                cookies = {
                    "steamLoginSecure": steam_login_secure,
                    "steamid": account.steamid
                }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36"
            }
            
            async with self.session.get(
                f"{self.STEAM_API_BASE}/mobileconf/getlist",
                params=params,
                headers=headers,
                cookies=cookies
            ) as response:
                if response.status == 200:
                    text = await response.text()
                    if "\"needauth\":true" in text or "\"success\":false" in text:
                        return {
                            "status": "expired",
                            "message": "Steam rejected tokens - need fresh login",
                            "can_refresh": False,
                            "needs_fresh_tokens": True
                        }
                    else:
                        return {
                            "status": "valid",
                            "message": "Session is working for confirmations",
                            "needs_fresh_tokens": False
                        }
                else:
                    return {
                        "status": "error",
                        "message": f"HTTP {response.status}",
                        "needs_fresh_tokens": False
                    }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "needs_fresh_tokens": False
            }
    
    async def refresh_session(self, account) -> bool:
        """Refresh the session token"""
        if not account.session_data.get("refresh_token"):
            return False
        
        try:
            data = {
                "refresh_token": account.session_data["refresh_token"],
                "steamid": account.steamid
            }
            
            async with self.session.post(
                f"{self.STEAM_LOGIN_BASE}/jwt/refresh",
                json=data
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        account.session_data["access_token"] = result["access_token"]
                        if "refresh_token" in result:
                            account.session_data["refresh_token"] = result["refresh_token"]
                        return True
            return False
        except Exception as e:
            print(f"Error refreshing session: {e}")
            return False
    
    async def respond_to_multiple_confirmations(self, account, confirmation_ids: List[str], 
                                               confirmation_keys: List[str], accept: bool) -> bool:
        """Accept or deny multiple confirmations at once"""
        try:
            time_stamp = int(time.time())
            operation = "allow" if accept else "cancel"
            conf_key = self.generate_confirmation_hash_for_time(time_stamp, operation, account.identity_secret)
            
            # Build the data for multiple confirmations
            data = {
                "op": operation,
                "p": account.device_id,
                "a": account.steamid,
                "k": conf_key,
                "t": time_stamp,
                "m": "android",
                "tag": operation
            }
            
            # Add each confirmation
            for i, (cid, ck) in enumerate(zip(confirmation_ids, confirmation_keys)):
                data[f"cid[{i}]"] = cid
                data[f"ck[{i}]"] = ck
            
            if account.session_data.get("access_token"):
                headers = {
                    "Authorization": f"Bearer {account.session_data['access_token']}",
                    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36"
                }
            else:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36",
                    "Cookie": f"steamLoginSecure={account.session_data.get('steamLoginSecure', '')}"
                }
            
            async with self.session.post(
                f"{self.STEAM_API_BASE}/mobileconf/multiajaxop",
                data=data,
                headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("success", False)
                return False
        except Exception as e:
            print(f"Error responding to multiple confirmations: {e}")
            return False