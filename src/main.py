#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GdkPixbuf
import asyncio
import threading
from pathlib import Path

# Get the icon path
ICON_PATH = Path(__file__).parent / "icons"
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
from sda_compat import is_sda_folder, read_sda_manifest, verify_sda_passkey, export_sda_accounts, import_sda_accounts

# Set up logging
_log_dir = Path.home() / ".local" / "share" / "steam-authenticator"
_log_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_dir / 'steam_authenticator.log')
    ]
)


class SteamAuthenticatorApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id='gg.cs2central.SteamAuthenticator',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self.mafile_manager = MaFileManager()
        self.preferences = PreferencesManager()
        self.accounts = []
        self.current_account = None
        self.main_window = None
        
    def do_startup(self):
        Adw.Application.do_startup(self)

        # Add custom icon path to icon theme
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icon_theme.add_search_path(str(ICON_PATH))

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
        self.create_action('export_encrypted', self.on_export_encrypted_action)
        self.create_action('import_encrypted', self.on_import_encrypted_action)
        self.create_action('export_folder', self.on_export_folder_action)
        self.create_action('refresh_token', self.on_refresh_token_action)
        self.create_action('steam_login', self.on_steam_login_action)
        self.create_action('relogin', self.on_relogin_action)
        self.create_action('refresh_profile', self.on_refresh_profile_action)
        self.create_action('show_import_export', self.on_show_import_export_action)
        
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
            application_icon='gg.cs2central.SteamAuthenticator',
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
        about.add_credit_section("Beta Testers", ["SmokeyCS"])
        about.add_link("Discord", "https://discord.gg/cs2central")
        about.present()
    
    def on_preferences_action(self, action, param):
        preferences_window = PreferencesWindow(self.main_window, self.preferences)
        preferences_window.present()
    
    def on_add_account_action(self, action, param):
        # Show add account dialog
        if self.main_window:
            self.main_window.show_add_account_dialog()

    def on_show_import_export_action(self, action, param):
        """Show import/export dialog"""
        if self.main_window:
            from ui import ImportExportDialog
            dialog = ImportExportDialog(self.main_window)
            dialog.present()

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

                # Check if file appears to be encrypted (not valid JSON)
                validation = self.mafile_manager.validate_mafile_format(source_path)
                if validation.get("encrypted"):
                    self.main_window.show_toast("This file is encrypted. Use 'Import Folder' on the SDA maFiles folder instead.")
                    return

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

                # Check if this is an encrypted SDA folder
                if is_sda_folder(folder_path):
                    manifest = read_sda_manifest(folder_path)
                    if manifest and manifest.get("encrypted", False):
                        # Show passkey dialog
                        self._show_sda_passkey_dialog(folder_path)
                        return

                # Import all maFiles from the folder (handles SDA unencrypted + plain maFiles)
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

    def _show_sda_passkey_dialog(self, folder_path: Path):
        """Show a dialog to enter SDA encryption passkey."""
        dialog = Adw.MessageDialog(
            transient_for=self.main_window,
            heading="Encrypted SDA Folder",
            body="This folder contains encrypted Steam Desktop Authenticator files. Enter the encryption passkey to import them.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("import", "Import")
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("import")
        dialog.set_close_response("cancel")

        # Add passkey entry
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.props.placeholder_text = "SDA Encryption Passkey"
        entry.set_hexpand(True)
        entry.add_css_class("card")
        entry.set_margin_start(24)
        entry.set_margin_end(24)
        entry.set_margin_top(8)

        # Allow Enter key to submit
        entry.connect("activate", lambda _: dialog.response("import"))

        dialog.set_extra_child(entry)

        dialog.connect("response", self._on_sda_passkey_response, folder_path, entry)
        dialog.present()
        entry.grab_focus()

    def _on_sda_passkey_response(self, dialog, response, folder_path, entry):
        """Handle SDA passkey dialog response."""
        if response != "import":
            return

        passkey = entry.get_text().strip()
        if not passkey:
            self.main_window.show_toast("Passkey cannot be empty")
            return

        # Verify passkey first
        if not verify_sda_passkey(folder_path, passkey):
            self.main_window.show_toast("Invalid passkey. Please check and try again.")
            return

        # Import with passkey
        try:
            imported, errors = self.mafile_manager.import_sda_folder(folder_path, passkey)

            if imported:
                self.load_accounts()
                self.main_window.set_accounts(self.accounts)

                self.current_account = imported[0]
                self.main_window.set_current_account(self.current_account)

                msg = f"Imported {len(imported)} accounts"
                if errors:
                    msg += f" ({len(errors)} errors)"
                self.main_window.show_toast(msg)
            else:
                error_msg = errors[0] if errors else "Unknown error"
                self.main_window.show_toast(f"Import failed: {error_msg}")

        except Exception as e:
            logging.error(f"SDA import error: {e}")
            self.main_window.show_toast("Could not import encrypted folder. Please try again.")
    
    def on_export_encrypted_action(self, action, param):
        """Export all accounts as maFiles ZIP (optionally encrypted)"""
        if not self.accounts:
            self.main_window.show_toast("No accounts to export")
            return

        # Show passkey dialog
        dialog = Adw.MessageDialog(
            transient_for=self.main_window,
            heading="Export Backup",
            body="Enter a passkey to encrypt the backup. Leave blank to export without encryption.\n\nCompatible with Hour Boost.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("export", "Export")
        dialog.set_response_appearance("export", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("export")
        dialog.set_close_response("cancel")

        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.props.placeholder_text = "Passkey"
        entry.set_hexpand(True)
        entry.add_css_class("card")
        entry.set_margin_start(24)
        entry.set_margin_end(24)
        entry.set_margin_top(8)
        entry.connect("activate", lambda _: dialog.response("export"))

        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_export_encrypted_passkey_response, entry)
        dialog.present()
        entry.grab_focus()

    def _on_export_encrypted_passkey_response(self, dialog, response, entry):
        """Handle passkey entry for export, then show file save dialog"""
        if response != "export":
            return

        passkey = entry.get_text().strip()
        # Empty passkey = plaintext export, non-empty = encrypted
        self._export_passkey = passkey if passkey else None

        suffix = "encrypted-" if passkey else ""
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title("Save Backup")
        file_dialog.set_initial_name(f"maFiles-{suffix}{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        file_dialog.save(self.main_window, None, self._on_export_encrypted_file_selected)

    def _on_export_encrypted_file_selected(self, dialog, result):
        """Save encrypted maFiles ZIP to selected path"""
        try:
            file = dialog.save_finish(result)
            if not file:
                return

            import zipfile
            dest_path = Path(file.get_path())
            passkey = getattr(self, '_export_passkey', None)
            if hasattr(self, '_export_passkey'):
                del self._export_passkey

            # Build account dicts
            account_dicts = [account.to_dict() for account in self.accounts]

            # Export using SDA-compatible encryption
            manifest, files = export_sda_accounts(account_dicts, passkey)

            with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr("manifest.json", json.dumps(manifest, indent=2))
                for filename, content in files.items():
                    zipf.writestr(filename, content)

            label = "Encrypted backup" if passkey else "Backup"
            self.main_window.show_toast(f"{label} saved - {len(files)} accounts")
            logging.info(f"Exported {len(files)} accounts as {'encrypted ' if passkey else ''}maFiles to {dest_path}")

        except GLib.Error as e:
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not save encrypted backup. Please try again.")
        except Exception as e:
            logging.error(f"Encrypted export error: {e}")
            self.main_window.show_toast("Could not save encrypted backup. Please try again.")

    def on_import_encrypted_action(self, action, param):
        """Import encrypted SDA-compatible maFiles ZIP"""
        dialog = Gtk.FileDialog()
        dialog.set_title("Import Encrypted Backup")

        filter_zip = Gtk.FileFilter()
        filter_zip.set_name("Encrypted Backup (*.zip)")
        filter_zip.add_pattern("*.zip")

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All Files")
        filter_all.add_pattern("*")

        filters = Gio.ListStore()
        filters.append(filter_zip)
        filters.append(filter_all)
        dialog.set_filters(filters)

        dialog.open(self.main_window, None, self._on_import_encrypted_file_selected)

    def _on_import_encrypted_file_selected(self, dialog, result):
        """Handle encrypted ZIP file selection"""
        try:
            file = dialog.open_finish(result)
            if not file:
                return

            import zipfile
            source_path = Path(file.get_path())

            # Verify it's a valid SDA-format ZIP (has manifest.json)
            try:
                with zipfile.ZipFile(source_path, 'r') as zipf:
                    if 'manifest.json' not in zipf.namelist():
                        self.main_window.show_toast("Not a valid encrypted backup (no manifest.json)")
                        return
                    manifest = json.loads(zipf.read('manifest.json').decode('utf-8'))
            except zipfile.BadZipFile:
                self.main_window.show_toast("Invalid ZIP file")
                return

            if not manifest.get("entries"):
                self.main_window.show_toast("No accounts found in backup")
                return

            if manifest.get("encrypted", False):
                # Show passkey dialog
                self._import_encrypted_zip_path = source_path
                self._show_import_encrypted_passkey_dialog()
            else:
                # Not encrypted, import directly
                self._do_import_encrypted_zip(source_path, None)

        except GLib.Error as e:
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not import backup. Please try again.")
        except Exception as e:
            logging.error(f"Import encrypted error: {e}")
            self.main_window.show_toast("Could not import backup. Please try again.")

    def _show_import_encrypted_passkey_dialog(self):
        """Show passkey dialog for importing encrypted backup"""
        dialog = Adw.MessageDialog(
            transient_for=self.main_window,
            heading="Encrypted Backup",
            body="This backup is encrypted. Enter the passkey used when exporting.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("import", "Import")
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("import")
        dialog.set_close_response("cancel")

        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.props.placeholder_text = "Decryption Passkey"
        entry.set_hexpand(True)
        entry.add_css_class("card")
        entry.set_margin_start(24)
        entry.set_margin_end(24)
        entry.set_margin_top(8)
        entry.connect("activate", lambda _: dialog.response("import"))

        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_import_encrypted_passkey_response, entry)
        dialog.present()
        entry.grab_focus()

    def _on_import_encrypted_passkey_response(self, dialog, response, entry):
        """Handle passkey entry for encrypted import"""
        if response != "import":
            if hasattr(self, '_import_encrypted_zip_path'):
                del self._import_encrypted_zip_path
            return

        passkey = entry.get_text().strip()
        if not passkey:
            self.main_window.show_toast("Passkey cannot be empty")
            return

        source_path = self._import_encrypted_zip_path
        del self._import_encrypted_zip_path

        self._do_import_encrypted_zip(source_path, passkey)

    def _do_import_encrypted_zip(self, source_path: Path, passkey):
        """Actually import accounts from an SDA-format ZIP"""
        import zipfile
        import tempfile

        try:
            # Extract ZIP to temp dir, then use import_sda_accounts
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                with zipfile.ZipFile(source_path, 'r') as zipf:
                    zipf.extractall(tmpdir)

                accounts, errors = import_sda_accounts(tmpdir_path, passkey)

                if not accounts and errors:
                    error_msg = errors[0] if errors else "Unknown error"
                    self.main_window.show_toast(f"Import failed: {error_msg}")
                    return

                imported = []
                for account_data in accounts:
                    try:
                        account = SteamGuardAccount(account_data)
                        self.mafile_manager.save_mafile(account)
                        imported.append(account)
                    except Exception as e:
                        name = account_data.get("account_name", "unknown")
                        errors.append(f"Failed to save {name}: {e}")

                if imported:
                    self.load_accounts()
                    self.main_window.set_accounts(self.accounts)
                    self.current_account = imported[0]
                    self.main_window.set_current_account(self.current_account)

                    msg = f"Imported {len(imported)} accounts"
                    if errors:
                        msg += f" ({len(errors)} errors)"
                    self.main_window.show_toast(msg)
                else:
                    self.main_window.show_toast("No accounts could be imported")

        except Exception as e:
            logging.error(f"Import encrypted ZIP error: {e}")
            self.main_window.show_toast("Could not import backup. Check the passkey and try again.")

    def on_export_folder_action(self, action, param):
        """Export all accounts as plaintext .maFile files to a folder"""
        if not self.accounts:
            self.main_window.show_toast("No accounts to export")
            return

        dialog = Gtk.FileDialog()
        dialog.set_title("Export maFiles to Folder")
        dialog.select_folder(self.main_window, None, self._on_export_folder_selected)

    def _on_export_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if not folder:
                return

            dest_path = Path(folder.get_path())
            count = 0
            for account in self.accounts:
                filename = f"{account.steamid or account.account_name}.maFile"
                file_path = dest_path / filename
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(account.to_dict(), f, indent=2)
                count += 1

            self.main_window.show_toast(f"Exported {count} accounts to folder")
            logging.info(f"Exported {count} accounts as plaintext maFiles to {dest_path}")

        except GLib.Error as e:
            if e.code == Gio.IOErrorEnum.CANCELLED or "Dismissed" in str(e):
                return
            self.main_window.show_toast("Could not export to folder. Please try again.")
        except Exception as e:
            logging.error(f"Export folder error: {e}")
            self.main_window.show_toast("Could not export to folder. Please try again.")

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

    def on_refresh_profile_action(self, action, param):
        """Refresh profile data from Steam Web API"""
        if not self.current_account:
            self.main_window.show_toast("No account selected")
            return

        if not self.current_account.steamid:
            self.main_window.show_toast("Account has no Steam ID - login first")
            return

        api_key = self.preferences.get("steam_api_key", "")
        if not api_key:
            self.main_window.show_toast("Steam API key not configured - check Preferences")
            return

        # Run refresh in background
        def refresh_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def do_refresh():
                from steam_web_api import SteamWebAPI
                async with SteamWebAPI(api_key) as api:
                    data = await api.fetch_all_player_data(self.current_account.steamid)

                    if data["summary"]:
                        self.current_account.display_name = data["summary"].get("display_name", "")
                        self.current_account.avatar_url = data["summary"].get("avatar_url", "")
                        self.current_account.profile_visibility = data["summary"].get("visibility", 0)

                    if data["games"]:
                        self.current_account.total_games = len(data["games"])

                    if data["bans"]:
                        self.current_account.vac_banned = data["bans"].get("vac_banned", False)
                        self.current_account.trade_banned = data["bans"].get("trade_banned", False)
                        self.current_account.game_bans = data["bans"].get("game_bans", 0)

                    # Update last refresh timestamp
                    self.current_account.last_api_refresh = datetime.now().isoformat()

                    # Save updated account
                    self.mafile_manager.save_mafile(self.current_account)

                    return data["summary"] is not None

            try:
                success = loop.run_until_complete(do_refresh())
                GLib.idle_add(self.handle_profile_refresh_result, success)
            except Exception as e:
                logging.error(f"Profile refresh error: {e}")
                GLib.idle_add(self.handle_profile_refresh_result, False)
            finally:
                loop.close()

        thread = threading.Thread(target=refresh_thread)
        thread.daemon = True
        thread.start()

        self.main_window.show_toast("Refreshing profile data...")

    def handle_profile_refresh_result(self, success):
        """Handle profile refresh result"""
        if success:
            # Update UI with new data
            self.main_window.set_current_account(self.current_account)
            self.main_window.show_toast(f"Profile updated: {self.current_account.display_name or self.current_account.account_name}")
            logging.info(f"Successfully refreshed profile for {self.current_account.account_name}")
        else:
            self.main_window.show_toast("Could not refresh profile. Check API key.")
            logging.warning("Profile refresh failed")

        return False
    
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
            
            self.main_window.show_toast("Fresh Steam session created!")
            logging.info(f"Successfully created fresh Steam session for {self.current_account.account_name}")

            # Auto-refresh profile data
            self.on_refresh_profile_action(None, None)

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
        """Crimson (Red Neon) theme - dark background with red accents"""
        return b"""
            @define-color accent_color #ff0040;
            @define-color accent_bg_color #ff0040;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a1a1a;
            @define-color view_bg_color #242424;
            @define-color card_bg_color #2a2a2a;
            @define-color headerbar_bg_color #242424;

            window { background-color: #1a1a1a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #ff0040; text-shadow: 0 0 3px rgba(255, 0, 64, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #cc0033, #ff0040);
                border: 1px solid #ff0040;
            }
            .card { background-color: #2a2a2a; border: 1px solid rgba(255, 0, 64, 0.2); }
            headerbar { background-color: #242424; border-bottom: 1px solid rgba(255, 0, 64, 0.3); }
            .view, scrolledwindow > viewport { background-color: #242424; }
        """

    def get_ocean_css(self):
        """Ocean (Blue) theme - dark background with blue accents"""
        return b"""
            @define-color accent_color #00a8ff;
            @define-color accent_bg_color #00a8ff;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a1a1a;
            @define-color view_bg_color #242424;
            @define-color card_bg_color #2a2a2a;
            @define-color headerbar_bg_color #242424;

            window { background-color: #1a1a1a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #00a8ff; text-shadow: 0 0 3px rgba(0, 168, 255, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #0077b6, #00a8ff);
                border: 1px solid #00a8ff;
            }
            .card { background-color: #2a2a2a; border: 1px solid rgba(0, 168, 255, 0.2); }
            headerbar { background-color: #242424; border-bottom: 1px solid rgba(0, 168, 255, 0.3); }
            .view, scrolledwindow > viewport { background-color: #242424; }
        """

    def get_forest_css(self):
        """Forest (Green) theme - dark background with green accents"""
        return b"""
            @define-color accent_color #00d26a;
            @define-color accent_bg_color #00d26a;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a1a1a;
            @define-color view_bg_color #242424;
            @define-color card_bg_color #2a2a2a;
            @define-color headerbar_bg_color #242424;

            window { background-color: #1a1a1a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #00d26a; text-shadow: 0 0 3px rgba(0, 210, 106, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #00a854, #00d26a);
                border: 1px solid #00d26a;
            }
            .card { background-color: #2a2a2a; border: 1px solid rgba(0, 210, 106, 0.2); }
            headerbar { background-color: #242424; border-bottom: 1px solid rgba(0, 210, 106, 0.3); }
            .view, scrolledwindow > viewport { background-color: #242424; }
        """

    def get_purple_css(self):
        """Purple (Violet) theme - dark background with purple accents"""
        return b"""
            @define-color accent_color #a855f7;
            @define-color accent_bg_color #a855f7;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a1a1a;
            @define-color view_bg_color #242424;
            @define-color card_bg_color #2a2a2a;
            @define-color headerbar_bg_color #242424;

            window { background-color: #1a1a1a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #a855f7; text-shadow: 0 0 3px rgba(168, 85, 247, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #7c3aed, #a855f7);
                border: 1px solid #a855f7;
            }
            .card { background-color: #2a2a2a; border: 1px solid rgba(168, 85, 247, 0.2); }
            headerbar { background-color: #242424; border-bottom: 1px solid rgba(168, 85, 247, 0.3); }
            .view, scrolledwindow > viewport { background-color: #242424; }
        """

    def get_sunset_css(self):
        """Sunset (Orange) theme - dark background with orange accents"""
        return b"""
            @define-color accent_color #ff6b35;
            @define-color accent_bg_color #ff6b35;
            @define-color accent_fg_color #ffffff;
            @define-color window_bg_color #1a1a1a;
            @define-color view_bg_color #242424;
            @define-color card_bg_color #2a2a2a;
            @define-color headerbar_bg_color #242424;

            window { background-color: #1a1a1a; }
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #ff6b35; text-shadow: 0 0 3px rgba(255, 107, 53, 0.5);
            }
            button.suggested-action {
                background: linear-gradient(45deg, #e65100, #ff6b35);
                border: 1px solid #ff6b35;
            }
            .card { background-color: #2a2a2a; border: 1px solid rgba(255, 107, 53, 0.2); }
            headerbar { background-color: #242424; border-bottom: 1px solid rgba(255, 107, 53, 0.3); }
            .view, scrolledwindow > viewport { background-color: #242424; }
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