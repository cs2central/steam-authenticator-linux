#!/bin/bash
# AppImage build script for Steam Authenticator
# Requires: appimagetool, python3

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$PROJECT_DIR/build/appimage"
APP_DIR="$BUILD_DIR/SteamAuthenticator.AppDir"

echo "Building AppImage for Steam Authenticator..."

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$APP_DIR"

# Create AppDir structure
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/applications"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/usr/share/steam-authenticator"

# Copy application files
cp -r "$PROJECT_DIR/src/"* "$APP_DIR/usr/share/steam-authenticator/"

# Create launcher script
cat > "$APP_DIR/usr/bin/steam-authenticator" << 'EOF'
#!/bin/bash
APPDIR="$(dirname "$(dirname "$(readlink -f "$0")")")"
export PYTHONPATH="$APPDIR/usr/share/steam-authenticator:$PYTHONPATH"
cd "$APPDIR/usr/share/steam-authenticator"
exec python3 main.py "$@"
EOF
chmod +x "$APP_DIR/usr/bin/steam-authenticator"

# Create desktop file
cat > "$APP_DIR/usr/share/applications/steam-authenticator.desktop" << 'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Steam Authenticator
Comment=Steam 2FA code generator and trade confirmation manager
Exec=steam-authenticator
Icon=steam-authenticator
Terminal=false
Categories=Network;Security;Game;
EOF

# Copy desktop file to AppDir root
cp "$APP_DIR/usr/share/applications/steam-authenticator.desktop" "$APP_DIR/"

# Copy icon (use Steam icon as fallback)
if [ -f "$PROJECT_DIR/assets/icon.png" ]; then
    cp "$PROJECT_DIR/assets/icon.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/steam-authenticator.png"
    cp "$PROJECT_DIR/assets/icon.png" "$APP_DIR/steam-authenticator.png"
else
    echo "Warning: No icon.png found in assets/, using placeholder"
    # Create a simple placeholder
    convert -size 256x256 xc:navy -fill white -gravity center -pointsize 48 -annotate 0 "SA" "$APP_DIR/steam-authenticator.png" 2>/dev/null || true
fi

# Create AppRun
cat > "$APP_DIR/AppRun" << 'EOF'
#!/bin/bash
APPDIR="$(dirname "$(readlink -f "$0")")"
exec "$APPDIR/usr/bin/steam-authenticator" "$@"
EOF
chmod +x "$APP_DIR/AppRun"

# Download appimagetool if not available
if ! command -v appimagetool &> /dev/null; then
    echo "Downloading appimagetool..."
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O /tmp/appimagetool
    chmod +x /tmp/appimagetool
    APPIMAGETOOL="/tmp/appimagetool"
else
    APPIMAGETOOL="appimagetool"
fi

# Build AppImage
cd "$BUILD_DIR"
ARCH=x86_64 "$APPIMAGETOOL" SteamAuthenticator.AppDir SteamAuthenticator-x86_64.AppImage

echo ""
echo "AppImage built: $BUILD_DIR/SteamAuthenticator-x86_64.AppImage"
echo ""
echo "Note: This AppImage requires the host system to have:"
echo "  - Python 3"
echo "  - GTK4 and libadwaita"
echo "  - PyGObject"
