# Personal Finance

A local, single-user web application for importing checking-account transactions, tracking a
monthly budget, and reconciling the current balance. Data is stored in SQLite on the host machine.

## Development

Requires Python 3.11 or later.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/flask --app run:app run --debug --port 5050
```

Open `http://127.0.0.1:5050` on the host machine. For remote access, install and connect Tailscale,
then bind the production server only to localhost and the computer's Tailscale address:

```bash
tailscale_ip="$(tailscale ip -4)"
.venv/bin/waitress-serve --listen=127.0.0.1:5050 --listen="$tailscale_ip:5050" run:app
```

Then open `http://<tailscale-ip>:5050` from another device signed into the same Tailscale network.
The application has no authentication and should not be exposed directly to the public internet.

## Install as a macOS application

On the Mac that will store the finance data, run:

```bash
./scripts/macos/install.sh
```

The installer requires the Tailscale app to be installed, signed in, and connected on the Mac.
Install Tailscale on the phone and sign into the same Tailscale account as well. Bitdefender VPN and
Tailscale may conflict when active at the same time; disconnect Bitdefender while using Tailscale if
the phone or Mac cannot connect.

The installer creates **Personal Finance.app** in the current user's `Applications` folder and a
macOS `launchd` service. The service starts automatically when that user logs in, keeps running
while the screen is locked, and restarts if it exits unexpectedly. After restarting the Mac, it
will be available again as soon as the user logs in. Opening the application starts the service if
necessary and opens `http://127.0.0.1:5050` in the default browser. Rerunning the installer replaces
the launcher bundle so its metadata and application icon stay current without changing the database.

The installed service accepts connections only from the Mac itself and the Mac's private Tailscale
address. The installer prints the Tailscale URL. On iPhone, open that URL in Safari and choose
**Share → Add to Home Screen**. On Android, open it in Chrome and choose **Add to Home screen**. The
Mac must be awake with Tailscale connected. Do not port-forward the service or otherwise expose it
directly to the internet.

If installation reports that port 5050 is already in use, inspect the listener before stopping it:

```bash
lsof -nP -iTCP:5050 -sTCP:LISTEN
```

The installer stops its own existing launchd service and waits for that listener to exit. If a
different process still owns the port, it prints the process details and exits without starting a
restart loop.

The application remains tied to this project folder because the database is stored here. If this
folder is moved, rerun the installer from its new location. Logs are written to
`~/Library/Logs/Personal Finance/`.

To stop automatic startup and remove the application launcher:

```bash
./scripts/macos/uninstall.sh
```

Uninstalling preserves the database and project files.

## First import

Open **Admin**, choose the bank CSV, review the preview, and enter the current bank balance when
confirming the first import. The balance is treated as already including every transaction in that
initial file.

The importer finds the header row containing `Date`, `Description`, and `Amount`, regardless of
whether blank or account-information lines precede it. Dates may use two- or four-digit years. It
ignores every other column. A typical file looks like:

```csv

Checking account information
Date,Amount,Description,Ref. #
8/21/2026,-15.85,Example purchase,ignored
8/22/2026,4118.3,Example deposit,ignored
```

The complete file is rejected if any transaction row is malformed. Existing transactions with the
same date, description, and signed amount are shown as duplicates and discarded after confirmation.

## Reconcile transactions

The **Reconcile bank CSV** tool on the Admin page compares a recent bank file with active database
transactions. Dates and signed amounts must match exactly; descriptions ignore capitalization and
extra whitespace. Each CSV and database transaction can be matched only once. Exact duplicate rows
already identified by the CSV parser are ignored using the same rule as the normal importer.

Same-date, same-amount rows with different descriptions are shown for manual matching. The final
report separates pending database transactions, CSV transactions that were not imported, and
possible duplicate or extra database transactions. Selected CSV rows can be imported and selected
extras can be soft-deleted; pending rows are informational only.

## Budget calendar

The **Calendar** tab shows budget items on their planned due dates for the current month, prior
budget months, or the next month. Item labels are shortened to fit each day; hover or keyboard-focus
an item to see its full description, amount, category, and payment status.

## Tests

```bash
.venv/bin/pytest
```

The SQLite database is created at `instance/finance.db`. Downloadable database and CSV backups are
available from the Admin page. Keep database backups private because they contain the complete
financial history. To restore a backup, stop the application and replace `instance/finance.db` with
the downloaded database file before restarting it.
