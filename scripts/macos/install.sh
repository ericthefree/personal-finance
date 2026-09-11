#!/usr/bin/env bash
set -euo pipefail

label="com.personal-finance.web"
service_target="gui/$(id -u)/$label"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
launch_agents_dir="$HOME/Library/LaunchAgents"
plist_path="$launch_agents_dir/$label.plist"
app_path="$HOME/Applications/Personal Finance.app"
log_dir="$HOME/Library/Logs/Personal Finance"

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

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
    python3 -m venv "$repo_root/.venv"
fi
"$repo_root/.venv/bin/python" -m pip install --quiet --disable-pip-version-check \
    -r "$repo_root/requirements.txt"

mkdir -p "$launch_agents_dir" "$log_dir" "$app_path/Contents/MacOS"

PLIST_PATH="$plist_path" REPO_ROOT="$repo_root" LOG_DIR="$log_dir" python3 <<'PY'
import os
import plistlib

configuration = {
    "Label": "com.personal-finance.web",
    "ProgramArguments": [
        os.path.join(os.environ["REPO_ROOT"], ".venv/bin/waitress-serve"),
        "--listen=127.0.0.1:5000",
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

APP_PLIST="$app_path/Contents/Info.plist" python3 <<'PY'
import os
import plistlib

configuration = {
    "CFBundleDevelopmentRegion": "en",
    "CFBundleDisplayName": "Personal Finance",
    "CFBundleExecutable": "Personal Finance",
    "CFBundleIdentifier": "com.personal-finance.launcher",
    "CFBundleInfoDictionaryVersion": "6.0",
    "CFBundleName": "Personal Finance",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "1.0",
    "LSMinimumSystemVersion": "11.0",
}

with open(os.environ["APP_PLIST"], "wb") as plist:
    plistlib.dump(configuration, plist)
PY

cat > "$app_path/Contents/MacOS/Personal Finance" <<'SH'
#!/bin/zsh

service="gui/$(id -u)/com.personal-finance.web"
launchctl kickstart "$service" >/dev/null 2>&1 || true

for attempt in {1..30}; do
    if curl --silent --fail --max-time 1 http://127.0.0.1:5000/ >/dev/null; then
        open http://127.0.0.1:5000/
        exit 0
    fi
    sleep 1
done

open "$HOME/Library/Logs/Personal Finance/service-error.log"
exit 1
SH
chmod 755 "$app_path/Contents/MacOS/Personal Finance"

launchctl bootout "$service_target" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$plist_path"
launchctl enable "$service_target"
launchctl kickstart "$service_target"

for attempt in {1..30}; do
    if curl --silent --fail --max-time 1 http://127.0.0.1:5000/ >/dev/null; then
        printf '\n%s\n' "Personal Finance is installed and running."
        printf '%s\n' "Open it from $app_path or visit http://127.0.0.1:5000."
        open "$app_path"
        exit 0
    fi
    sleep 1
done

printf '%s\n' "The service did not become ready. Check $log_dir/service-error.log" >&2
exit 1
