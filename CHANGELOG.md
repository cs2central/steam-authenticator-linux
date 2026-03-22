# Changelog

## v1.1.0 (2026-03-22)

### New Features
- 5 new themes: Neon, Sakura, Hacker, Bubblegum, Minimal (13 total)
- Search accounts by display name in account selector
- Login dialog prefills username and focuses password field
- Confirmation dialog for individual trade accept/deny
- Data loss warning when removing accounts

### Account Setup Fixes
- Fixed account setup flow: properly handles email Steam Guard, no Steam Guard, and existing authenticator detection
- Correct protobuf field types (fixed64 for steamid) matching Steam's proto definitions
- Fixed AddAuthenticator, FinalizeAddAuthenticator, and QueryStatus request encoding
- Fixed response parsers to match official proto field numbers
- Rate limit detection with user-friendly error messages

### Security
- Steam Guard 2FA codes no longer logged to disk
- File permissions (0600) on maFiles and manifest
- Atomic writes for manifest (write-to-temp-then-rename)
- Path traversal fix for steamid filenames
- Log rotation (5MB max, 3 backups)

### Reliability
- Fixed missing steam_login module (SteamProtobufLogin)
- Error handling on Steam Guard code generation
- Error handling on manifest save
- Recursion guard on confirmation retry loops
- 30s HTTP timeouts on all API requests
- None checks before access_token operations

### UI/UX
- Disabled QR Code button (not implemented) with "Coming soon" tooltip
- Fixed title letter-spacing (no longer applies monospace to all titles)
- Removed emoji from log messages
- Replaced subprocess xdg-open with webbrowser module
- Removed text-shadow glow effects from Steam Guard code display

### Steam API
- Fixed multi-confirmation auth (cookies instead of Bearer header)
- Fixed protobuf parser for multi-byte varint tags
- Correct Steam Guard code_type (email vs device) when submitting
- Removed dead refresh_session endpoint

### Dependencies
- Removed unused argon2-cffi and requests
- Removed 11 unused imports
- install.sh now uses requirements.txt instead of hardcoded packages
- Fixed pacman and emerge flags in install.sh
- Removed PNG screenshots (WebP only)

## v1.0.0 (2026-03-21)

Initial release.
