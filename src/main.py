#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, GdkPixbuf
import asyncio
import threading
from pathlib import Path
import json
import logging
import time
from datetime import datetime

from steam_guard import SteamGuardAccount, Manifest
from steam_api import SteamAPI
from ui import MainWindow
from mafile_manager import MaFileManager
from login_dialog import LoginDialog
from preferences import PreferencesManager, PreferencesWindow
from setup_dialog import SetupDialog

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('steam_authenticator.log')
    ]
)


class SteamAuthenticatorApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='com.github.steamauthenticator',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self.mafile_manager = MaFileManager()
        self.preferences = PreferencesManager()
        self.accounts = []
        self.current_account = None
        self.main_window = None
        
    def do_startup(self):
        Adw.Application.do_startup(self)
        
        # Set up actions
        self.create_action('quit', lambda *_: self.quit(), ['<Control>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action)
        self.create_action('add_account', self.on_add_account_action)
        self.create_action('setup_account', self.on_setup_account_action)
        self.create_action('remove_account', self.on_remove_account_action)
        self.create_action('import_account', self.on_import_account_action)
        self.create_action('import_folder', self.on_import_folder_action)
        self.create_action('export_account', self.on_export_account_action)
        self.create_action('backup_all', self.on_backup_all_action)
        self.create_action('restore_backup', self.on_restore_backup_action)
        self.create_action('refresh_token', self.on_refresh_token_action)
        self.create_action('steam_login', self.on_steam_login_action)
        self.create_action('relogin', self.on_relogin_action)
        
    def do_activate(self):
        if not self.main_window:
            self.main_window = MainWindow(application=self)
            
            # Load accounts from maFiles
            self.load_accounts()
            self.main_window.set_accounts(self.accounts)
            
            # Load first account if available
            if self.accounts:
                self.current_account = self.accounts[0]
                self.main_window.set_current_account(self.current_account)
            
            # Apply saved preferences
            self.apply_saved_preferences()

            # Start the code update timer
            GLib.timeout_add_seconds(1, self.update_code)

        self.main_window.present()
    
    def load_accounts(self):
        """Load all accounts from maFiles directory"""
        # Show loading progress for large account collections
        mafiles_dir = self.mafile_manager.get_mafiles_directory()
        print(f"Looking for .maFile files in: {mafiles_dir}")
        
        # Load accounts with progress indication
        self.accounts = self.mafile_manager.scan_mafiles()
        account_count = len(self.accounts)
        
        if account_count > 0:
            logging.info(f"Successfully loaded {account_count} accounts from maFiles")
            print(f"✅ Loaded {account_count} Steam accounts")
            
            # Log account names for debugging (first 10 only to avoid spam)
            if account_count <= 10:
                for account in self.accounts:
                    print(f"  • {account.account_name}")
            else:
                for account in self.accounts[:5]:
                    print(f"  • {account.account_name}")
                print(f"  ... and {account_count - 5} more accounts")
        else:
            print("No .maFile files found. You can:")
            print("1. Copy your .maFile files to the maFiles directory")
            print("2. Use 'Add Account' to create a new account")
            print("3. Use 'Import Account' to import existing .maFile files")
    
    def create_action(self, name, callback, shortcuts=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect('activate', callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f'app.{name}', shortcuts)
    
    def update_code(self):
        """Update Steam Guard code every second"""
        if self.current_account and self.main_window:
            code = self.current_account.generate_steam_guard_code()
            time_left = self.current_account.get_time_until_next_code()
            self.main_window.update_code_display(code, time_left)
        return True
    
    def on_about_action(self, action, param):
        about = Adw.AboutWindow(
            transient_for=self.main_window,
            application_name='Steam Authenticator',
            application_icon='steam',
            developer_name='zorex',
            version='1.0.0',
            developers=['zorex'],
            copyright='© 2026 zorex / CS2Central',
            license_type=Gtk.License.GPL_3_0,
            comments='A modern Steam Authenticator for Linux with 2FA code generation and trade confirmation support',
            website='https://cs2central.gg/',
            issue_url='https://github.com/cs2central/steam-authenticator-linux/issues',
            support_url='https://discord.gg/cs2central'
        )
        about.add_link("Discord", "https://discord.gg/cs2central")
        about.add_link("Website", "https://cs2central.gg/")
        about.present()
    
    def on_preferences_action(self, action, param):
        preferences_window = PreferencesWindow(self.main_window, self.preferences)
        preferences_window.present()
    
    def on_add_account_action(self, action, param):
        # Show add account dialog
        if self.main_window:
            self.main_window.show_add_account_dialog()

    def on_setup_account_action(self, action, param):
        """Show setup dialog to link a new Steam account"""
        if self.main_window:
            dialog = SetupDialog(parent=self.main_window)
            dialog.connect('account-created', self.on_account_setup_complete)
            dialog.present()

    def on_account_setup_complete(self, dialog, account_data):
        """Handle successful account setup"""
        try:
            account = SteamGuardAccount(account_data)
            self.mafile_manager.save_mafile(account)

            # Reload accounts
            self.load_accounts()
            self.main_window.set_accounts(self.accounts)

            # Select the new account
            self.current_account = account
            self.main_window.set_current_account(account)

            self.main_window.show_toast(f"Account {account.account_name} set up successfully!")
            logging.info(f"New account linked: {account.account_name}")
        except Exception as e:
            logging.error(f"Error saving new account: {e}")
            self.main_window.show_toast("Could not save account. Please try again.")

    def on_remove_account_action(self, action, param):
        if self.current_account and self.main_window:
            dialog = Adw.MessageDialog(
                transient_for=self.main_window,
                heading="Remove Account",
                body=f"Are you sure you want to remove {self.current_account.account_name}?",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("remove", "Remove")
            dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect("response", self.on_remove_account_response)
            dialog.present()
    
    def on_remove_account_response(self, dialog, response):
        if response == "remove" and self.current_account:
            # Delete the maFile
            self.mafile_manager.delete_mafile(self.current_account)
            
            # Reload accounts
            self.load_accounts()
            self.main_window.set_accounts(self.accounts)
            
            # Select another account or clear
            if self.accounts:
                self.current_account = self.accounts[0]
                self.main_window.set_current_account(self.current_account)
            else:
                self.current_account = None
                self.main_window.set_current_account(None)
    
    def on_import_account_action(self, action, param):
        dialog = Gtk.FileDialog()
        dialog.set_title("Import Account")
        
        filter_mafile = Gtk.FileFilter()
        filter_mafile.set_name("Steam Authenticator Files")
        filter_mafile.add_pattern("*.maFile")
        
        filter_all = Gtk.FileFilter()
        filter_all.set_name("All Files")
        filter_all.add_pattern("*")
        
        filters = Gio.ListStore()
        filters.append(filter_mafile)
        filters.append(filter_all)
        dialog.set_filters(filters)
        
        dialog.open(self.main_window, None, self.on_import_file_selected)
    
    def on_import_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                source_path = Path(file.get_path())

                # Import the maFile
                account = self.mafile_manager.import_mafile(source_path)
                if account:
                    # Reload accounts
                    self.load_accounts()
                    self.main_window.set_accounts(self.accounts)

                    self.current_account = account
                    self.main_window.set_current_account(account)

                    self.main_window.show_toast("Account imported successfully")
                else:
                    self.main_window.show_toast("Could not read account file. Please check the file format.")
        except GLib.Error as e:
            # User cancelled the dialog - this is normal, don't show error
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not import account. Please try again.")
        except Exception as e:
            logging.error(f"Import error: {e}")
            self.main_window.show_toast("Could not import account. Please try again.")

    def on_import_folder_action(self, action, param):
        dialog = Gtk.FileDialog()
        dialog.set_title("Import Folder with maFiles")
        dialog.select_folder(self.main_window, None, self.on_import_folder_selected)

    def on_import_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                folder_path = Path(folder.get_path())

                # Import all maFiles from the folder
                imported_accounts = self.mafile_manager.import_mafiles_from_folder(folder_path)

                if imported_accounts:
                    # Reload accounts
                    self.load_accounts()
                    self.main_window.set_accounts(self.accounts)

                    # Select the first imported account
                    self.current_account = imported_accounts[0]
                    self.main_window.set_current_account(self.current_account)

                    self.main_window.show_toast(f"Imported {len(imported_accounts)} accounts")
                else:
                    self.main_window.show_toast("No .maFile files found in this folder")
        except GLib.Error as e:
            # User cancelled the dialog
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not import folder. Please try again.")
        except Exception as e:
            logging.error(f"Import folder error: {e}")
            self.main_window.show_toast("Could not import folder. Please try again.")
    
    def on_export_account_action(self, action, param):
        if not self.current_account:
            return
        
        dialog = Gtk.FileDialog()
        dialog.set_title("Export Account")
        dialog.set_initial_name(f"{self.current_account.account_name}.maFile")
        
        dialog.save(self.main_window, None, self.on_export_file_selected)
    
    def on_export_file_selected(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file and self.current_account:
                dest_path = Path(file.get_path())

                if self.mafile_manager.export_mafile(self.current_account, dest_path):
                    self.main_window.show_toast("Account exported successfully")
                else:
                    self.main_window.show_toast("Could not save file. Please check permissions.")
        except GLib.Error as e:
            # User cancelled the dialog
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not export account. Please try again.")
        except Exception as e:
            logging.error(f"Export error: {e}")
            self.main_window.show_toast("Could not export account. Please try again.")

    def on_backup_all_action(self, action, param):
        """Backup all accounts to a single zip file"""
        if not self.accounts:
            self.main_window.show_toast("No accounts to backup")
            return

        dialog = Gtk.FileDialog()
        dialog.set_title("Backup All Accounts")
        dialog.set_initial_name(f"steam_authenticator_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        dialog.save(self.main_window, None, self.on_backup_file_selected)

    def on_backup_file_selected(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file:
                import zipfile
                dest_path = Path(file.get_path())

                with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    # Add each account's maFile
                    for account in self.accounts:
                        account_data = json.dumps(account.to_dict(), indent=2)
                        filename = f"{account.steamid or account.account_name}.maFile"
                        zipf.writestr(filename, account_data)

                    # Add a manifest with metadata
                    manifest = {
                        "backup_date": datetime.now().isoformat(),
                        "account_count": len(self.accounts),
                        "accounts": [{"name": a.account_name, "steamid": a.steamid} for a in self.accounts]
                    }
                    zipf.writestr("backup_manifest.json", json.dumps(manifest, indent=2))

                self.main_window.show_toast(f"Backup complete - {len(self.accounts)} accounts saved")
        except GLib.Error as e:
            # User cancelled the dialog
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not create backup. Please try again.")
        except Exception as e:
            logging.error(f"Backup error: {e}")
            self.main_window.show_toast("Could not create backup. Please try again.")

    def on_restore_backup_action(self, action, param):
        """Restore accounts from a backup zip file"""
        dialog = Gtk.FileDialog()
        dialog.set_title("Restore Backup")

        filter_zip = Gtk.FileFilter()
        filter_zip.set_name("Backup Files (*.zip)")
        filter_zip.add_pattern("*.zip")

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All Files")
        filter_all.add_pattern("*")

        filters = Gio.ListStore()
        filters.append(filter_zip)
        filters.append(filter_all)
        dialog.set_filters(filters)

        dialog.open(self.main_window, None, self.on_restore_file_selected)

    def on_restore_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                import zipfile
                source_path = Path(file.get_path())

                restored_count = 0
                with zipfile.ZipFile(source_path, 'r') as zipf:
                    for name in zipf.namelist():
                        if name.endswith('.maFile'):
                            # Extract and import the maFile
                            data = zipf.read(name)
                            account_data = json.loads(data.decode('utf-8'))

                            from steam_guard import SteamGuardAccount
                            account = SteamGuardAccount(account_data)
                            self.mafile_manager.save_mafile(account)
                            restored_count += 1

                # Reload accounts
                self.load_accounts()
                self.main_window.set_accounts(self.accounts)

                if self.accounts:
                    self.current_account = self.accounts[0]
                    self.main_window.set_current_account(self.current_account)

                if restored_count > 0:
                    self.main_window.show_toast(f"Restored {restored_count} accounts")
                else:
                    self.main_window.show_toast("No accounts found in backup file")
        except GLib.Error as e:
            # User cancelled the dialog
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not restore backup. Please try again.")
        except zipfile.BadZipFile:
            self.main_window.show_toast("Invalid backup file. Please select a valid .zip file.")
        except Exception as e:
            logging.error(f"Restore error: {e}")
            self.main_window.show_toast("Could not restore backup. Please try again.")
    
    def switch_account(self, account_name: str):
        """Switch to a different account"""
        for account in self.accounts:
            if account.account_name == account_name:
                self.current_account = account
                self.main_window.set_current_account(account)
                break
    
    def add_new_account(self, account_data: dict):
        """Add a new account and save as maFile"""
        try:
            account = SteamGuardAccount(account_data)
            self.mafile_manager.save_mafile(account)
            
            # Reload accounts
            self.load_accounts()
            self.main_window.set_accounts(self.accounts)
            
            self.current_account = account
            self.main_window.set_current_account(account)
            
            return True
        except Exception as e:
            logging.error(f"Failed to add account: {e}")
            return False
    
    def on_refresh_token_action(self, action, param):
        """Try to refresh all account tokens automatically"""
        if not self.current_account:
            self.main_window.show_toast("No account selected")
            return
        
        # Run refresh in background
        def refresh_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def do_refresh():
                refreshed_count = 0
                
                for account in self.accounts:
                    refresh_token = account.session_data.get("refresh_token")
                    if refresh_token:
                        logging.info(f"Attempting to refresh token for {account.account_name}")
                        async with SteamLogin() as steam_login:
                            new_token = await steam_login.try_refresh_token(
                                account.steamid, 
                                refresh_token
                            )
                            if new_token:
                                account.session_data["access_token"] = new_token
                                account.session_data["token_timestamp"] = int(time.time())
                                # Save updated account
                                self.mafile_manager.save_mafile(account)
                                refreshed_count += 1
                                logging.info(f"Successfully refreshed token for {account.account_name}")
                            else:
                                logging.warning(f"Failed to refresh token for {account.account_name}")
                    else:
                        logging.info(f"No refresh token available for {account.account_name}")
                
                return refreshed_count
            
            try:
                count = loop.run_until_complete(do_refresh())
                GLib.idle_add(self.handle_bulk_token_refresh_result, count)
            except Exception as e:
                logging.error(f"Token refresh error: {e}")
                GLib.idle_add(self.handle_bulk_token_refresh_result, 0)
            finally:
                loop.close()
        
        thread = threading.Thread(target=refresh_thread)
        thread.daemon = True
        thread.start()
        
        self.main_window.show_toast("Refreshing account sessions...")
    
    def handle_bulk_token_refresh_result(self, count):
        """Handle bulk token refresh result"""
        if count > 0:
            self.main_window.show_toast(f"Refreshed {count} account session(s) successfully!")
            logging.info(f"Successfully refreshed {count} account tokens")
        else:
            self.main_window.show_toast("No tokens were refreshed - you may need to login again")
            logging.warning("No tokens were refreshed")
        
        return False
    
    def on_steam_login_action(self, action, param):
        """Show Steam login dialog with integrated protobuf authentication"""
        if not self.current_account:
            self.main_window.show_toast("No account selected")
            return
        
        # Show the Steam login dialog with protobuf support
        dialog = LoginDialog(self.main_window)
        
        # Pre-fill username if available
        if hasattr(dialog, 'username_entry') and self.current_account.account_name:
            dialog.username_entry.set_text(self.current_account.account_name)
        
        dialog.present()
        
        # Handle dialog response
        def on_dialog_close(dialog):
            login_result = dialog.get_login_result()
            if login_result and login_result.get("success"):
                self.handle_steam_login_success(login_result)
        
        dialog.connect("close-request", on_dialog_close)
    
    
    def on_relogin_action(self, action, param):
        """Legacy action - redirect to steam_login"""
        self.on_steam_login_action(action, param)
    
    def handle_steam_login_success(self, login_result):
        """Handle successful Steam login with fresh tokens"""
        try:
            # Update current account with fresh tokens
            if login_result.get("access_token"):
                self.current_account.session_data["access_token"] = login_result["access_token"]
                self.current_account.session_data["token_timestamp"] = int(time.time())
                
            if login_result.get("refresh_token"):
                self.current_account.session_data["refresh_token"] = login_result["refresh_token"]
            
            # Update other session data if available
            if login_result.get("account_name"):
                # Verify account name matches
                if login_result["account_name"] != self.current_account.account_name:
                    logging.warning(f"Account name mismatch: expected {self.current_account.account_name}, got {login_result['account_name']}")
            
            # Save updated account
            self.mafile_manager.save_mafile(self.current_account)
            
            self.main_window.show_toast("✅ Fresh Steam session created! Trade confirmations should work now.")
            logging.info(f"Successfully created fresh Steam session for {self.current_account.account_name}")
            
        except Exception as e:
            logging.error(f"Error updating account with fresh tokens: {e}")
            self.main_window.show_toast("Could not save session. Please try again.")
    
    def handle_token_update(self, token_data):
        """Handle manual token update from dialog"""
        try:
            # Update current account with new tokens
            if token_data.get("access_token"):
                self.current_account.session_data["access_token"] = token_data["access_token"]
                self.current_account.session_data["token_timestamp"] = int(time.time())
            
            if token_data.get("refresh_token"):
                self.current_account.session_data["refresh_token"] = token_data["refresh_token"]
            
            # Save updated account
            self.mafile_manager.save_mafile(self.current_account)
            
            self.main_window.show_toast("Tokens updated! Trade confirmations should work now.")
            logging.info(f"Successfully updated tokens for {self.current_account.account_name}")
            
        except Exception as e:
            logging.error(f"Error updating account tokens: {e}")
            self.main_window.show_toast("Could not update tokens. Please try again.")
    
    def apply_saved_preferences(self):
        """Apply saved preferences to the application"""
        # Apply theme
        theme = self.preferences.get("theme", "light")
        self.apply_theme(theme)
        
        # Apply font size
        font_size = self.preferences.get("font_size", "large")
        if self.main_window:
            self.main_window.update_code_font_size(font_size)
    
    def apply_theme(self, theme_name):
        """Apply the selected theme"""
        style_manager = Adw.StyleManager.get_default()

        # First clear any existing custom theme
        self.clear_custom_theme()

        if theme_name == "light":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif theme_name == "dark":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        elif theme_name == "crimson":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self.apply_custom_theme(self.get_crimson_css())
        elif theme_name == "ocean":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self.apply_custom_theme(self.get_ocean_css())
        elif theme_name == "forest":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self.apply_custom_theme(self.get_forest_css())
        elif theme_name == "purple":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self.apply_custom_theme(self.get_purple_css())
        elif theme_name == "sunset":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self.apply_custom_theme(self.get_sunset_css())
        elif theme_name == "nord":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
            self.apply_custom_theme(self.get_nord_css())
    
    def clear_custom_theme(self):
        """Remove custom theme CSS"""
        if hasattr(self, 'custom_css_provider') and self.custom_css_provider:
            Gtk.StyleContext.remove_provider_for_display(
                self.main_window.get_display(),
                self.custom_css_provider
            )
            self.custom_css_provider = None

    def apply_custom_theme(self, css_data):
        """Apply a custom theme CSS"""
        self.custom_css_provider = Gtk.CssProvider()
        self.custom_css_provider.load_from_data(css_data)

        if self.main_window:
            Gtk.StyleContext.add_provider_for_display(
                self.main_window.get_display(),
                self.custom_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def get_crimson_css(self):
        """Crimson (Red Neon) theme"""
        return b"""
            @define-color accent_color #ff0040;
            @define-color accent_bg_color #ff0040;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a0005;
            @define-color view_bg_color #220008;
            @define-color card_bg_color #2a000a;
            @define-color headerbar_bg_color #330011;

            window { background-color: #1a0005; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #ff0040; text-shadow: 0 0 3px rgba(255, 0, 64, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #ff0040, #ff3366);
                border: 1px solid #ff0040;
            }
            .card { background-color: #2a000a; border: 1px solid rgba(255, 0, 64, 0.15); }
            headerbar { background: linear-gradient(90deg, #1a0005, #330011); border-bottom: 1px solid rgba(255, 0, 64, 0.3); }
            .view, scrolledwindow > viewport { background-color: #220008; }
        """

    def get_ocean_css(self):
        """Ocean (Blue) theme"""
        return b"""
            @define-color accent_color #00a8ff;
            @define-color accent_bg_color #00a8ff;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #001a2c;
            @define-color view_bg_color #002240;
            @define-color card_bg_color #003355;
            @define-color headerbar_bg_color #002a4a;

            window { background-color: #001a2c; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #00a8ff; text-shadow: 0 0 3px rgba(0, 168, 255, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #0077b6, #00a8ff);
                border: 1px solid #00a8ff;
            }
            .card { background-color: #003355; border: 1px solid rgba(0, 168, 255, 0.15); }
            headerbar { background: linear-gradient(90deg, #001a2c, #002a4a); border-bottom: 1px solid rgba(0, 168, 255, 0.3); }
            .view, scrolledwindow > viewport { background-color: #002240; }
        """

    def get_forest_css(self):
        """Forest (Green) theme"""
        return b"""
            @define-color accent_color #00d26a;
            @define-color accent_bg_color #00d26a;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #0a1f0a;
            @define-color view_bg_color #0f2a0f;
            @define-color card_bg_color #143814;
            @define-color headerbar_bg_color #1a4a1a;

            window { background-color: #0a1f0a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #00d26a; text-shadow: 0 0 3px rgba(0, 210, 106, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #00a854, #00d26a);
                border: 1px solid #00d26a;
            }
            .card { background-color: #143814; border: 1px solid rgba(0, 210, 106, 0.15); }
            headerbar { background: linear-gradient(90deg, #0a1f0a, #1a4a1a); border-bottom: 1px solid rgba(0, 210, 106, 0.3); }
            .view, scrolledwindow > viewport { background-color: #0f2a0f; }
        """

    def get_purple_css(self):
        """Purple (Violet) theme"""
        return b"""
            @define-color accent_color #a855f7;
            @define-color accent_bg_color #a855f7;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a0a2e;
            @define-color view_bg_color #240f3d;
            @define-color card_bg_color #2e1450;
            @define-color headerbar_bg_color #3b1a66;

            window { background-color: #1a0a2e; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #a855f7; text-shadow: 0 0 3px rgba(168, 85, 247, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #7c3aed, #a855f7);
                border: 1px solid #a855f7;
            }
            .card { background-color: #2e1450; border: 1px solid rgba(168, 85, 247, 0.15); }
            headerbar { background: linear-gradient(90deg, #1a0a2e, #3b1a66); border-bottom: 1px solid rgba(168, 85, 247, 0.3); }
            .view, scrolledwindow > viewport { background-color: #240f3d; }
        """

    def get_sunset_css(self):
        """Sunset (Orange) theme"""
        return b"""
            @define-color accent_color #ff6b35;
            @define-color accent_bg_color #ff6b35;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1f0f0a;
            @define-color view_bg_color #2a1510;
            @define-color card_bg_color #3d1f15;
            @define-color headerbar_bg_color #4a2518;

            window { background-color: #1f0f0a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #ff6b35; text-shadow: 0 0 3px rgba(255, 107, 53, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #e65100, #ff6b35);
                border: 1px solid #ff6b35;
            }
            .card { background-color: #3d1f15; border: 1px solid rgba(255, 107, 53, 0.15); }
            headerbar { background: linear-gradient(90deg, #1f0f0a, #4a2518); border-bottom: 1px solid rgba(255, 107, 53, 0.3); }
            .view, scrolledwindow > viewport { background-color: #2a1510; }
        """

    def get_nord_css(self):
        """Nord theme"""
        return b"""
            @define-color accent_color #88c0d0;
            @define-color accent_bg_color #88c0d0;
            @define-color accent_fg_color #2e3440;
            @define-color window_bg_color #2e3440;
            @define-color view_bg_color #3b4252;
            @define-color card_bg_color #434c5e;
            @define-color headerbar_bg_color #3b4252;

            window { background-color: #2e3440; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #88c0d0; text-shadow: 0 0 3px rgba(136, 192, 208, 0.3);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #5e81ac, #88c0d0);
                border: 1px solid #88c0d0;
            }
            .card { background-color: #434c5e; border: 1px solid rgba(136, 192, 208, 0.15); }
            headerbar { background: linear-gradient(90deg, #2e3440, #3b4252); border-bottom: 1px solid rgba(136, 192, 208, 0.2); }
            .view, scrolledwindow > viewport { background-color: #3b4252; }
        """


def main():
    app = SteamAuthenticatorApp()
    app.run(None)


if __name__ == '__main__':
    main()