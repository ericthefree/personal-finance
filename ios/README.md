<!--
File: ios/README.md
Summary: Setup, signing, installation, and maintenance instructions for the iPhone companion app.
Modified by: Eric Freeman
Last modified: 2026-09-15
-->

# Personal Finance for iPhone

The iPhone app is a native SwiftUI container for the Personal Finance web application. It remembers
the Mac's private Tailscale URL, displays the application in an in-app `WKWebView`, and offers native
settings and retry controls. Web application updates appear without rebuilding the iPhone app.

## Prerequisites

1. Install Tailscale on the Mac and iPhone.
2. Sign into the same Tailscale account on both devices.
3. Run the macOS installer and copy the URL it prints, such as `http://100.100.100.100:5050`.
4. If Bitdefender VPN interferes with Tailscale, disconnect Bitdefender while using Personal Finance.

## Install with a free Apple developer account

1. Connect the iPhone to the Mac and open `PersonalFinance.xcodeproj` in Xcode.
2. Select the **PersonalFinance** project, then the **PersonalFinance** target.
3. Under **Signing & Capabilities**, select Eric Freeman's Personal Team. If Xcode reports that the
   bundle identifier is unavailable, replace `com.ericfreeman.personalfinance` with a unique value.
4. Select the connected iPhone as the run destination and press **Run**.
5. Follow any iPhone prompts to enable Developer Mode or trust the developer profile.
6. On first launch, enter the Tailscale URL printed by the macOS installer.

Free provisioning profiles generally expire after seven days. Reconnect the iPhone and press
**Run** in Xcode again to refresh the installation. A paid Apple Developer membership allows normal
long-lived distribution later without changing the application architecture.

## Generated and comment-free files

The Xcode asset-catalog `Contents.json` files are strict JSON and cannot contain documentation
comments. `project.pbxproj` is Xcode-managed metadata; its first line is an Xcode-required marker,
followed by its documentation header. The shared scheme is committed so the app can be opened,
built, and run immediately.
