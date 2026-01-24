import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango
import asyncio
import threading
import logging
from typing import Optional, Dict, Any

from steam_protobuf_login import SteamProtobufLogin
from steam_guard import SteamGuardAccount


class LoginDialog(Adw.Window):
    """Steam login dialog similar to Windows Steam Desktop Authenticator"""
    
    def __init__(self, parent_window, **kwargs):
        super().__init__(**kwargs)
        
        self.set_title("Steam Login")
        self.set_default_size(380, 480)  # Slightly smaller and more compact
        self.set_transient_for(parent_window)
        self.set_modal(True)
        
        self.login_result = None
        self.pending_auth = None
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # Header bar
        header = Adw.HeaderBar()
        main_box.append(header)
        
        # Toast overlay
        self.toast_overlay = Adw.ToastOverlay()
        main_box.append(self.toast_overlay)
        
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.toast_overlay.set_child(scrolled)
        
        # Content box (more compact)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        scrolled.set_child(content_box)
        
        # Title and description (more compact)
        title_label = Gtk.Label(label="Steam Login")
        title_label.add_css_class("title-2")  # Smaller than title-1
        title_label.set_halign(Gtk.Align.CENTER)
        content_box.append(title_label)
        
        # Description (shorter and more concise)
        desc_label = Gtk.Label()
        desc_label.set_markup(
            "🔐 <b>Generate Fresh Tokens</b>\n"
            "Creates new Steam session tokens for trade confirmations."
        )
        desc_label.set_wrap(True)
        desc_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_label.set_justify(Gtk.Justification.CENTER)
        desc_label.add_css_class("dim-label")
        desc_label.set_max_width_chars(40)  # Limit width to prevent overflow
        content_box.append(desc_label)
        
        # Login form
        self.login_group = Adw.PreferencesGroup()
        self.login_group.set_title("Credentials")
        content_box.append(self.login_group)
        
        # Username entry
        self.username_entry = Adw.EntryRow()
        self.username_entry.set_title("Username")
        self.username_entry.connect("changed", self.on_field_changed)
        self.login_group.add(self.username_entry)
        
        # Password entry
        self.password_entry = Adw.PasswordEntryRow()
        self.password_entry.set_title("Password")
        self.password_entry.connect("changed", self.on_field_changed)
        self.login_group.add(self.password_entry)
        
        # Login button
        self.login_button = Gtk.Button(label="Sign In")
        self.login_button.add_css_class("suggested-action")
        self.login_button.set_sensitive(False)
        self.login_button.connect("clicked", self.on_login_clicked)
        content_box.append(self.login_button)
        
        # 2FA section (initially hidden)
        self.twofa_group = Adw.PreferencesGroup()
        self.twofa_group.set_title("Two-Factor Authentication")
        self.twofa_group.set_description("Enter the code from your Steam Guard mobile app")
        content_box.append(self.twofa_group)
        
        # 2FA code entry
        self.twofa_entry = Adw.EntryRow()
        self.twofa_entry.set_title("Steam Guard Code")
        self.twofa_entry.set_input_hints(Gtk.InputHints.NO_SPELLCHECK)
        self.twofa_entry.connect("changed", self.on_twofa_changed)
        self.twofa_entry.connect("activate", self.on_submit_2fa)
        self.twofa_group.add(self.twofa_entry)
        
        # Submit 2FA button
        self.submit_2fa_button = Gtk.Button(label="Submit Code")
        self.submit_2fa_button.add_css_class("suggested-action")
        self.submit_2fa_button.set_sensitive(False)
        self.submit_2fa_button.connect("clicked", self.on_submit_2fa)
        content_box.append(self.submit_2fa_button)
        
        # Progress section
        self.progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.progress_box.set_valign(Gtk.Align.CENTER)
        
        self.progress_spinner = Gtk.Spinner()
        self.progress_spinner.set_size_request(32, 32)
        self.progress_box.append(self.progress_spinner)
        
        self.progress_label = Gtk.Label()
        self.progress_label.add_css_class("dim-label")
        self.progress_box.append(self.progress_label)
        
        content_box.append(self.progress_box)
        
        # Initially show only login form
        self.show_login_form()
    
    def show_login_form(self):
        """Show the initial login form"""
        self.login_group.set_visible(True)
        self.login_button.set_visible(True)
        self.twofa_group.set_visible(False)
        self.submit_2fa_button.set_visible(False)
        self.progress_box.set_visible(False)
    
    def show_2fa_form(self):
        """Show the 2FA code entry form"""
        self.login_group.set_visible(False)
        self.login_button.set_visible(False)
        self.twofa_group.set_visible(True)
        self.submit_2fa_button.set_visible(True)
        self.progress_box.set_visible(False)
        self.twofa_entry.grab_focus()
    
    def show_progress(self, message: str):
        """Show progress spinner with message"""
        self.login_group.set_visible(False)
        self.login_button.set_visible(False)
        self.twofa_group.set_visible(False)
        self.submit_2fa_button.set_visible(False)
        self.progress_box.set_visible(True)
        self.progress_spinner.start()
        self.progress_label.set_text(message)
    
    def on_field_changed(self, entry):
        """Enable login button when both fields are filled"""
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text().strip()
        self.login_button.set_sensitive(bool(username and password))
    
    def on_twofa_changed(self, entry):
        """Enable submit button when 2FA code is entered"""
        code = self.twofa_entry.get_text().strip()
        self.submit_2fa_button.set_sensitive(len(code) >= 5)
    
    def on_login_clicked(self, button):
        """Handle login button click"""
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text().strip()
        
        if not username or not password:
            self.show_toast("Please enter both username and password")
            return
        
        self.show_progress("Signing in to Steam...")
        
        # Start login in background thread
        def login_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def do_login():
                async with SteamProtobufLogin() as steam_login:
                    # Check if this account has Steam Guard enabled
                    parent_app = self.get_transient_for().get_application()
                    current_account = parent_app.current_account
                    
                    # If this is the same account we have loaded, use automatic 2FA
                    if (current_account and 
                        current_account.account_name == username and 
                        current_account.shared_secret):
                        
                        # Create auto 2FA callback
                        async def auto_2fa_callback():
                            code = current_account.generate_steam_guard_code()
                            logging.info(f"🤖 Auto-generated Steam Guard code: {code}")
                            return code
                        
                        return await steam_login.complete_login_flow(username, password, auto_2fa_callback)
                    else:
                        # Manual 2FA flow for different accounts
                        return await steam_login.complete_login_flow(username, password)
            
            try:
                result = loop.run_until_complete(do_login())
                GLib.idle_add(self.handle_login_result, result)
            except Exception as e:
                logging.error(f"Login error: {e}")
                GLib.idle_add(self.handle_login_result, {"error": str(e)})
            finally:
                loop.close()
        
        thread = threading.Thread(target=login_thread)
        thread.daemon = True
        thread.start()
    
    def handle_login_result(self, result):
        """Handle login result on main thread"""
        if result.get("error"):
            error_msg = result['error']
            # Make error messages more user-friendly
            if "invalid" in error_msg.lower() or "password" in error_msg.lower():
                self.show_toast("Incorrect username or password")
            elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
                self.show_toast("Too many attempts. Please wait a moment.")
            elif "network" in error_msg.lower() or "connection" in error_msg.lower():
                self.show_toast("Connection error. Please check your internet.")
            else:
                self.show_toast("Could not sign in. Please try again.")
            self.show_login_form()
        elif result.get("needs_2fa"):
            self.pending_auth = result
            self.show_2fa_form()
        elif result.get("success"):
            self.login_result = result
            self.show_progress("Login successful!")
            # Close after showing success message
            GLib.timeout_add(2000, lambda: self.close())
        else:
            self.show_toast("Something went wrong. Please try again.")
            self.show_login_form()

        return False
    
    def on_submit_2fa(self, widget):
        """Handle 2FA code submission"""
        if not self.pending_auth:
            return
        
        code = self.twofa_entry.get_text().strip()
        if len(code) < 5:
            self.show_toast("Please enter a valid Steam Guard code")
            return
        
        self.show_progress("Verifying Steam Guard code...")
        
        # Submit 2FA code in background thread
        def submit_2fa_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def do_submit():
                async with SteamProtobufLogin() as steam_login:
                    return await steam_login.complete_2fa_login(
                        self.pending_auth["client_id"],
                        self.pending_auth["request_id"],
                        self.pending_auth["steamid"],
                        code
                    )
            
            try:
                result = loop.run_until_complete(do_submit())
                GLib.idle_add(self.handle_2fa_result, result)
            except Exception as e:
                logging.error(f"2FA error: {e}")
                GLib.idle_add(self.handle_2fa_result, {"error": str(e)})
            finally:
                loop.close()
        
        thread = threading.Thread(target=submit_2fa_thread)
        thread.daemon = True
        thread.start()
    
    def handle_2fa_result(self, result):
        """Handle 2FA result on main thread"""
        if result.get("error"):
            error_msg = result['error']
            if "invalid" in error_msg.lower() or "incorrect" in error_msg.lower():
                self.show_toast("Invalid code. Please try again.")
            elif "expired" in error_msg.lower():
                self.show_toast("Code expired. Please enter the new code.")
            else:
                self.show_toast("Could not verify code. Please try again.")
            self.show_2fa_form()
            self.twofa_entry.set_text("")
        elif result.get("success"):
            self.login_result = result
            self.show_progress("Authentication complete!")
            # Close after showing success message
            GLib.timeout_add(2000, lambda: self.close())
        else:
            self.show_toast("Something went wrong. Please try again.")
            self.show_2fa_form()

        return False
    
    def show_toast(self, message: str):
        """Show a toast notification"""
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)
    
    def get_login_result(self) -> Optional[Dict[str, Any]]:
        """Get the login result after dialog closes"""
        return self.login_result