"""
File: test_ios_app.py
Summary: Verifies the native iPhone project, private networking configuration, and icon catalog.
Modified by: Eric Freeman
Last modified: 2026-09-15
"""

import json
import plistlib
import struct
from pathlib import Path


ROOT = Path(__file__).parents[1]
IOS_ROOT = ROOT / "ios"
APP_ROOT = IOS_ROOT / "PersonalFinance"


def test_xcode_project_includes_native_sources_and_resources():
    """Verify that the Xcode project references every required Swift source and asset resource."""
    project = (IOS_ROOT / "PersonalFinance.xcodeproj" / "project.pbxproj").read_text(
        encoding="utf-8"
    )

    assert "PersonalFinanceApp.swift in Sources" in project
    assert "ContentView.swift in Sources" in project
    assert "FinanceWebView.swift in Sources" in project
    assert "Assets.xcassets in Resources" in project
    assert "TARGETED_DEVICE_FAMILY = 1" in project
    assert "CODE_SIGN_STYLE = Automatic" in project


def test_web_view_uses_saved_address_and_permits_tailscale_http_content():
    """Verify URL persistence and the WebKit-only HTTP exception needed inside encrypted Tailscale."""
    content = (APP_ROOT / "ContentView.swift").read_text(encoding="utf-8")
    browser = (APP_ROOT / "FinanceWebView.swift").read_text(encoding="utf-8")
    with (APP_ROOT / "Info.plist").open("rb") as plist_file:
        metadata = plistlib.load(plist_file)

    assert '@AppStorage("serverAddress")' in content
    assert "WKWebView" in browser
    assert "context.coordinator.serverURL != url" in browser
    assert "webView.url != url" not in browser
    assert metadata["CFBundleIdentifier"] == "$(PRODUCT_BUNDLE_IDENTIFIER)"
    assert metadata["CFBundleVersion"] == "$(CURRENT_PROJECT_VERSION)"
    assert metadata["NSAppTransportSecurity"]["NSAllowsArbitraryLoadsInWebContent"] is True
    assert "NSAllowsArbitraryLoads" not in metadata["NSAppTransportSecurity"]


def test_app_icon_catalog_contains_every_declared_rgb_image():
    """Verify all declared iPhone icon files exist, have PNG headers, and contain no alpha channel."""
    icon_root = APP_ROOT / "Assets.xcassets" / "AppIcon.appiconset"
    catalog = json.loads((icon_root / "Contents.json").read_text(encoding="utf-8"))

    expected_sizes = {
        image["filename"]: round(float(image["size"].split("x")[0]) * int(image["scale"][0]))
        for image in catalog["images"]
    }
    assert expected_sizes["AppIcon-1024.png"] == 1024
    assert len(expected_sizes) == 9
    for filename, expected_size in expected_sizes.items():
        image = (icon_root / filename).read_bytes()
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", image[16:24])
        assert (width, height) == (expected_size, expected_size)
        assert image[25] == 2
