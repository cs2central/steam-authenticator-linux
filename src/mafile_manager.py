import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import logging
from steam_guard import SteamGuardAccount


class MaFileManager:
    """Manages .maFile files like Steam Desktop Authenticator"""
    
    def __init__(self, mafiles_dir: Optional[Path] = None):
        if mafiles_dir is None:
            # Default to src/maFiles directory
            src_dir = Path(__file__).parent
            self.mafiles_dir = src_dir / "maFiles"
        else:
            self.mafiles_dir = Path(mafiles_dir)
        
        self.mafiles_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Using maFiles directory: {self.mafiles_dir}")
    
    def scan_mafiles(self) -> List[SteamGuardAccount]:
        """Scan the maFiles directory and load all accounts"""
        accounts = []
        
        if not self.mafiles_dir.exists():
            logging.warning(f"maFiles directory does not exist: {self.mafiles_dir}")
            return accounts
        
        for file_path in self.mafiles_dir.glob("*.maFile"):
            try:
                account = self.load_mafile(file_path)
                if account:
                    accounts.append(account)
                    logging.info(f"Loaded account: {account.account_name}")
            except Exception as e:
                logging.error(f"Failed to load {file_path}: {e}")
        
        logging.info(f"Loaded {len(accounts)} accounts from maFiles")
        return accounts
    
    def load_mafile(self, file_path: Path) -> Optional[SteamGuardAccount]:
        """Load a single .maFile"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate required fields
            required_fields = ['account_name', 'shared_secret']
            for field in required_fields:
                if field not in data:
                    logging.error(f"Missing required field '{field}' in {file_path}")
                    return None
            
            # Create account from maFile data
            account = SteamGuardAccount(data)
            account.mafile_path = file_path
            
            return account
            
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in {file_path}: {e}")
            return None
        except Exception as e:
            logging.error(f"Error loading {file_path}: {e}")
            return None
    
    def save_mafile(self, account: SteamGuardAccount, filename: Optional[str] = None) -> Path:
        """Save account to .maFile using Steam ID format (Windows compatible)"""
        if filename is None:
            # Use Steam ID format (like Windows Steam Desktop Authenticator)
            if account.steamid:
                filename = f"{account.steamid}.maFile"
            else:
                # Fallback to account name if no Steam ID
                safe_name = self._sanitize_filename(account.account_name or "unknown")
                filename = f"{safe_name}.maFile"
        
        file_path = self.mafiles_dir / filename
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(account.to_dict(), f, indent=2)
            
            account.mafile_path = file_path
            logging.info(f"Saved account to {file_path}")
            return file_path
            
        except Exception as e:
            logging.error(f"Failed to save {file_path}: {e}")
            raise
    
    async def save_account(self, account: SteamGuardAccount) -> bool:
        """Async version of save_mafile for use in SteamAPI"""
        try:
            self.save_mafile(account)
            return True
        except Exception as e:
            logging.error(f"Failed to save account {account.account_name}: {e}")
            return False
    
    def delete_mafile(self, account: SteamGuardAccount) -> bool:
        """Delete the .maFile for an account"""
        if hasattr(account, 'mafile_path') and account.mafile_path:
            try:
                account.mafile_path.unlink()
                logging.info(f"Deleted {account.mafile_path}")
                return True
            except Exception as e:
                logging.error(f"Failed to delete {account.mafile_path}: {e}")
                return False
        return False
    
    def import_mafile(self, source_path: Path) -> Optional[SteamGuardAccount]:
        """Import a .maFile from another location"""
        try:
            account = self.load_mafile(source_path)
            if account:
                # Save to our maFiles directory
                new_path = self.save_mafile(account)
                account.mafile_path = new_path
                return account
            return None
        except Exception as e:
            logging.error(f"Failed to import {source_path}: {e}")
            return None
    
    def export_mafile(self, account: SteamGuardAccount, dest_path: Path) -> bool:
        """Export account to a .maFile at specified location"""
        try:
            with open(dest_path, 'w', encoding='utf-8') as f:
                json.dump(account.to_dict(), f, indent=2)
            
            logging.info(f"Exported account to {dest_path}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to export to {dest_path}: {e}")
            return False
    
    def get_mafiles_directory(self) -> Path:
        """Get the maFiles directory path"""
        return self.mafiles_dir
    
    def set_mafiles_directory(self, new_dir: Path):
        """Change the maFiles directory"""
        new_dir = Path(new_dir)
        new_dir.mkdir(parents=True, exist_ok=True)
        self.mafiles_dir = new_dir
        logging.info(f"Changed maFiles directory to: {self.mafiles_dir}")
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string to be safe for use as filename"""
        # Remove or replace unsafe characters
        unsafe_chars = '<>:"/\\|?*'
        safe_name = name
        for char in unsafe_chars:
            safe_name = safe_name.replace(char, '_')
        
        # Remove leading/trailing spaces and dots
        safe_name = safe_name.strip('. ')
        
        # Ensure it's not empty
        if not safe_name:
            safe_name = "account"
        
        return safe_name
    
    def import_mafiles_from_folder(self, folder_path: Path) -> List[SteamGuardAccount]:
        """Import all .maFile files from a folder"""
        imported = []
        folder_path = Path(folder_path)

        if not folder_path.exists() or not folder_path.is_dir():
            logging.error(f"Invalid folder path: {folder_path}")
            return imported

        # Find all .maFile files (case insensitive)
        mafiles = list(folder_path.glob("*.maFile")) + list(folder_path.glob("*.mafile"))

        logging.info(f"Found {len(mafiles)} .maFile files in {folder_path}")

        for mafile_path in mafiles:
            try:
                account = self.import_mafile(mafile_path)
                if account:
                    imported.append(account)
                    logging.info(f"Imported: {account.account_name}")
            except Exception as e:
                logging.error(f"Failed to import {mafile_path}: {e}")

        logging.info(f"Successfully imported {len(imported)} accounts from folder")
        return imported

    def validate_mafile_format(self, file_path: Path) -> Dict[str, any]:
        """Validate a .maFile format and return validation results"""
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "account_name": None,
            "steam_id": None
        }
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check required fields
            required_fields = ['account_name', 'shared_secret']
            for field in required_fields:
                if field not in data:
                    result["errors"].append(f"Missing required field: {field}")
            
            # Check recommended fields
            recommended_fields = ['identity_secret', 'steamid']
            for field in recommended_fields:
                if field not in data:
                    result["warnings"].append(f"Missing recommended field: {field} (needed for confirmations)")
            
            # Extract account info
            result["account_name"] = data.get("account_name")
            result["steam_id"] = data.get("steamid") or data.get("SteamID")
            
            # Check if valid
            result["valid"] = len(result["errors"]) == 0
            
        except json.JSONDecodeError as e:
            result["errors"].append(f"Invalid JSON: {e}")
        except Exception as e:
            result["errors"].append(f"Error reading file: {e}")
        
        return result