# Contributing to Steam Authenticator for Linux

Thank you for your interest in contributing to Steam Authenticator! This document provides guidelines for contributing to the project.

## Code of Conduct

By participating in this project, you agree to be respectful and constructive in your communications.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](https://github.com/cs2central/steam-authenticator-linux/issues)
2. If not, create a new issue with:
   - A clear, descriptive title
   - Steps to reproduce the bug
   - Expected behavior vs actual behavior
   - Your Linux distribution and version
   - Python version (`python3 --version`)
   - GTK4 version (`pkg-config --modversion gtk4`)

### Suggesting Features

1. Check if the feature has already been suggested
2. Create a new issue with the "enhancement" label
3. Describe the feature and why it would be useful

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Test your changes on at least one Linux distribution
5. Commit with clear messages: `git commit -m "Add: description of change"`
6. Push to your fork: `git push origin feature/your-feature-name`
7. Open a Pull Request

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/steam-authenticator-linux.git
cd steam-authenticator-linux
./install.sh
```

## Code Style

- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Use GTK4/libadwaita patterns for UI code

## Project Structure

```
steam-authenticator-linux/
├── src/
│   ├── main.py              # Application entry point
│   ├── ui.py                # Main window UI
│   ├── preferences.py       # Settings management
│   ├── steam_guard.py       # 2FA code generation
│   ├── steam_api.py         # Steam API communication
│   ├── mafile_manager.py    # Account file management
│   ├── login_dialog.py      # Steam login UI
│   └── confirmations_dialog.py  # Trade confirmations UI
├── packaging/               # Distribution packaging files
├── assets/                  # Icons and screenshots
└── .github/                 # GitHub templates and workflows
```

## Testing

Before submitting a PR:
1. Test the application starts without errors
2. Test your specific changes work correctly
3. Test on at least one distribution if possible

## Commit Messages

Use clear, descriptive commit messages:
- `Add: new feature description`
- `Fix: bug description`
- `Update: what was updated`
- `Remove: what was removed`
- `Refactor: what was refactored`

## Questions?

- Join our [Discord](https://discord.gg/cs2central)
- Open a [Discussion](https://github.com/cs2central/steam-authenticator-linux/discussions)

Thank you for contributing!
