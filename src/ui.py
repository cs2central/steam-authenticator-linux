import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, GObject, Pango
import asyncio
from typing import Optional
import qrcode
from io import BytesIO

from steam_guard import SteamGuardAccount
from steam_api import SteamAPI
from confirmations_dialog import ConfirmationsDialog


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        self.set_title("Steam Authenticator")
        self.set_default_size(450, 650)  # Slightly wider to prevent text truncation
        
        self.current_account = None
        self.accounts = []
        self.confirmations_list = []
        
        self.setup_ui()
        self.setup_headerbar()
    
    def setup_ui(self):
        # Main box
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)
        
        # Toast overlay
        self.toast_overlay = Adw.ToastOverlay()
        self.main_box.append(self.toast_overlay)
        
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.toast_overlay.set_child(scrolled)
        
        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        scrolled.set_child(content_box)
        
        # Account selector
        self.account_row = Adw.ActionRow()
        self.account_row.set_title("No Account Selected")
        self.account_row.set_subtitle("Add an account to get started")
        self.account_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.account_row.set_activatable(True)
        self.account_row.connect("activated", self.on_account_row_activated)
        
        account_group = Adw.PreferencesGroup()
        account_group.set_title("Account")
        account_group.add(self.account_row)
        content_box.append(account_group)
        
        # Steam Guard Code section
        code_group = Adw.PreferencesGroup()
        code_group.set_title("Steam Guard Code")
        content_box.append(code_group)
        
        # Code display card
        self.code_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.code_card.add_css_class("card")
        self.code_card.set_margin_top(12)
        self.code_card.set_margin_bottom(12)
        self.code_card.set_margin_start(12)
        self.code_card.set_margin_end(12)
        code_group.add(self.code_card)
        
        # Code label
        self.code_label = Gtk.Label()
        self.code_label.set_text("-----")
        self.code_label.add_css_class("title-1")
        self.code_label.set_selectable(True)
        
        # Apply custom CSS for larger, monospace font
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .title-1 {
                font-size: 48px;
                font-family: monospace;
                font-weight: bold;
                letter-spacing: 8px;
                color: @accent_color;
            }
            .code-small {
                font-size: 32px;
                font-family: monospace;
                font-weight: bold;
                letter-spacing: 6px;
                color: @accent_color;
            }
            .code-medium {
                font-size: 40px;
                font-family: monospace;
                font-weight: bold;
                letter-spacing: 7px;
                color: @accent_color;
            }
            .code-large {
                font-size: 48px;
                font-family: monospace;
                font-weight: bold;
                letter-spacing: 8px;
                color: @accent_color;
            }
            .code-extra-large {
                font-size: 56px;
                font-family: monospace;
                font-weight: bold;
                letter-spacing: 10px;
                color: @accent_color;
            }
            .dim-label {
                opacity: 0.6;
            }
            .card {
                background: alpha(@card_bg_color, 0.5);
                border-radius: 12px;
                padding: 20px;
            }
            .success-button {
                background: @success_color;
                color: white;
            }
            .destructive-button {
                background: @destructive_color;
                color: white;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        self.code_card.append(self.code_label)
        
        # Timer progress bar
        self.timer_progress = Gtk.ProgressBar()
        self.timer_progress.set_show_text(True)
        self.code_card.append(self.timer_progress)
        
        # Copy button
        copy_button = Gtk.Button(label="Copy Code")
        copy_button.add_css_class("suggested-action")
        copy_button.connect("clicked", self.on_copy_code)
        self.code_card.append(copy_button)
        
        # Confirmations section
        confirmations_group = Adw.PreferencesGroup()
        confirmations_group.set_title("Trade Confirmations")
        content_box.append(confirmations_group)
        
        # Session status row
        self.session_status_row = Adw.ActionRow()
        self.session_status_row.set_title("Check Session Status")  # Removed emoji to save space
        self.session_status_row.set_subtitle("Verify token status")
        self.session_status_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self.session_status_row.set_activatable(True)
        self.session_status_row.connect("activated", self.on_check_session_status)
        confirmations_group.add(self.session_status_row)
        
        # Steam login button (prominent)
        steam_login_row = Adw.ActionRow()
        steam_login_row.set_title("Login to Steam")  # Removed emoji to save space
        steam_login_row.set_subtitle("Generate fresh tokens for confirmations")
        steam_login_row.set_subtitle_lines(0)  # Allow subtitle to wrap
        steam_login_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        steam_login_row.set_activatable(True)
        steam_login_row.connect("activated", self.on_steam_login_activated)
        confirmations_group.add(steam_login_row)
        
        # Open confirmations button
        confirmations_row = Adw.ActionRow()
        confirmations_row.set_title("View Confirmations")
        confirmations_row.set_subtitle("Open trade confirmations window")
        confirmations_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        confirmations_row.set_activatable(True)
        confirmations_row.connect("activated", self.on_open_confirmations)
        confirmations_group.add(confirmations_row)
    
    def setup_headerbar(self):
        # Header bar
        header = Adw.HeaderBar()

        # Add header to main box instead of set_titlebar
        self.main_box.prepend(header)

        # Discord button
        discord_button = Gtk.Button()
        discord_button.set_icon_name("discord-symbolic")
        discord_button.set_tooltip_text("Join our Discord")
        discord_button.connect("clicked", self.on_discord_clicked)
        header.pack_start(discord_button)

        # Website button
        website_button = Gtk.Button()
        website_button.set_icon_name("starred-symbolic")
        website_button.set_tooltip_text("Visit CS2Central.gg")
        website_button.connect("clicked", self.on_website_clicked)
        header.pack_start(website_button)

        # Menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        header.pack_end(menu_button)
        
        # Create menu
        menu = Gio.Menu()
        menu.append("Set Up New Account", "app.setup_account")
        menu.append("Add Account Manually", "app.add_account")
        menu.append("Import Account", "app.import_account")
        menu.append("Import Folder", "app.import_folder")
        menu.append("Export Account", "app.export_account")
        menu.append_section(None, self.create_backup_menu_section())
        menu.append_section(None, self.create_account_menu_section())
        menu.append_section(None, self.create_app_menu_section())
        
        menu_button.set_menu_model(menu)
    
    def create_backup_menu_section(self):
        section = Gio.Menu()
        section.append("Backup All Accounts", "app.backup_all")
        section.append("Restore from Backup", "app.restore_backup")
        return section

    def create_account_menu_section(self):
        section = Gio.Menu()
        section.append("Login to Steam", "app.steam_login")
        section.append("Refresh Sessions", "app.refresh_token")
        section.append("Remove Current Account", "app.remove_account")
        return section
    
    def create_app_menu_section(self):
        section = Gio.Menu()
        section.append("Preferences", "app.preferences")
        section.append("About Steam Authenticator", "app.about")
        section.append("Quit", "app.quit")
        return section
    
    def set_accounts(self, accounts):
        self.accounts = accounts
    
    def set_current_account(self, account: Optional[SteamGuardAccount]):
        self.current_account = account
        
        if account:
            self.account_row.set_title(account.account_name)
            self.account_row.set_subtitle(f"Steam ID: {account.steamid or 'Not logged in'}")
            
            # Reset session status
            self.session_status_row.set_title("Check Session Status")
            self.session_status_row.set_subtitle("Click to check tokens")
            
            # Update code immediately
            code = account.generate_steam_guard_code()
            time_left = account.get_time_until_next_code()
            self.update_code_display(code, time_left)
        else:
            self.account_row.set_title("No Account Selected")
            self.account_row.set_subtitle("Add an account to get started")
            self.session_status_row.set_title("Check Session Status")
            self.session_status_row.set_subtitle("No account selected")
            self.code_label.set_text("-----")
            self.timer_progress.set_fraction(0)
            self.timer_progress.set_text("")
    
    def update_code_display(self, code: str, time_left: int):
        self.code_label.set_text(code)
        
        # Update progress bar
        progress = time_left / 30.0
        self.timer_progress.set_fraction(progress)
        self.timer_progress.set_text(f"{time_left}s")
        
        # Change color when time is running out
        if time_left <= 5:
            self.timer_progress.add_css_class("warning")
        else:
            self.timer_progress.remove_css_class("warning")
    
    def on_copy_code(self, button):
        if self.current_account:
            code = self.current_account.generate_steam_guard_code()
            clipboard = self.get_clipboard()
            clipboard.set(code)
            self.show_toast("Code copied to clipboard")
    
    def on_account_row_activated(self, row):
        if not self.accounts:
            # Show options to add account
            self.show_no_account_dialog()
            return

        # Create advanced account selector for large numbers of accounts
        selector = AccountSelectorDialog(self, self.accounts, self.current_account)
        selector.connect("account-selected", self.on_account_selected)
        selector.present()

    def show_no_account_dialog(self):
        """Show dialog with options to add an account"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="No Accounts",
            body="Add a Steam account to get started",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("setup", "Set Up New Account")
        dialog.add_response("import", "Import Existing")

        dialog.set_response_appearance("setup", Adw.ResponseAppearance.SUGGESTED)

        dialog.connect("response", self.on_no_account_response)
        dialog.present()

    def on_no_account_response(self, dialog, response):
        """Handle response from no account dialog"""
        app = self.get_application()
        if response == "setup":
            app.activate_action("setup_account")
        elif response == "import":
            app.activate_action("import_account")
    
    def on_account_selected(self, dialog, account):
        """Handle account selection from the advanced dialog"""
        app = self.get_application()
        app.switch_account(account.account_name)
    
    def on_open_confirmations(self, row):
        if not self.current_account:
            self.show_toast("No account selected")
            return
        
        # Open confirmations dialog
        dialog = ConfirmationsDialog(self, self.current_account)
        dialog.present()
    
    def show_toast(self, message: str):
        toast = Adw.Toast(title=message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)

    def on_discord_clicked(self, button):
        """Open Discord invite link"""
        import subprocess
        subprocess.Popen(["xdg-open", "https://discord.gg/cs2central"])

    def on_website_clicked(self, button):
        """Open website link"""
        import subprocess
        subprocess.Popen(["xdg-open", "https://cs2central.gg/"])
    
    def update_code_font_size(self, font_size):
        """Update the font size of the Steam Guard code display"""
        # Remove existing font size classes
        self.code_label.remove_css_class("title-1")
        self.code_label.remove_css_class("code-small")
        self.code_label.remove_css_class("code-medium")
        self.code_label.remove_css_class("code-large")
        self.code_label.remove_css_class("code-extra-large")
        
        # Apply new font size class
        if font_size == "small":
            self.code_label.add_css_class("code-small")
        elif font_size == "medium":
            self.code_label.add_css_class("code-medium")
        elif font_size == "large":
            self.code_label.add_css_class("code-large")
        elif font_size == "extra-large":
            self.code_label.add_css_class("code-extra-large")
        else:
            self.code_label.add_css_class("code-large")  # Default to large
    
    def on_check_session_status(self, row):
        """Check the current session status"""
        if not self.current_account:
            self.show_toast("No account selected")
            return
        
        # Check session status in background
        def check_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def do_check():
                from steam_api import SteamAPI
                async with SteamAPI() as api:
                    return await api.check_session_status(self.current_account)
            
            try:
                result = loop.run_until_complete(do_check())
                GLib.idle_add(self.handle_session_status_result, result)
            except Exception as e:
                GLib.idle_add(self.handle_session_status_result, {"status": "error", "message": str(e)})
            finally:
                loop.close()
        
        import threading
        thread = threading.Thread(target=check_thread)
        thread.daemon = True
        thread.start()
        
        self.session_status_row.set_subtitle("Checking...")
    
    def handle_session_status_result(self, result):
        """Handle session status check result"""
        status = result.get("status", "unknown")
        message = result.get("message", "Unknown status")
        needs_fresh = result.get("needs_fresh_tokens", False)
        can_refresh = result.get("can_refresh", False)
        
        if status == "valid":
            self.session_status_row.set_title("Session Valid")
            self.session_status_row.set_subtitle("Ready for confirmations")
            self.show_toast("Session active - ready for confirmations")

        elif status == "expired":
            if needs_fresh:
                self.session_status_row.set_title("Session Expired")
                self.session_status_row.set_subtitle("Please login again")
                self.show_toast("Session expired. Please login to Steam.")
            else:
                self.session_status_row.set_title("Session Expired")
                self.session_status_row.set_subtitle("Please login again")
                self.show_toast("Session expired. Please login to Steam.")

        elif status == "refresh_needed":
            self.session_status_row.set_title("Refreshing...")
            self.session_status_row.set_subtitle("Updating session")
            self.show_toast("Refreshing session...")

        else:
            self.session_status_row.set_title("Session Unknown")
            self.session_status_row.set_subtitle("Could not check status")
            self.show_toast("Could not check session. Please try again.")
        
        return False
    
    def on_steam_login_activated(self, row):
        """Handle Steam login activation"""
        if not self.current_account:
            self.show_toast("No account selected")
            return
        
        # Trigger the Steam login action
        app = self.get_application()
        if app:
            app.on_steam_login_action(None, None)
    
    def refresh_account_list(self):
        # This would refresh the account list in the UI
        pass
    
    def show_add_account_dialog(self):
        dialog = AddAccountDialog(transient_for=self)
        dialog.connect("account-added", self.on_account_added)
        dialog.present()
    
    def on_account_added(self, dialog, account_data):
        app = self.get_application()
        if app.add_new_account(account_data):
            self.show_toast("Account added")
        else:
            self.show_toast("Could not add account. Please check the details.")


class AddAccountDialog(Adw.Window):
    __gsignals__ = {
        'account-added': (GObject.SignalFlags.RUN_FIRST, None, (object,))
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        self.set_title("Add Account")
        self.set_default_size(400, 500)
        self.set_modal(True)
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main box
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(box)
        
        # Header bar
        header = Adw.HeaderBar()
        box.append(header)
        
        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(20)
        content.set_margin_bottom(20) 
        content.set_margin_start(20)
        content.set_margin_end(20)
        box.append(content)
        
        # Instructions
        label = Gtk.Label()
        label.set_markup("<b>Add Steam Account</b>\n\nYou can add an account by:\n• Scanning a QR code\n• Entering account details manually\n• Importing a .maFile")
        label.set_wrap(True)
        content.append(label)
        
        # Options
        qr_button = Gtk.Button(label="Scan QR Code")
        qr_button.add_css_class("suggested-action")
        qr_button.connect("clicked", self.on_scan_qr)
        content.append(qr_button)
        
        manual_button = Gtk.Button(label="Enter Manually")
        manual_button.connect("clicked", self.on_enter_manually)
        content.append(manual_button)
    
    def on_scan_qr(self, button):
        # TODO: Implement QR scanning
        self.show_toast("QR scanning not yet implemented")
    
    def on_enter_manually(self, button):
        # Show manual entry dialog
        dialog = ManualEntryDialog(transient_for=self)
        dialog.connect("response", self.on_manual_entry_response)
        dialog.present()
    
    def on_manual_entry_response(self, dialog, response_id):
        if response_id == Gtk.ResponseType.OK:
            account_data = dialog.get_account_data()
            if account_data:
                self.emit('account-added', account_data)
                self.close()
    
    def show_toast(self, message: str):
        # Show toast in parent window
        parent = self.get_transient_for()
        if parent and hasattr(parent, 'show_toast'):
            parent.show_toast(message)


class ManualEntryDialog(Gtk.Dialog):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        self.set_title("Enter Account Details")
        self.set_default_size(400, 400)
        self.set_modal(True)
        
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Add", Gtk.ResponseType.OK)
        
        self.setup_ui()
    
    def setup_ui(self):
        box = self.get_content_area()
        box.set_spacing(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Account name
        self.name_entry = Adw.EntryRow()
        self.name_entry.set_title("Account Name")
        box.append(self.name_entry)
        
        # Steam ID (required for confirmations)
        self.steamid_entry = Adw.EntryRow()
        self.steamid_entry.set_title("Steam ID (64-bit)")
        self.steamid_entry.set_subtitle("Required for trade confirmations")
        box.append(self.steamid_entry)
        
        # Shared secret
        self.shared_secret_entry = Adw.EntryRow()
        self.shared_secret_entry.set_title("Shared Secret")
        self.shared_secret_entry.set_subtitle("Base64 encoded")
        box.append(self.shared_secret_entry)
        
        # Identity secret
        self.identity_secret_entry = Adw.EntryRow()
        self.identity_secret_entry.set_title("Identity Secret")
        self.identity_secret_entry.set_subtitle("Base64 encoded, required for confirmations")
        box.append(self.identity_secret_entry)
        
        # Access token (optional)
        self.access_token_entry = Adw.EntryRow()
        self.access_token_entry.set_title("Access Token (optional)")
        box.append(self.access_token_entry)
    
    def get_account_data(self):
        account_name = self.name_entry.get_text()
        shared_secret = self.shared_secret_entry.get_text()
        steamid = self.steamid_entry.get_text()
        
        if not account_name or not shared_secret:
            return None
        
        account_data = {
            "account_name": account_name,
            "steamid": steamid,
            "shared_secret": shared_secret,
            "identity_secret": self.identity_secret_entry.get_text(),
            "session": {}
        }
        
        access_token = self.access_token_entry.get_text()
        if access_token:
            account_data["session"]["access_token"] = access_token
        
        return account_data


class AccountSelectorDialog(Adw.Window):
    """Advanced account selector dialog for handling hundreds of accounts"""
    
    __gsignals__ = {
        'account-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,))
    }
    
    def __init__(self, parent_window, accounts, current_account, **kwargs):
        super().__init__(**kwargs)
        
        self.set_title("Select Account")
        self.set_default_size(500, 600)
        self.set_transient_for(parent_window)
        self.set_modal(True)
        
        self.accounts = accounts
        self.current_account = current_account
        self.filtered_accounts = accounts.copy()
        
        self.setup_ui()
        self.populate_accounts()
    
    def setup_ui(self):
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # Header bar with search
        header = Adw.HeaderBar()
        main_box.append(header)
        
        # Cancel button
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_button)
        
        # Account count label
        self.count_label = Gtk.Label(label=f"{len(self.accounts)} accounts")
        self.count_label.add_css_class("dim-label")
        header.pack_end(self.count_label)
        
        # Search section
        search_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        search_box.set_margin_top(12)
        search_box.set_margin_start(12)
        search_box.set_margin_end(12)
        main_box.append(search_box)
        
        # Search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search accounts by name or Steam ID...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self.on_search_changed)
        search_box.append(self.search_entry)
        
        # Filter buttons (mutually exclusive)
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        filter_box.set_halign(Gtk.Align.CENTER)
        filter_box.set_margin_bottom(12)  # Add spacing to prevent overlap
        
        # Create radio buttons for mutually exclusive selection
        self.all_button = Gtk.ToggleButton(label="All")
        self.all_button.set_active(True)
        self.all_button.connect("toggled", self.on_filter_all)
        filter_box.append(self.all_button)
        
        self.valid_tokens_button = Gtk.ToggleButton(label="Valid Tokens")
        self.valid_tokens_button.connect("toggled", self.on_filter_valid_tokens)
        filter_box.append(self.valid_tokens_button)
        
        self.expired_tokens_button = Gtk.ToggleButton(label="Expired Tokens")
        self.expired_tokens_button.connect("toggled", self.on_filter_expired_tokens)
        filter_box.append(self.expired_tokens_button)
        
        search_box.append(filter_box)
        
        # Accounts list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_margin_start(12)
        scrolled.set_margin_end(12)
        scrolled.set_margin_bottom(12)
        main_box.append(scrolled)
        
        self.accounts_list = Gtk.ListBox()
        self.accounts_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.accounts_list.add_css_class("boxed-list")
        scrolled.set_child(self.accounts_list)
        
        # Empty state
        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.empty_box.set_vexpand(True)
        self.empty_box.set_valign(Gtk.Align.CENTER)
        
        empty_icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
        empty_icon.set_pixel_size(64)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)
        
        self.empty_label = Gtk.Label(label="No accounts found")
        self.empty_label.add_css_class("title-2")
        self.empty_label.add_css_class("dim-label")
        self.empty_box.append(self.empty_label)
        
        main_box.append(self.empty_box)
        self.empty_box.set_visible(False)
    
    def populate_accounts(self):
        """Populate the accounts list"""
        # Clear existing rows
        while self.accounts_list.get_first_child():
            self.accounts_list.remove(self.accounts_list.get_first_child())
        
        if not self.filtered_accounts:
            self.accounts_list.set_visible(False)
            self.empty_box.set_visible(True)
            return
        
        self.accounts_list.set_visible(True)
        self.empty_box.set_visible(False)
        
        for account in self.filtered_accounts:
            row = self.create_account_row(account)
            self.accounts_list.append(row)
        
        # Update count
        self.count_label.set_text(f"{len(self.filtered_accounts)} of {len(self.accounts)} accounts")
    
    def create_account_row(self, account):
        """Create a row for an account"""
        row = Adw.ActionRow()
        row.set_activatable(True)
        row.connect("activated", lambda _: self.on_account_clicked(account))
        
        # Account name and Steam ID
        row.set_title(account.account_name)
        
        # Add Steam ID and status info
        status_info = []
        if account.steamid:
            status_info.append(f"ID: {account.steamid}")
        
        # Check token status
        if hasattr(account, 'check_token_expiration'):
            token_status = account.check_token_expiration()
            if token_status.get("access_token_valid"):
                status_info.append("✅ Valid tokens")
            elif token_status.get("refresh_token_valid"):
                status_info.append("🔄 Needs refresh")
            else:
                status_info.append("❌ Expired tokens")
        
        row.set_subtitle(" • ".join(status_info))
        
        # Current account indicator
        if account == self.current_account:
            current_icon = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
            current_icon.set_pixel_size(16)
            current_icon.set_tooltip_text("Current account")
            row.add_prefix(current_icon)
        else:
            # Account icon
            account_icon = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
            account_icon.set_pixel_size(32)
            row.add_prefix(account_icon)
        
        # Arrow icon
        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        row.add_suffix(arrow)
        
        return row
    
    def on_account_clicked(self, account):
        """Handle account selection"""
        if account != self.current_account:
            self.emit("account-selected", account)
        self.close()
    
    def on_search_changed(self, entry):
        """Handle search input"""
        search_text = entry.get_text().lower()
        
        if not search_text:
            self.filtered_accounts = self.accounts.copy()
        else:
            self.filtered_accounts = []
            for account in self.accounts:
                # Search in account name and Steam ID
                if (search_text in account.account_name.lower() or
                    (account.steamid and search_text in str(account.steamid))):
                    self.filtered_accounts.append(account)
        
        self.populate_accounts()
    
    def on_filter_all(self, button):
        """Show all accounts"""
        if button.get_active():
            # Deactivate other filter buttons
            self.valid_tokens_button.set_active(False)
            self.expired_tokens_button.set_active(False)
            self.filtered_accounts = self.accounts.copy()
            self.populate_accounts()
        elif not self.valid_tokens_button.get_active() and not self.expired_tokens_button.get_active():
            # Ensure at least one button is always active
            button.set_active(True)
    
    def on_filter_valid_tokens(self, button):
        """Show only accounts with valid tokens"""
        if button.get_active():
            # Deactivate other filter buttons
            self.all_button.set_active(False)
            self.expired_tokens_button.set_active(False)
            self.filtered_accounts = []
            for account in self.accounts:
                if hasattr(account, 'check_token_expiration'):
                    token_status = account.check_token_expiration()
                    if token_status.get("access_token_valid"):
                        self.filtered_accounts.append(account)
            self.populate_accounts()
        elif not self.all_button.get_active() and not self.expired_tokens_button.get_active():
            # Ensure at least one button is always active
            button.set_active(True)
    
    def on_filter_expired_tokens(self, button):
        """Show only accounts with expired tokens"""
        if button.get_active():
            # Deactivate other filter buttons
            self.all_button.set_active(False)
            self.valid_tokens_button.set_active(False)
            self.filtered_accounts = []
            for account in self.accounts:
                if hasattr(account, 'check_token_expiration'):
                    token_status = account.check_token_expiration()
                    if not token_status.get("access_token_valid") and not token_status.get("refresh_token_valid"):
                        self.filtered_accounts.append(account)
            self.populate_accounts()
        elif not self.all_button.get_active() and not self.valid_tokens_button.get_active():
            # Ensure at least one button is always active
            button.set_active(True)