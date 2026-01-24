#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║         Steam Authenticator for Linux - Installer         ║"
echo "║                    by CS2Central.gg                       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detect distribution
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
        DISTRO_LIKE=$ID_LIKE
    elif [ -f /etc/lsb-release ]; then
        . /etc/lsb-release
        DISTRO=$DISTRIB_ID
    else
        DISTRO="unknown"
    fi
    echo "$DISTRO"
}

# Install system dependencies based on distro
install_system_deps() {
    local distro=$(detect_distro)
    echo -e "${YELLOW}Detected distribution: ${distro}${NC}"

    case "$distro" in
        debian|ubuntu|linuxmint|pop|elementary|zorin)
            echo -e "${GREEN}Installing dependencies for Debian/Ubuntu-based system...${NC}"
            sudo apt update
            sudo apt install -y gir1.2-gtk-4.0 gir1.2-adw-1 libgtk-4-1 libadwaita-1-0 \
                python3-gi python3-gi-cairo python3-pip python3-venv
            ;;
        arch|manjaro|cachyos|endeavouros|garuda)
            echo -e "${GREEN}Installing dependencies for Arch-based system...${NC}"
            sudo pacman -S --noconfirm --needed gtk4 libadwaita python python-gobject python-pip
            ;;
        fedora|rhel|centos|rocky|alma)
            echo -e "${GREEN}Installing dependencies for Fedora/RHEL-based system...${NC}"
            sudo dnf install -y gtk4 libadwaita python3 python3-gobject python3-pip
            ;;
        opensuse*|suse)
            echo -e "${GREEN}Installing dependencies for openSUSE...${NC}"
            sudo zypper install -y gtk4 libadwaita-devel python3 python3-gobject python3-pip
            ;;
        gentoo)
            echo -e "${GREEN}Installing dependencies for Gentoo...${NC}"
            sudo emerge --ask gui-libs/gtk gui-libs/libadwaita dev-python/pygobject
            ;;
        void)
            echo -e "${GREEN}Installing dependencies for Void Linux...${NC}"
            sudo xbps-install -y gtk4 libadwaita python3 python3-gobject python3-pip
            ;;
        nixos)
            echo -e "${YELLOW}NixOS detected. Please add the following to your configuration:${NC}"
            echo "  environment.systemPackages = with pkgs; [ gtk4 libadwaita python3 python3Packages.pygobject3 ];"
            return 0
            ;;
        *)
            # Try to detect based on ID_LIKE
            case "$DISTRO_LIKE" in
                *debian*|*ubuntu*)
                    echo -e "${GREEN}Installing dependencies for Debian-like system...${NC}"
                    sudo apt update
                    sudo apt install -y gir1.2-gtk-4.0 gir1.2-adw-1 libgtk-4-1 libadwaita-1-0 \
                        python3-gi python3-gi-cairo python3-pip python3-venv
                    ;;
                *arch*)
                    echo -e "${GREEN}Installing dependencies for Arch-like system...${NC}"
                    sudo pacman -S --noconfirm --needed gtk4 libadwaita python python-gobject python-pip
                    ;;
                *fedora*|*rhel*)
                    echo -e "${GREEN}Installing dependencies for Fedora-like system...${NC}"
                    sudo dnf install -y gtk4 libadwaita python3 python3-gobject python3-pip
                    ;;
                *)
                    echo -e "${RED}Unknown distribution: $distro${NC}"
                    echo "Please install the following packages manually:"
                    echo "  - GTK4"
                    echo "  - libadwaita"
                    echo "  - Python 3"
                    echo "  - PyGObject"
                    echo "  - python-pip"
                    return 1
                    ;;
            esac
            ;;
    esac
}

# Create virtual environment and install Python dependencies
install_python_deps() {
    echo -e "${GREEN}Setting up Python virtual environment...${NC}"

    if [ -d "venv" ]; then
        echo -e "${YELLOW}Existing virtual environment found. Removing...${NC}"
        rm -rf venv
    fi

    python3 -m venv --system-site-packages venv

    echo -e "${GREEN}Installing Python dependencies...${NC}"
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install aiohttp cryptography "qrcode[pil]" Pillow requests argon2-cffi
}

# Create desktop entry
create_desktop_entry() {
    echo -e "${GREEN}Creating desktop entry...${NC}"

    local desktop_file="$HOME/.local/share/applications/steam-authenticator.desktop"
    mkdir -p "$HOME/.local/share/applications"

    cat > "$desktop_file" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Steam Authenticator
Comment=A modern Steam Authenticator for Linux with 2FA code generation and trade confirmation support
Exec="$SCRIPT_DIR/run.sh"
Icon=steam
Path=$SCRIPT_DIR
Terminal=false
Categories=Network;Security;Game;
StartupNotify=true
StartupWMClass=com.github.steamauthenticator
Keywords=Steam;2FA;Authenticator;Gaming;Trade;
EOF

    chmod +x "$desktop_file"

    # Update desktop database
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
}

# Create data directories
create_data_dirs() {
    echo -e "${GREEN}Creating data directories...${NC}"
    mkdir -p "$HOME/.config/steam-authenticator"
    mkdir -p "$HOME/.local/share/steam-authenticator"
    mkdir -p "$SCRIPT_DIR/src/maFiles"
}

# Main installation
main() {
    echo -e "${BLUE}Step 1/4: Installing system dependencies...${NC}"
    install_system_deps

    echo ""
    echo -e "${BLUE}Step 2/4: Installing Python dependencies...${NC}"
    install_python_deps

    echo ""
    echo -e "${BLUE}Step 3/4: Creating desktop entry...${NC}"
    create_desktop_entry

    echo ""
    echo -e "${BLUE}Step 4/4: Creating data directories...${NC}"
    create_data_dirs

    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║            Installation completed successfully!           ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "You can now run Steam Authenticator by:"
    echo -e "  ${YELLOW}1.${NC} Running ${BLUE}./run.sh${NC} from this directory"
    echo -e "  ${YELLOW}2.${NC} Searching for 'Steam Authenticator' in your application menu"
    echo ""
    echo -e "Join our community:"
    echo -e "  ${BLUE}Discord:${NC} https://discord.gg/cs2central"
    echo -e "  ${BLUE}Website:${NC} https://cs2central.gg/"
    echo ""

    # Ask to run the application
    read -p "Would you like to run Steam Authenticator now? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        ./run.sh
    fi
}

# Run main function
main "$@"
