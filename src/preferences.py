import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GObject
import json
import os
from pathlib import Path


class PreferencesManager:
    """Manages application preferences with persistent storage"""
    
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "steam-authenticator"
        self.config_file = self.config_dir / "preferences.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.defaults = {
            "theme": "light",  # light, dark, crimson
            "font_size": "large",  # small, medium, large, extra-large
            "show_countdown": True,
            "steam_api_key": "",  # Steam Web API key for profile data
        }
        
        self.settings = self.load_preferences()
    
    def load_preferences(self):
        """Load preferences from file or return defaults"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    saved_prefs = json.load(f)
                # Merge with defaults to handle new settings
                merged = self.defaults.copy()
                merged.update(saved_prefs)
                return merged
            return self.defaults.copy()
        except Exception:
            return self.defaults.copy()
    
    def save_preferences(self):
        """Save current preferences to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save preferences: {e}")
    
    def get(self, key, default=None):
        """Get a preference value"""
        return self.settings.get(key, default)
    
    def set(self, key, value):
        """Set a preference value and save"""
        self.settings[key] = value
        self.save_preferences()
    
    def reset_to_defaults(self):
        """Reset all preferences to defaults"""
        self.settings = self.defaults.copy()
        self.save_preferences()


class PreferencesWindow(Adw.PreferencesWindow):
    """Modern preferences window using Adwaita preferences components"""
    
    def __init__(self, parent, preferences_manager):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Preferences")
        self.set_default_size(600, 700)
        
        self.prefs = preferences_manager
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the preferences UI"""
        
        # General page
        general_page = Adw.PreferencesPage()
        general_page.set_title("General")
        general_page.set_icon_name("preferences-system-symbolic")
        self.add(general_page)
        
        # Appearance group
        appearance_group = Adw.PreferencesGroup()
        appearance_group.set_title("Appearance")
        appearance_group.set_description("Customize the look and feel")
        general_page.add(appearance_group)
        
        # Theme selection
        theme_row = Adw.ComboRow()
        theme_row.set_title("Theme")
        theme_row.set_subtitle("Choose application theme")
        theme_model = Gtk.StringList()
        theme_model.append("Light")
        theme_model.append("Dark")
        theme_model.append("Crimson")
        theme_model.append("Ocean")
        theme_model.append("Forest")
        theme_model.append("Purple")
        theme_model.append("Sunset")
        theme_model.append("Nord")
        theme_row.set_model(theme_model)

        theme_map = {"light": 0, "dark": 1, "crimson": 2, "ocean": 3, "forest": 4, "purple": 5, "sunset": 6, "nord": 7}
        reverse_theme_map = {0: "light", 1: "dark", 2: "crimson", 3: "ocean", 4: "forest", 5: "purple", 6: "sunset", 7: "nord"}
        theme_row.set_selected(theme_map.get(self.prefs.get("theme"), 0))
        theme_row.connect("notify::selected", lambda row, _: 
                         self.apply_theme_via_app(reverse_theme_map[row.get_selected()]))
        appearance_group.add(theme_row)
        
        # Font size
        font_row = Adw.ComboRow()
        font_row.set_title("Code Font Size")
        font_row.set_subtitle("Size of Steam Guard codes")
        font_model = Gtk.StringList()
        font_model.append("Small")
        font_model.append("Medium")
        font_model.append("Large")
        font_model.append("Extra Large")
        font_row.set_model(font_model)
        
        font_map = {"small": 0, "medium": 1, "large": 2, "extra-large": 3}
        reverse_font_map = {0: "small", 1: "medium", 2: "large", 3: "extra-large"}
        font_row.set_selected(font_map.get(self.prefs.get("font_size"), 2))
        font_row.connect("notify::selected", lambda row, _:
                        self.apply_font_size(reverse_font_map[row.get_selected()]))
        appearance_group.add(font_row)
        
        # Show countdown
        countdown_row = Adw.SwitchRow()
        countdown_row.set_title("Show Countdown Timer")
        countdown_row.set_subtitle("Display time remaining for current code")
        countdown_row.set_active(self.prefs.get("show_countdown", True))
        countdown_row.connect("notify::active", lambda row, _:
                              self.prefs.set("show_countdown", row.get_active()))
        appearance_group.add(countdown_row)

        # Steam API group
        api_group = Adw.PreferencesGroup()
        api_group.set_title("Steam Web API")
        api_group.set_description("Configure Steam API for profile pictures and data")
        general_page.add(api_group)

        # API Key row with edit/save functionality
        self.api_key_row = Adw.ActionRow()
        self.api_key_row.set_title("API Key")
        self.api_key_editing = False

        # Entry for editing (hidden by default)
        self.api_key_entry = Gtk.Entry()
        self.api_key_entry.set_visibility(False)  # Password-style
        self.api_key_entry.set_hexpand(True)
        self.api_key_entry.set_valign(Gtk.Align.CENTER)
        self.api_key_entry.set_visible(False)

        # Label showing masked key (visible by default)
        self.api_key_label = Gtk.Label()
        self.api_key_label.set_hexpand(True)
        self.api_key_label.set_xalign(0)
        self.api_key_label.add_css_class("dim-label")

        # Edit/Save button
        self.api_key_button = Gtk.Button()
        self.api_key_button.set_valign(Gtk.Align.CENTER)
        self.api_key_button.connect("clicked", self.on_api_key_button_clicked)

        self.api_key_row.add_suffix(self.api_key_label)
        self.api_key_row.add_suffix(self.api_key_entry)
        self.api_key_row.add_suffix(self.api_key_button)
        api_group.add(self.api_key_row)

        # Initialize display state
        self._update_api_key_display()

        # Get API key link
        api_link_row = Adw.ActionRow()
        api_link_row.set_title("Get Steam API Key")
        api_link_row.set_subtitle("Open Steam to create an API key")
        api_link_row.add_suffix(Gtk.Image.new_from_icon_name("globe-symbolic"))
        api_link_row.set_activatable(True)
        api_link_row.connect("activated", self.on_get_api_key_clicked)
        api_group.add(api_link_row)
    
    def apply_theme_via_app(self, theme_name):
        """Apply the selected theme via the main application"""
        self.prefs.set("theme", theme_name)
        
        # Get the main application and apply theme through it
        app = self.get_transient_for().get_application()
        if app and hasattr(app, 'apply_theme'):
            app.apply_theme(theme_name)
    
    def apply_crimson_theme(self):
        """Apply the crimson (red neon) theme"""
        self.crimson_css_provider = Gtk.CssProvider()
        self.crimson_css_provider.load_from_data(b"""
            @define-color accent_color #ff0040;
            @define-color accent_bg_color #ff0040;
            @define-color accent_fg_color #ffffff;
            @define-color destructive_color #ff3366;
            @define-color destructive_bg_color #ff3366;
            @define-color destructive_fg_color #ffffff;
            @define-color success_color #ff6699;
            @define-color success_bg_color #ff6699;
            @define-color success_fg_color #ffffff;
            @define-color warning_color #ff9933;
            @define-color warning_bg_color #ff9933;
            @define-color warning_fg_color #ffffff;
            @define-color error_color #ff0066;
            @define-color error_bg_color #ff0066;
            @define-color error_fg_color #ffffff;
            
            /* Background colors */
            @define-color window_bg_color #1a0005;
            @define-color view_bg_color #220008;
            @define-color card_bg_color #2a000a;
            @define-color headerbar_bg_color #330011;
            @define-color popover_bg_color #220008;
            @define-color dialog_bg_color #1a0005;
            
            window {
                background-color: #1a0005;
            }
            
            .title-1, .code-small, .code-medium, .code-large, .code-extra-large {
                color: #ff0040;
                text-shadow: 0 0 3px rgba(255, 0, 64, 0.5);
            }
            
            button.suggested-action {
                background: linear-gradient(45deg, #ff0040, #ff3366);
                border: 1px solid #ff0040;
                box-shadow: 0 0 3px rgba(255, 0, 64, 0.2);
            }
            
            button.suggested-action:hover {
                background: linear-gradient(45deg, #ff3366, #ff6699);
                box-shadow: 0 0 5px rgba(255, 0, 64, 0.3);
            }
            
            .card {
                background-color: #2a000a;
                border: 1px solid rgba(255, 0, 64, 0.15);
                box-shadow: 0 0 2px rgba(255, 0, 64, 0.1);
            }
            
            headerbar {
                background: linear-gradient(90deg, #1a0005, #330011);
                border-bottom: 1px solid rgba(255, 0, 64, 0.3);
            }
            
            .view, scrolledwindow > viewport {
                background-color: #220008;
            }
        """)
        
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            self.crimson_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def clear_crimson_theme(self):
        """Remove crimson theme CSS"""
        if hasattr(self, 'crimson_css_provider') and self.crimson_css_provider:
            Gtk.StyleContext.remove_provider_for_display(
                self.get_display(),
                self.crimson_css_provider
            )
            self.crimson_css_provider = None
    
    def apply_font_size(self, font_size):
        """Apply the selected font size"""
        self.prefs.set("font_size", font_size)

        # Get the main application window to update font
        app = self.get_transient_for().get_application()
        if app and hasattr(app, 'main_window'):
            app.main_window.update_code_font_size(font_size)

    def _update_api_key_display(self):
        """Update the API key row display based on current state"""
        current_key = self.prefs.get("steam_api_key", "")

        if self.api_key_editing:
            # Show entry, hide label
            self.api_key_label.set_visible(False)
            self.api_key_entry.set_visible(True)
            self.api_key_entry.set_text(current_key)
            self.api_key_entry.grab_focus()
            self.api_key_button.set_icon_name("emblem-ok-symbolic")
            self.api_key_button.set_tooltip_text("Save")
            self.api_key_button.add_css_class("suggested-action")
        else:
            # Show label, hide entry
            self.api_key_entry.set_visible(False)
            self.api_key_label.set_visible(True)

            if current_key:
                # Show masked key
                masked = current_key[:4] + "•" * 20 + current_key[-4:] if len(current_key) > 8 else "•" * len(current_key)
                self.api_key_label.set_text(masked)
                self.api_key_row.set_subtitle("Saved")
            else:
                self.api_key_label.set_text("Not configured")
                self.api_key_row.set_subtitle("Click Edit to add your API key")

            self.api_key_button.set_icon_name("document-edit-symbolic")
            self.api_key_button.set_tooltip_text("Edit")
            self.api_key_button.remove_css_class("suggested-action")

    def on_api_key_button_clicked(self, button):
        """Handle Edit/Save button click"""
        if self.api_key_editing:
            # Save the key
            new_key = self.api_key_entry.get_text().strip()
            self.prefs.set("steam_api_key", new_key)
            self.api_key_editing = False
            self._update_api_key_display()

            # Show feedback
            parent = self.get_transient_for()
            if parent and hasattr(parent, 'show_toast'):
                if new_key:
                    parent.show_toast("API key saved")
                else:
                    parent.show_toast("API key removed")
        else:
            # Enter edit mode
            self.api_key_editing = True
            self._update_api_key_display()

    def on_get_api_key_clicked(self, row):
        """Open Steam API key registration page"""
        import subprocess
        subprocess.Popen(["xdg-open", "https://steamcommunity.com/dev/apikey"])