import io
import re
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from personal_finance.models import (
    BalanceCheckpoint,
    BudgetItem,
    ImportBatch,
    RecurringTemplate,
    Transaction,
    TransactionSplit,
    db,
)


def test_main_pages_render(client):
    for path in ["/", "/transactions", "/budget", "/admin"]:
        response = client.get(path)
        assert response.status_code == 200


def test_transactions_show_fifty_rows_and_pagination_at_both_ends(app, client):
    with app.app_context():
        db.session.add_all(
            [
                Transaction(
                    bank_date=date.today(),
                    budget_month=date.today().replace(day=1),
                    amount=-index,
                    bank_description=f"Transaction {index}",
                )
                for index in range(1, 52)
            ]
        )
        db.session.commit()

    first_page = client.get("/transactions")
    second_page = client.get("/transactions?page=2")

    assert first_page.data.count(b'class="transaction-edit-form"') == 50
    assert first_page.data.count(b'aria-label="Transaction pages ') == 2
    assert b"Page 1 of 2" in first_page.data
    assert second_page.data.count(b'class="transaction-edit-form"') == 1


def test_initial_import_preview_and_confirmation(app, client):
    csv_data = b"\nChecking account\nDate,Amount,Description,Anything Else\n8/21/2026,-15.85,Market,x\n8/22/2026,4118.3,Payroll,y\n"
    response = client.post(
        "/admin/import/preview",
        data={"csv_file": (io.BytesIO(csv_data), "checking.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"Import preview" in response.data

    preview_dir = Path(app.instance_path, "import_previews")
    preview = max(preview_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
    token = preview.stem
    response = client.post(
        "/admin/import/confirm",
        data={"token": token, "initial_balance": "4118.30"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Imported 2 transaction" in response.data
    with app.app_context():
        assert Transaction.query.count() == 2
        assert ImportBatch.query.one().duplicate_count == 0
        assert BalanceCheckpoint.query.one().balance == Decimal("4118.30")


def test_initial_import_keeps_historical_transactions_in_their_month(app, client):
    csv_data = b"Date,Amount,Description\n3/21/2025,-10,Older one\n3/22/2025,-20,Older two\n"
    response = client.post(
        "/admin/import/preview",
        data={"csv_file": (io.BytesIO(csv_data), "history.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    preview = max(
        Path(app.instance_path, "import_previews").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
    )

    response = client.post(
        "/admin/import/confirm",
        data={"token": preview.stem, "initial_balance": "100"},
    )

    assert response.status_code == 302
    with app.app_context():
        assert {transaction.budget_month for transaction in Transaction.query.all()} == {
            date(2025, 3, 1)
        }


def test_duplicate_import_is_discarded(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date(2026, 8, 21),
            budget_month=date(2026, 8, 1),
            amount=-15.85,
            bank_description="Market",
        )
        db.session.add(transaction)
        db.session.commit()
    csv_data = b"\nChecking\nDate,Amount,Description\n8/21/2026,-15.85,Market\n"
    response = client.post(
        "/admin/import/preview",
        data={"csv_file": (io.BytesIO(csv_data), "checking.csv")},
        content_type="multipart/form-data",
    )
    assert b"Duplicate" in response.data


def test_transaction_delete_is_soft_delete(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(), budget_month=date.today().replace(day=1), amount=-10, bank_description="Test"
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    response = client.post(f"/transactions/{transaction_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Transaction, transaction_id).deleted_at is not None


def test_transaction_amount_can_be_corrected(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=date.today().replace(day=1),
            amount=25,
            bank_description="Mistyped expense",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    response = client.post(
        f"/transactions/{transaction_id}/edit",
        data={"amount": "-25.00", "custom_description": "Mistyped expense"},
    )

    assert response.status_code == 302
    assert response.location.endswith(f"#transaction-{transaction_id}")
    with app.app_context():
        assert db.session.get(Transaction, transaction_id).amount == Decimal("-25.00")


def test_transaction_matches_include_same_bank_description_with_different_amounts(app, client):
    with app.app_context():
        selected = Transaction(
            bank_date=date(2026, 8, 15),
            budget_month=date(2026, 8, 1),
            amount=2000,
            bank_description="CONCUR TECHNOLOGPAYMENTS",
        )
        db.session.add_all(
            [
                selected,
                Transaction(
                    bank_date=date(2026, 7, 31),
                    budget_month=date(2026, 7, 1),
                    amount=1900,
                    bank_description="CONCUR TECHNOLOGPAYMENTS",
                ),
                Transaction(
                    bank_date=date(2026, 7, 15),
                    budget_month=date(2026, 7, 1),
                    amount=2050,
                    bank_description="CONCUR TECHNOLOGPAYMENTS",
                ),
                Transaction(
                    bank_date=date(2026, 7, 15),
                    budget_month=date(2026, 7, 1),
                    amount=2000,
                    bank_description="Different deposit",
                ),
            ]
        )
        db.session.commit()
        transaction_id = selected.id

    response = client.get(f"/transactions/{transaction_id}/matches")

    assert response.status_code == 200
    assert [match["amount"] for match in response.json["matches"]] == ["$1,900.00", "$2,050.00"]


def test_recurring_transaction_edits_update_open_budget_item(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=date.today().replace(day=1),
            amount=-25,
            bank_description="Original bank description",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    response = client.post(
        f"/transactions/{transaction_id}/recurring",
        data={"enabled": "true", "interval": "1"},
    )
    assert response.status_code == 200

    response = client.post(
        f"/transactions/{transaction_id}/edit",
        data={"amount": "-25.00", "custom_description": "Updated description"},
    )

    assert response.status_code == 302
    with app.app_context():
        template = RecurringTemplate.query.filter_by(
            created_from_transaction_id=transaction_id
        ).one()
        item = BudgetItem.query.filter_by(recurring_template_id=template.id).one()
        assert template.description == "Updated description"
        assert item.description == "Updated description"


def test_recurring_split_creates_budget_and_can_be_matched(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=date.today().replace(day=1),
            amount=-100,
            bank_description="Combined purchase",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    response = client.post(
        f"/transactions/{transaction_id}/splits",
        json={
            "splits": [
                {
                    "description": "Recurring portion",
                    "amount": "-40.00",
                    "transaction_type": "Bills",
                    "parent_category": "Subscriptions",
                    "subcategory": "Software",
                    "is_recurring": True,
                    "interval_months": 3,
                },
                {"description": "Other portion", "amount": "-60.00"},
            ]
        },
    )
    assert response.status_code == 200
    with app.app_context():
        split = TransactionSplit.query.filter_by(description="Recurring portion").one()
        template = RecurringTemplate.query.filter_by(created_from_split_id=split.id).one()
        item = BudgetItem.query.filter_by(recurring_template_id=template.id).one()
        assert template.interval_months == 3
        split_id = split.id
        item_id = item.id

    response = client.post(
        f"/budget/{item_id}/paid",
        data={"paid": "true", "transaction_match": f"split:{split_id}"},
    )
    assert response.status_code == 200
    with app.app_context():
        item = db.session.get(BudgetItem, item_id)
        assert item.paid
        assert item.actual_amount == Decimal("-40.00")


def test_writes_require_csrf_token(app, client):
    app.config["WTF_CSRF_ENABLED"] = True

    response = client.post(
        "/transactions/add",
        data={"date": date.today().isoformat(), "description": "Blocked", "amount": "-1"},
    )
    assert response.status_code == 400

    page = client.get("/transactions")
    token = re.search(rb'<meta name="csrf-token" content="([^"]+)"', page.data).group(1)
    response = client.post(
        "/transactions/add",
        data={
            "csrf_token": token.decode(),
            "date": date.today().isoformat(),
            "description": "Allowed",
            "amount": "-1",
        },
    )
    assert response.status_code == 302


def test_database_backup_is_valid_sqlite(client):
    response = client.get("/admin/backup")

    assert response.status_code == 200
    connection = sqlite3.connect(":memory:")
    connection.deserialize(response.data)
    tables = {
        row[0]
        for row in connection.execute("select name from sqlite_master where type = 'table'")
    }
    assert {"transaction", "budget_item", "balance_checkpoint"}.issubset(tables)
