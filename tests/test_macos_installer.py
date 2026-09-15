"""
File: test_macos_installer.py
Summary: Verifies macOS launcher metadata, resources, service networking, and conflict handling.
Modified by: Eric Freeman
Last modified: 2026-09-15
"""

import plistlib
import struct
from pathlib import Path


ROOT = Path(__file__).parents[1]
MACOS_SCRIPTS = ROOT / "scripts" / "macos"


def test_launcher_metadata_references_packaged_icon_and_working_executable():
    """Verify launcher identity, compatibility metadata, executable, and packaged ICNS resource."""
    with (MACOS_SCRIPTS / "app-info.plist").open("rb") as plist_file:
        metadata = plistlib.load(plist_file)

    assert metadata["CFBundleDisplayName"] == "Personal Finance"
    assert metadata["CFBundleExecutable"] == "Personal Finance"
    assert metadata["CFBundleIconFile"] == "PersonalFinance.icns"
    assert metadata["CFBundleIdentifier"] == "com.personal-finance.launcher"
    assert metadata["LSMinimumSystemVersion"] == "11.0"
    assert metadata["CFBundleSupportedPlatforms"] == ["MacOSX"]
    assert metadata["CFBundleShortVersionString"] == "1.1"
    assert metadata["CFBundleVersion"] == "2"

    icon = MACOS_SCRIPTS / "resources" / metadata["CFBundleIconFile"]
    icon_data = icon.read_bytes()
    assert icon_data.startswith(b"icns")
    assert struct.unpack(">I", icon_data[4:8])[0] == len(icon_data)
    assert b"ic10" in icon_data


def test_installer_copies_complete_launcher_bundle_resources():
    """Verify the installer copies every file required by the macOS application bundle."""
    installer = (MACOS_SCRIPTS / "install.sh").read_text(encoding="utf-8")

    assert 'cp "$app_plist_source" "$app_path/Contents/Info.plist"' in installer
    assert 'cp "$app_icon_source" "$app_path/Contents/Resources/PersonalFinance.icns"' in installer
    assert "printf 'APPL????' > \"$app_path/Contents/PkgInfo\"" in installer
    assert 'cat > "$app_path/Contents/MacOS/Personal Finance"' in installer


def test_installed_service_listens_only_locally_and_on_tailscale():
    """Verify the installed service excludes LAN interfaces and binds only local and Tailscale IPs."""
    installer = (MACOS_SCRIPTS / "install.sh").read_text(encoding="utf-8")

    assert '"--listen=127.0.0.1:5050"' in installer
    assert 'f"--listen={os.environ[\'TAILSCALE_IP\']}:5050"' in installer
    assert '"--listen=0.0.0.0:5050"' not in installer
    assert "http://$tailscale_ip:5050" in installer


def test_installer_requires_a_connected_tailscale_client():
    """Verify installation stops with actionable guidance unless Tailscale is available and online."""
    installer = (MACOS_SCRIPTS / "install.sh").read_text(encoding="utf-8")

    assert 'command -v tailscale' in installer
    assert '"$tailscale_bin" ip -4' in installer
    assert "Install Tailscale on this Mac" in installer
    assert "Tailscale is not connected" in installer


def test_installer_stops_existing_service_and_reports_other_port_owner():
    """Verify installation stops its service before launch and diagnoses unrelated port listeners."""
    installer = (MACOS_SCRIPTS / "install.sh").read_text(encoding="utf-8")

    bootout = 'launchctl bootout "$service_target"'
    bootstrap = 'launchctl bootstrap "gui/$(id -u)" "$plist_path"'
    assert installer.count(bootout) == 1
    assert installer.index(bootout) < installer.index(bootstrap)
    assert 'lsof -nP -iTCP:5050 -sTCP:LISTEN' in installer
    assert "Port 5050 is still in use by another process" in installer
