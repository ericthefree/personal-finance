#!/usr/bin/env bash
set -euo pipefail

label="com.personal-finance.web"
service_target="gui/$(id -u)/$label"
plist_path="$HOME/Library/LaunchAgents/$label.plist"
app_path="$HOME/Applications/Personal Finance.app"

if [[ "$(uname -s)" != "Darwin" ]]; then
    printf '%s\n' "This uninstaller must be run on macOS." >&2
    exit 1
fi

launchctl bootout "$service_target" >/dev/null 2>&1 || true
rm -f "$plist_path"
rm -rf "$app_path"

printf '%s\n' "Personal Finance startup and app launcher were removed."
printf '%s\n' "Your database, source files, virtual environment, and logs were preserved."
