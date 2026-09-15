#!/usr/bin/env bash
set -euo pipefail

label="com.personal-finance.web"
service_target="gui/$(id -u)/$label"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
launch_agents_dir="$HOME/Library/LaunchAgents"
plist_path="$launch_agents_dir/$label.plist"
app_path="$HOME/Applications/Personal Finance.app"
log_dir="$HOME/Library/Logs/Personal Finance"
app_plist_source="$repo_root/scripts/macos/app-info.plist"
app_icon_source="$repo_root/scripts/macos/resources/PersonalFinance.icns"

if [[ "$(uname -s)" != "Darwin" ]]; then
    printf '%s\n' "This installer must be run on macOS." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "Python 3.11 or later is required." >&2
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    printf '%s\n' "Python 3.11 or later is required." >&2
    exit 1
fi

printf '%s\n' "Installing Personal Finance from $repo_root"

launchctl bootout "$service_target" >/dev/null 2>&1 || true
for attempt in {1..20}; do
    if ! lsof -nP -iTCP:5050 -sTCP:LISTEN >/dev/null 2>&1; then
        break
    fi
    sleep 0.25
done
if lsof -nP -iTCP:5050 -sTCP:LISTEN >/dev/null 2>&1; then
    printf '%s\n' "Port 5050 is still in use by another process:" >&2
    lsof -nP -iTCP:5050 -sTCP:LISTEN >&2
    printf '%s\n' "Stop that process, then rerun this installer." >&2
    exit 1
fi

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
    python3 -m venv "$repo_root/.venv"
fi
"$repo_root/.venv/bin/python" -m pip install --quiet --disable-pip-version-check \
    -r "$repo_root/requirements.txt"

rm -rf "$app_path"
mkdir -p "$launch_agents_dir" "$log_dir" "$app_path/Contents/MacOS" "$app_path/Contents/Resources"

PLIST_PATH="$plist_path" REPO_ROOT="$repo_root" LOG_DIR="$log_dir" python3 <<'PY'
import os
import plistlib

configuration = {
    "Label": "com.personal-finance.web",
    "ProgramArguments": [
        os.path.join(os.environ["REPO_ROOT"], ".venv/bin/waitress-serve"),
        "--listen=0.0.0.0:5050",
        "run:app",
    ],
    "WorkingDirectory": os.environ["REPO_ROOT"],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "ThrottleInterval": 10,
    "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    "StandardOutPath": os.path.join(os.environ["LOG_DIR"], "service.log"),
    "StandardErrorPath": os.path.join(os.environ["LOG_DIR"], "service-error.log"),
}

with open(os.environ["PLIST_PATH"], "wb") as plist:
    plistlib.dump(configuration, plist)
PY

cp "$app_plist_source" "$app_path/Contents/Info.plist"
cp "$app_icon_source" "$app_path/Contents/Resources/PersonalFinance.icns"
printf 'APPL????' > "$app_path/Contents/PkgInfo"

cat > "$app_path/Contents/MacOS/Personal Finance" <<'SH'
#!/bin/zsh

service="gui/$(id -u)/com.personal-finance.web"
launchctl kickstart "$service" >/dev/null 2>&1 || true

for attempt in {1..30}; do
    if curl --silent --fail --max-time 1 http://127.0.0.1:5050/ >/dev/null; then
        open http://127.0.0.1:5050/
        exit 0
    fi
    sleep 1
done

open "$HOME/Library/Logs/Personal Finance/service-error.log"
exit 1
SH
chmod 755 "$app_path/Contents/MacOS/Personal Finance"

launchctl bootstrap "gui/$(id -u)" "$plist_path"
launchctl enable "$service_target"
launchctl kickstart "$service_target"

for attempt in {1..30}; do
    if curl --silent --fail --max-time 1 http://127.0.0.1:5050/ >/dev/null; then
        printf '\n%s\n' "Personal Finance is installed and running."
        printf '%s\n' "Open it from $app_path or visit http://127.0.0.1:5050."
        local_hostname="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
        if [[ -n "$local_hostname" ]]; then
            printf '%s\n' "On your trusted Wi-Fi, open http://$local_hostname.local:5050 from your phone."
        fi
        open "$app_path"
        exit 0
    fi
    sleep 1
done

printf '%s\n' "The service did not become ready. Check $log_dir/service-error.log" >&2
exit 1
