# Personal Finance

A local, single-user web application for importing checking-account transactions, tracking a
monthly budget, and reconciling the current balance. Data is stored in SQLite on the host machine.

## Development

Requires Python 3.11 or later.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/flask --app run:app run --debug
```

Open `http://127.0.0.1:5000` on the host machine. To access the application from another device on
your trusted home network, run the production server:

```bash
.venv/bin/waitress-serve --listen=0.0.0.0:5000 run:app
```

Then open `http://<local-machine-ip>:5000` from the other device. The application has no
authentication and should not be exposed directly to the public internet.

## First import

Open **Admin**, choose the bank CSV, review the preview, and enter the current bank balance when
confirming the first import. The balance is treated as already including every transaction in that
initial file.

The importer finds the header row containing `Date`, `Description`, and `Amount`, regardless of
whether blank or account-information lines precede it. It ignores every other column. A typical
file looks like:

```csv

Checking account information
Date,Amount,Description,Ref. #
8/21/2026,-15.85,Example purchase,ignored
8/22/2026,4118.3,Example deposit,ignored
```

The complete file is rejected if any transaction row is malformed. Existing transactions with the
same date, description, and signed amount are shown as duplicates and discarded after confirmation.

## Tests

```bash
.venv/bin/pytest
```

The SQLite database is created at `instance/finance.db`. Downloadable database and CSV backups are
available from the Admin page. Keep database backups private because they contain the complete
financial history. To restore a backup, stop the application and replace `instance/finance.db` with
the downloaded database file before restarting it.
