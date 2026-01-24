import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio
import asyncio
import threading
from typing import List, Dict, Any

from steam_guard import SteamGuardAccount
from steam_api import SteamAPI


class ExpandableConfirmationRow(Gtk.ListBoxRow):
    """Expandable row for trade confirmations with detailed item view"""
    
    def __init__(self, confirmation: Dict[str, Any], account: SteamGuardAccount, **kwargs):
        super().__init__(**kwargs)
        
        self.confirmation = confirmation
        self.account = account
        self.expanded = False
        self.trade_details = None
        
        self.setup_ui()
    
    def setup_ui(self):
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(main_box)
        
        # Header row (always visible)
        self.header_row = Adw.ActionRow()
        main_box.append(self.header_row)
        
        # Get confirmation details
        conf_type = self.confirmation.get("type", "Trade")
        title = self.confirmation.get("title", conf_type)
        description = self.confirmation.get("description", "")
        
        self.header_row.set_title(title)
        if description:
            self.header_row.set_subtitle(description)
        
        # Add icon
        image = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
        image.set_pixel_size(32)
        self.header_row.add_prefix(image)
        
        # Expand arrow button
        self.expand_button = Gtk.Button()
        self.expand_button.set_icon_name("pan-end-symbolic")
        self.expand_button.add_css_class("flat")
        self.expand_button.add_css_class("circular")
        self.expand_button.set_tooltip_text("Show trade details")
        self.expand_button.connect("clicked", self.on_expand_clicked)
        self.header_row.add_suffix(self.expand_button)
        
        # Action buttons
        button_box = Gtk.Box(spacing=6)
        button_box.set_valign(Gtk.Align.CENTER)
        
        accept_button = Gtk.Button()
        accept_button.set_icon_name("emblem-ok-symbolic")
        accept_button.add_css_class("suggested-action")
        accept_button.add_css_class("circular")
        accept_button.set_tooltip_text("Accept")
        accept_button.connect("clicked", self.on_accept_clicked)
        button_box.append(accept_button)
        
        deny_button = Gtk.Button()
        deny_button.set_icon_name("window-close-symbolic")
        deny_button.add_css_class("destructive-action")
        deny_button.add_css_class("circular")
        deny_button.set_tooltip_text("Deny")
        deny_button.connect("clicked", self.on_deny_clicked)
        button_box.append(deny_button)
        
        self.header_row.add_suffix(button_box)
        
        # Expandable details section (initially hidden)
        self.details_revealer = Gtk.Revealer()
        self.details_revealer.set_reveal_child(False)
        main_box.append(self.details_revealer)
        
        # Details content
        self.details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.details_box.set_margin_top(12)
        self.details_box.set_margin_bottom(12)
        self.details_box.set_margin_start(48)  # Indent to align with title
        self.details_box.set_margin_end(12)
        self.details_revealer.set_child(self.details_box)
        
        # Loading spinner for details
        self.loading_spinner = Gtk.Spinner()
        self.loading_spinner.set_size_request(24, 24)
        self.details_box.append(self.loading_spinner)
        
        loading_label = Gtk.Label(label="Loading trade details...")
        loading_label.add_css_class("dim-label")
        self.details_box.append(loading_label)
    
    def on_expand_clicked(self, button):
        """Toggle expansion of trade details"""
        if not self.expanded:
            # Expand and load details
            self.expanded = True
            self.expand_button.set_icon_name("pan-down-symbolic")
            self.details_revealer.set_reveal_child(True)
            
            if self.trade_details is None:
                self.load_trade_details()
        else:
            # Collapse
            self.expanded = False
            self.expand_button.set_icon_name("pan-end-symbolic")
            self.details_revealer.set_reveal_child(False)
    
    def load_trade_details(self):
        """Load detailed trade information"""
        # Clear loading content
        while self.details_box.get_first_child():
            self.details_box.remove(self.details_box.get_first_child())
        
        if self.confirmation.get("type_id") == 2:  # Trade offers
            self.show_trade_details({})
        else:
            self.show_no_details()
    
    def show_trade_details(self, details):
        """Display the trade details"""
        # For now, show the description we already have from the confirmation
        # In a more advanced version, this would parse the Steam trade offer page
        
        description = self.confirmation.get("description", "")
        if description:
            # Parse the existing description which has format "You will give up X | You will receive Y"
            parts = description.split(" | ")
            
            # Show what you're giving
            if len(parts) > 0 and "give up" in parts[0].lower():
                give_text = parts[0].replace("You will give up your ", "").replace("You will give up ", "")
                give_group = Adw.PreferencesGroup()
                give_group.set_title("📤 You will give:")
                give_group.set_margin_top(8)
                
                give_row = Adw.ActionRow()
                give_row.set_title(give_text)
                
                # Add item icon
                item_icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
                item_icon.set_pixel_size(20)
                give_row.add_prefix(item_icon)
                
                give_group.add(give_row)
                self.details_box.append(give_group)
            
            # Show what you're receiving
            if len(parts) > 1:
                receive_text = parts[1].replace("You will receive ", "")
                receive_group = Adw.PreferencesGroup()
                receive_group.set_title("📥 You will receive:")
                receive_group.set_margin_top(8)
                
                if receive_text.lower() == "nothing":
                    nothing_row = Adw.ActionRow()
                    nothing_row.set_title("Nothing")
                    nothing_row.add_css_class("dim-label")
                    
                    nothing_icon = Gtk.Image.new_from_icon_name("action-unavailable-symbolic")
                    nothing_icon.set_pixel_size(20)
                    nothing_row.add_prefix(nothing_icon)
                    
                    receive_group.add(nothing_row)
                else:
                    receive_row = Adw.ActionRow()
                    receive_row.set_title(receive_text)
                    
                    # Add item icon
                    item_icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
                    item_icon.set_pixel_size(20)
                    receive_row.add_prefix(item_icon)
                    
                    receive_group.add(receive_row)
                
                self.details_box.append(receive_group)
        
        # Trade ID info
        trade_id = self.confirmation.get("id", "")
        if trade_id:
            info_group = Adw.PreferencesGroup()
            info_group.set_title("Trade Information")
            info_group.set_margin_top(8)
            
            id_row = Adw.ActionRow()
            id_row.set_title("Trade Offer ID")
            id_row.set_subtitle(trade_id)
            
            info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
            info_icon.set_pixel_size(20)
            id_row.add_prefix(info_icon)
            
            info_group.add(id_row)
            self.details_box.append(info_group)
    
    def show_no_details(self):
        """Show message when details can't be loaded"""
        error_label = Gtk.Label(label="Unable to load trade details")
        error_label.add_css_class("dim-label")
        self.details_box.append(error_label)
    
    def on_accept_clicked(self, button):
        """Handle accept button click"""
        parent = self.get_parent()
        while parent and not isinstance(parent, ConfirmationsDialog):
            parent = parent.get_parent()
        
        if parent:
            parent.respond_to_confirmation(self.confirmation, True)
    
    def on_deny_clicked(self, button):
        """Handle deny button click"""
        parent = self.get_parent()
        while parent and not isinstance(parent, ConfirmationsDialog):
            parent = parent.get_parent()
        
        if parent:
            parent.respond_to_confirmation(self.confirmation, False)


