"""
Account Setup Dialog - Links new Steam accounts to the authenticator
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject
import asyncio
import threading
import logging

from account_linker import AccountLinker
from steam_protobuf_login import SteamProtobufLogin
from steam_guard import SteamGuardAccount
import base64
import json
import time


class SetupDialog(Adw.Window):
    """Multi-step dialog for setting up a new Steam account"""

    __gsignals__ = {
        'account-created': (GObject.SignalFlags.RUN_FIRST, None, (object,))
    }

    def __init__(self, parent=None, **kwargs):
        super().__init__(**kwargs)

        self.set_title("Set Up New Account")
        self.set_default_size(450, 500)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        # State
        self.pending_data = None
        self.sms_code_future = None
        self.linker = None
        self.access_token = None
        self.steamid = None

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

        # Stack for different steps
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_vexpand(True)
        self.toast_overlay.set_child(self.stack)

        # Step 1: Login
        self.stack.add_named(self.create_login_page(), "login")

        # Step 2: SMS Code
        self.stack.add_named(self.create_sms_page(), "sms")

        # Step 3: Success
        self.stack.add_named(self.create_success_page(), "success")

        # Step 4: Loading
        self.stack.add_named(self.create_loading_page(), "loading")

    def create_login_page(self) -> Gtk.Widget:
        """Create the login step"""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        page.set_margin_start(20)
        page.set_margin_end(20)

        # Title
        title = Gtk.Label(label="Link Steam Account")
        title.add_css_class("title-1")
        page.append(title)

        # Description
        desc = Gtk.Label(label="Enter your Steam login credentials to set up the authenticator.\n\nYour account must NOT already have Steam Guard enabled.")
        desc.set_wrap(True)
        desc.set_justify(Gtk.Justification.CENTER)
        desc.add_css_class("dim-label")
        page.append(desc)

        # Form
        form_group = Adw.PreferencesGroup()
        page.append(form_group)

        # Username
        self.username_row = Adw.EntryRow()
        self.username_row.set_title("Steam Username")
        form_group.add(self.username_row)

        # Password
        self.password_row = Adw.PasswordEntryRow()
        self.password_row.set_title("Password")
        self.password_row.connect("entry-activated", self.on_login_clicked)
        form_group.add(self.password_row)

        # Error message (hidden by default)
        self.error_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.error_box.set_margin_top(15)
        self.error_box.set_margin_bottom(5)
        self.error_box.set_visible(False)

        self.error_label = Gtk.Label()
        self.error_label.set_wrap(True)
        self.error_label.set_justify(Gtk.Justification.CENTER)
        # Apply red color via CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b".error-text { color: #e01b24; font-weight: bold; }")
        self.error_label.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.error_label.add_css_class("error-text")
        self.error_box.append(self.error_label)

        page.append(self.error_box)

        # Warning
        warning_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        warning_box.set_margin_top(10)
        warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warning_box.append(warning_icon)
        warning_label = Gtk.Label(label="Make sure you have a phone number linked to your Steam account")
        warning_label.set_wrap(True)
        warning_label.add_css_class("dim-label")
        warning_box.append(warning_label)
        page.append(warning_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        page.append(spacer)

        # Button
        self.login_button = Gtk.Button(label="Continue")
        self.login_button.add_css_class("suggested-action")
        self.login_button.add_css_class("pill")
        self.login_button.connect("clicked", self.on_login_clicked)
        page.append(self.login_button)

        return page

    def create_sms_page(self) -> Gtk.Widget:
        """Create the SMS verification step"""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        page.set_margin_start(20)
        page.set_margin_end(20)

        # Title
        title = Gtk.Label(label="Enter Verification Code")
        title.add_css_class("title-1")
        page.append(title)

        # Description
        self.sms_desc = Gtk.Label(label="Steam has sent a verification code to your phone.\nEnter it below to complete setup.")
        self.sms_desc.set_wrap(True)
        self.sms_desc.set_justify(Gtk.Justification.CENTER)
        self.sms_desc.add_css_class("dim-label")
        page.append(self.sms_desc)

        # Phone hint
        self.phone_hint_label = Gtk.Label()
        self.phone_hint_label.add_css_class("dim-label")
        page.append(self.phone_hint_label)

        # Code entry
        form_group = Adw.PreferencesGroup()
        page.append(form_group)

        self.sms_entry = Adw.EntryRow()
        self.sms_entry.set_title("Verification Code")
        self.sms_entry.connect("entry-activated", self.on_sms_submit)
        form_group.add(self.sms_entry)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        page.append(spacer)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)

        back_button = Gtk.Button(label="Cancel")
        back_button.connect("clicked", lambda b: self.close())
        button_box.append(back_button)

        self.sms_submit_button = Gtk.Button(label="Verify")
        self.sms_submit_button.add_css_class("suggested-action")
        self.sms_submit_button.add_css_class("pill")
        self.sms_submit_button.connect("clicked", self.on_sms_submit)
        button_box.append(self.sms_submit_button)

        page.append(button_box)

        return page

    def create_success_page(self) -> Gtk.Widget:
        """Create the success page"""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        page.set_margin_start(20)
        page.set_margin_end(20)

        # Success icon
        icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("success")
        page.append(icon)

        # Title
        title = Gtk.Label(label="Setup Complete!")
        title.add_css_class("title-1")
        page.append(title)

        # Description
        desc = Gtk.Label(label="Your Steam account is now linked.\nSave your revocation code in a safe place!")
        desc.set_wrap(True)
        desc.set_justify(Gtk.Justification.CENTER)
        page.append(desc)

        # Revocation code box
        revoke_group = Adw.PreferencesGroup()
        revoke_group.set_title("Revocation Code")
        revoke_group.set_description("Use this code to remove the authenticator if you lose access")
        page.append(revoke_group)

        self.revocation_row = Adw.ActionRow()
        self.revocation_row.set_title("R12345")
        self.revocation_row.add_css_class("monospace")

        copy_button = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.set_tooltip_text("Copy to clipboard")
        copy_button.connect("clicked", self.on_copy_revocation)
        self.revocation_row.add_suffix(copy_button)

        revoke_group.add(self.revocation_row)

        # Warning
        warning_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        warning_box.set_margin_top(10)
        warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warning_icon.add_css_class("warning")
        warning_box.append(warning_icon)
        warning_label = Gtk.Label(label="Write down this code! You will need it to remove the authenticator.")
        warning_label.set_wrap(True)
        warning_box.append(warning_label)
        page.append(warning_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        page.append(spacer)

        # Done button
        done_button = Gtk.Button(label="Done")
        done_button.add_css_class("suggested-action")
        done_button.add_css_class("pill")
        done_button.connect("clicked", lambda b: self.close())
        page.append(done_button)

        return page

    def create_loading_page(self) -> Gtk.Widget:
        """Create loading page"""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.set_margin_top(40)
        page.set_margin_bottom(40)
        page.set_margin_start(40)
        page.set_margin_end(40)
        page.set_valign(Gtk.Align.CENTER)

        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.start()
        page.append(spinner)

        self.loading_label = Gtk.Label(label="Connecting to Steam...")
        self.loading_label.add_css_class("title-3")
        page.append(self.loading_label)

        return page

    def on_login_clicked(self, widget):
        """Handle login button click"""
        # Hide any previous error
        self.hide_error()

        username = self.username_row.get_text().strip()
        password = self.password_row.get_text()

        if not username or not password:
            self.show_error("Please enter username and password")
            return

        self.stack.set_visible_child_name("loading")
        self.loading_label.set_text("Logging in to Steam...")

        # Start login in background thread
        def login_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def do_login():
                try:
                    async with SteamProtobufLogin() as login:
                        result = await login.complete_login_flow(username, password)
                        return result
                except Exception as e:
                    logging.error(f"Login error: {e}")
                    return {"error": str(e)}

            result = loop.run_until_complete(do_login())
            loop.close()
            GLib.idle_add(self.handle_login_result, result, username)

        thread = threading.Thread(target=login_thread)
        thread.daemon = True
        thread.start()

    def handle_login_result(self, result, username):
        """Handle login result"""
        if result.get("error"):
            self.show_error("Could not login. Please check your credentials.")
            self.stack.set_visible_child_name("login")
            return

        if result.get("needs_2fa"):
            self.show_error("This account already has Steam Guard enabled.\n\nTo use this account, you need to:\n1. Disable Steam Guard in your current authenticator\n2. Or use 'Import Account' if you have the .maFile")
            self.stack.set_visible_child_name("login")
            return

        if not result.get("success"):
            self.show_error("Login failed. Please try again.")
            self.stack.set_visible_child_name("login")
            return

        # Clear any previous error
        self.hide_error()

        # Store tokens
        self.access_token = result.get("access_token")
        self.refresh_token = result.get("refresh_token")
        self.username = username

        # Extract steamid from JWT
        try:
            token_parts = self.access_token.split('.')
            payload = json.loads(base64.b64decode(token_parts[1] + '=='))
            self.steamid = int(payload.get("sub", 0))
        except:
            self.show_toast("Could not process login. Please try again.")
            self.stack.set_visible_child_name("login")
            return

        # Now add authenticator
        self.loading_label.set_text("Adding authenticator...")
        self.add_authenticator()

    def add_authenticator(self):
        """Request to add authenticator"""
        def add_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def do_add():
                try:
                    async with AccountLinker() as linker:
                        linker.set_tokens(self.access_token, self.steamid)
                        self.linker = linker
                        result = await linker.add_authenticator()
                        return result
                except Exception as e:
                    logging.error(f"Add authenticator error: {e}")
                    return {"error": str(e)}

            result = loop.run_until_complete(do_add())
            loop.close()
            GLib.idle_add(self.handle_add_result, result)

        thread = threading.Thread(target=add_thread)
        thread.daemon = True
        thread.start()

    def handle_add_result(self, result):
        """Handle add authenticator result"""
        if result.get("error"):
            error = result.get("error")
            if error == "authenticator_present":
                self.show_error("This account already has Steam Guard enabled.\n\nTo use this account, you need to:\n1. Disable Steam Guard in your current authenticator\n2. Or use 'Import Account' if you have the .maFile")
            elif error == "no_phone":
                self.show_error("Your Steam account needs a phone number.\n\nPlease add a phone number to your Steam account first, then try again.")
            elif error == "confirm_email":
                self.show_error("Steam sent you a confirmation email.\n\nPlease click the link in that email, then try again.")
            else:
                self.show_error("Could not add authenticator. Please try again.")

            self.stack.set_visible_child_name("login")
            return

        # Store the pending data
        self.pending_data = result

        # Update SMS page
        phone_hint = result.get("phone_number_hint", "")
        confirm_type = result.get("confirm_type", 1)

        if confirm_type == 3:  # Email
            self.sms_desc.set_text("Steam has sent a verification code to your email.\nEnter it below to complete setup.")
            self.phone_hint_label.set_text("")
        else:  # SMS
            self.sms_desc.set_text("Steam has sent a verification code to your phone.\nEnter it below to complete setup.")
            if phone_hint:
                self.phone_hint_label.set_text(f"Phone ending in: {phone_hint}")

        # Show SMS page
        self.stack.set_visible_child_name("sms")
        self.sms_entry.set_text("")
        self.sms_entry.grab_focus()

    def on_sms_submit(self, widget):
        """Handle SMS code submission"""
        code = self.sms_entry.get_text().strip()

        if len(code) < 5:
            self.show_toast("Please enter the verification code")
            return

        self.stack.set_visible_child_name("loading")
        self.loading_label.set_text("Verifying code...")

        # Finalize in background
        def finalize_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def do_finalize():
                try:
                    async with AccountLinker() as linker:
                        linker.set_tokens(self.access_token, self.steamid)

                        shared_secret = self.pending_data.get("shared_secret")
                        server_time = self.pending_data.get("server_time", int(time.time()))

                        result = await linker.finalize_authenticator(code, shared_secret, server_time)

                        if result.get("success"):
                            # Verify status
                            status = await linker.query_status()
                            result["active"] = status.get("active", False)

                        return result
                except Exception as e:
                    logging.error(f"Finalize error: {e}")
                    return {"error": str(e)}

            result = loop.run_until_complete(do_finalize())
            loop.close()
            GLib.idle_add(self.handle_finalize_result, result)

        thread = threading.Thread(target=finalize_thread)
        thread.daemon = True
        thread.start()

    def handle_finalize_result(self, result):
        """Handle finalization result"""
        if result.get("error"):
            error = result.get("error")
            if error == "bad_code":
                self.show_toast("Invalid code. Please try again.")
            else:
                self.show_toast("Verification failed. Please try again.")
            self.stack.set_visible_child_name("sms")
            return

        if not result.get("success") or not result.get("active"):
            self.show_toast("Setup incomplete. Please try again.")
            self.stack.set_visible_child_name("sms")
            return

        # Success! Show revocation code
        revocation_code = self.pending_data.get("revocation_code", "")
        self.revocation_row.set_title(revocation_code)

        # Build account data
        account_data = {
            "account_name": self.username,
            "steamid": str(self.steamid),
            "shared_secret": self.pending_data.get("shared_secret"),
            "identity_secret": self.pending_data.get("identity_secret"),
            "revocation_code": revocation_code,
            "device_id": f"android:{self.steamid}",
            "token_gid": self.pending_data.get("token_gid", ""),
            "uri": self.pending_data.get("uri", ""),
            "Session": {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token or "",
            }
        }

        # Emit signal with account data
        self.emit('account-created', account_data)

        # Show success page
        self.stack.set_visible_child_name("success")

    def on_copy_revocation(self, button):
        """Copy revocation code to clipboard"""
        code = self.revocation_row.get_title()
        clipboard = self.get_clipboard()
        clipboard.set(code)
        self.show_toast("Revocation code copied")

    def show_toast(self, message: str):
        """Show a toast notification"""
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def show_error(self, message: str):
        """Show a persistent error message in red"""
        self.error_label.set_text(message)
        self.error_box.set_visible(True)

    def hide_error(self):
        """Hide the error message"""
        self.error_box.set_visible(False)
        self.error_label.set_text("")
