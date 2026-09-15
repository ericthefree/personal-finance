import plistlib
from pathlib import Path


ROOT = Path(__file__).parents[1]
MACOS_SCRIPTS = ROOT / "scripts" / "macos"


def test_launcher_metadata_references_packaged_icon_and_working_executable():
    with (MACOS_SCRIPTS / "app-info.plist").open("rb") as plist_file:
        metadata = plistlib.load(plist_file)

    assert metadata["CFBundleDisplayName"] == "Personal Finance"
    assert metadata["CFBundleExecutable"] == "Personal Finance"
    assert metadata["CFBundleIconFile"] == "PersonalFinance.icns"
    assert metadata["CFBundleIdentifier"] == "com.personal-finance.launcher"
    assert metadata["LSMinimumSystemVersion"] == "11.0"
    assert metadata["CFBundleSupportedPlatforms"] == ["MacOSX"]

    icon = MACOS_SCRIPTS / "resources" / metadata["CFBundleIconFile"]
    assert icon.read_bytes().startswith(b"icns")


def test_installer_copies_complete_launcher_bundle_resources():
    installer = (MACOS_SCRIPTS / "install.sh").read_text(encoding="utf-8")

    assert 'cp "$app_plist_source" "$app_path/Contents/Info.plist"' in installer
    assert 'cp "$app_icon_source" "$app_path/Contents/Resources/PersonalFinance.icns"' in installer
    assert "printf 'APPL????' > \"$app_path/Contents/PkgInfo\"" in installer
    assert 'cat > "$app_path/Contents/MacOS/Personal Finance"' in installer