class ConfirmationsDialog(Adw.Window):
    def __init__(self, parent_window, account: SteamGuardAccount, **kwargs):
        super().__init__(**kwargs)
        
        self.set_title("Trade Confirmations")
        self.set_default_size(600, 500)
        self.set_transient_for(parent_window)
        self.set_modal(True)
        
        self.account = account
        self.confirmations = []
        self.selected_confirmations = set()
        
        self.setup_ui()
        self.refresh_confirmations()
    
    def setup_ui(self):
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # Header bar
        header = Adw.HeaderBar()
        main_box.append(header)
        
        # Refresh button in header
        refresh_button = Gtk.Button()
        refresh_button.set_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh confirmations")
        refresh_button.connect("clicked", lambda _: self.refresh_confirmations())
        header.pack_start(refresh_button)
        
        # Action buttons in header
        self.accept_all_button = Gtk.Button(label="Accept All")
        self.accept_all_button.add_css_class("suggested-action")
        self.accept_all_button.set_sensitive(False)
        self.accept_all_button.connect("clicked", self.on_accept_all)
        header.pack_end(self.accept_all_button)
        
        self.deny_all_button = Gtk.Button(label="Deny All")
        self.deny_all_button.add_css_class("destructive-action")
        self.deny_all_button.set_sensitive(False)
        self.deny_all_button.connect("clicked", self.on_deny_all)
        header.pack_end(self.deny_all_button)
        
        # Toast overlay
        self.toast_overlay = Adw.ToastOverlay()
        main_box.append(self.toast_overlay)
        
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.toast_overlay.set_child(scrolled)
        
        # Content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        scrolled.set_child(content_box)
        
        # Loading spinner
        self.loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.loading_box.set_vexpand(True)
        self.loading_box.set_valign(Gtk.Align.CENTER)
        
        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.start()
        self.loading_box.append(spinner)
        
        loading_label = Gtk.Label(label="Loading confirmations...")
        self.loading_box.append(loading_label)
        
        content_box.append(self.loading_box)
        
        # Confirmations list
        self.confirmations_list = Gtk.ListBox()
        self.confirmations_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.confirmations_list.add_css_class("boxed-list")
        content_box.append(self.confirmations_list)
        self.confirmations_list.set_visible(False)
        
        # Empty state
        self.empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.empty_box.set_vexpand(True)
        self.empty_box.set_valign(Gtk.Align.CENTER)
        
        empty_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        empty_icon.set_pixel_size(64)
        empty_icon.add_css_class("dim-label")
        self.empty_box.append(empty_icon)
        
        empty_label = Gtk.Label(label="No pending confirmations")
        empty_label.add_css_class("title-2")
        empty_label.add_css_class("dim-label")
        self.empty_box.append(empty_label)
        
        content_box.append(self.empty_box)
        self.empty_box.set_visible(False)
    
    def refresh_confirmations(self):
        self.loading_box.set_visible(True)
        self.confirmations_list.set_visible(False)
        self.empty_box.set_visible(False)
        
        # Clear existing confirmations
        while self.confirmations_list.get_first_child():
            self.confirmations_list.remove(self.confirmations_list.get_first_child())
        
        # Run async task
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def fetch():
                async with SteamAPI() as api:
                    return await api.get_confirmations(self.account)
            
            try:
                return loop.run_until_complete(fetch())
            except Exception as e:
                print(f"Error fetching confirmations: {e}")
                return None
            finally:
                loop.close()
        
        # Run in thread to avoid blocking UI
        def on_complete(confirmations):
            self.loading_box.set_visible(False)
            
            if confirmations is None:
                self.show_toast("Could not load confirmations. Please try refreshing.")
                self.empty_box.set_visible(True)
                return
            
            self.confirmations = confirmations
            
            if not confirmations:
                self.empty_box.set_visible(True)
                self.accept_all_button.set_sensitive(False)
                self.deny_all_button.set_sensitive(False)
            else:
                self.confirmations_list.set_visible(True)
                self.accept_all_button.set_sensitive(True)
                self.deny_all_button.set_sensitive(True)
                self.display_confirmations(confirmations)
            
            return False
        
        # Start async operation
        def thread_func():
            result = run_async()
            GLib.idle_add(on_complete, result)
        
        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()
    
    def display_confirmations(self, confirmations):
        for conf in confirmations:
            # Create expandable row for detailed view
            expandable_row = ExpandableConfirmationRow(conf, self.account)
            self.confirmations_list.append(expandable_row)
    
    def on_accept_single(self, button, confirmation):
        self.respond_to_confirmation(confirmation, True)
    
    def on_deny_single(self, button, confirmation):
        self.respond_to_confirmation(confirmation, False)
    
    def on_accept_all(self, button):
        if not self.confirmations:
            return
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Accept All Confirmations",
            body=f"Are you sure you want to accept all {len(self.confirmations)} confirmations?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("accept", "Accept All")
        dialog.set_response_appearance("accept", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self.on_accept_all_response)
        dialog.present()
    
    def on_deny_all(self, button):
        if not self.confirmations:
            return
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Deny All Confirmations",
            body=f"Are you sure you want to deny all {len(self.confirmations)} confirmations?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("deny", "Deny All")
        dialog.set_response_appearance("deny", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self.on_deny_all_response)
        dialog.present()
    
    def on_accept_all_response(self, dialog, response):
        if response == "accept":
            self.respond_to_all_confirmations(True)
    
    def on_deny_all_response(self, dialog, response):
        if response == "deny":
            self.respond_to_all_confirmations(False)
    
    def respond_to_confirmation(self, confirmation, accept: bool):
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def respond():
                async with SteamAPI() as api:
                    return await api.respond_to_confirmation(
                        self.account,
                        confirmation["id"],
                        confirmation["key"],
                        accept
                    )
            
            try:
                return loop.run_until_complete(respond())
            except Exception as e:
                print(f"Error responding to confirmation: {e}")
                return False
            finally:
                loop.close()
        
        def on_complete(success):
            if success:
                action = "accepted" if accept else "denied"
                self.show_toast(f"Confirmation {action}")
                self.refresh_confirmations()
            else:
                self.show_toast("Could not process confirmation. Session may have expired.")
            return False
        
        # Start async operation
        def thread_func():
            result = run_async()
            GLib.idle_add(on_complete, result)
        
        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()
    
    def respond_to_all_confirmations(self, accept: bool):
        if not self.confirmations:
            return
        
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def respond_all():
                async with SteamAPI() as api:
                    conf_ids = [c["id"] for c in self.confirmations]
                    conf_keys = [c["key"] for c in self.confirmations]
                    return await api.respond_to_multiple_confirmations(
                        self.account,
                        conf_ids,
                        conf_keys,
                        accept
                    )
            
            try:
                return loop.run_until_complete(respond_all())
            except Exception as e:
                print(f"Error responding to all confirmations: {e}")
                return False
            finally:
                loop.close()
        
        def on_complete(success):
            if success:
                action = "accepted" if accept else "denied"
                self.show_toast(f"All confirmations {action}")
                self.refresh_confirmations()
            else:
                self.show_toast("Could not process confirmations. Session may have expired.")
            return False

        # Start async operation
        def thread_func():
            result = run_async()
            GLib.idle_add(on_complete, result)
        
        thread = threading.Thread(target=thread_func)
        thread.daemon = True
        thread.start()
    
    def show_toast(self, message: str):
        toast = Adw.Toast(title=message)
        toast.set_timeout(2)
        self.toast_overlay.add_toast(toast)