import csv
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
    MonthRecord,
    RecurringTemplate,
    Transaction,
    TransactionSplit,
    db,
)


def test_main_pages_render(client):
    for path in ["/", "/cash-flow", "/transactions", "/budget", "/calendar", "/admin"]:
        response = client.get(path)
        assert response.status_code == 200

    transactions_page = client.get("/transactions").data
    assert b'id="match-amount-range"' in transactions_page
    assert b'id="select-all-matches"' in transactions_page
    assert b'id="deselect-all-matches"' in transactions_page


def test_calendar_groups_budget_items_and_offers_past_current_and_next_months(app, client):
    current_month = date.today().replace(day=1)
    previous_month = (
        date(current_month.year - 1, 12, 1)
        if current_month.month == 1
        else date(current_month.year, current_month.month - 1, 1)
    )
    next_month = (
        date(current_month.year + 1, 1, 1)
        if current_month.month == 12
        else date(current_month.year, current_month.month + 1, 1)
    )
    later_month = (
        date(next_month.year + 1, 1, 1)
        if next_month.month == 12
        else date(next_month.year, next_month.month + 1, 1)
    )
    with app.app_context():
        db.session.add_all(
            [
                MonthRecord(month=previous_month, closed=True),
                MonthRecord(month=later_month),
                BudgetItem(
                    month=current_month,
                    due_date=current_month.replace(day=10),
                    description="Neighborhood electricity utility with a long name",
                    amount=-125,
                    transaction_type="Bills",
                    parent_category="Utilities",
                    subcategory="Electricity",
                ),
                BudgetItem(
                    month=current_month,
                    due_date=current_month.replace(day=10),
                    description="Internet",
                    amount=-75,
                    paid=True,
                    actual_amount=-74,
                ),
            ]
        )
        db.session.commit()

    response = client.get("/calendar")
    page = response.data.decode()

    assert response.status_code == 200
    assert f"{current_month:%B %Y} calendar" in page
    assert f'<option value="{previous_month:%Y-%m}"' in page
    assert f'<option value="{current_month:%Y-%m}" selected>' in page
    assert f'<option value="{next_month:%Y-%m}"' in page
    assert f'<option value="{later_month:%Y-%m}"' not in page
    day_cell = re.search(
        rf'<article class="[^"]*" data-calendar-date="{current_month.replace(day=10).isoformat()}">(.*?)</article>',
        page,
        re.S,
    ).group(1)
    assert "Neighborhood electricit…" in day_cell
    assert "Neighborhood electricity utility with a long name" in day_cell
    assert "Bills · Utilities · Electricity" in day_cell
    assert "Remaining" in day_cell
    assert "Internet" in day_cell and "Paid · Actual $74.00" in day_cell
    assert "color-0" in day_cell and "color-1" in day_cell

    previous_page = client.get(f"/calendar?month={previous_month:%Y-%m}").data.decode()
    assert f"{previous_month:%B %Y} calendar" in previous_page
    assert f'<option value="{previous_month:%Y-%m}" selected>' in previous_page


def test_cash_flow_splits_budget_periods_and_uses_assigned_month(app, client):
    selected_month = date.today().replace(day=1)
    previous_month = (
        date(selected_month.year - 1, 12, 1)
        if selected_month.month == 1
        else date(selected_month.year, selected_month.month - 1, 1)
    )
    next_month = (
        date(selected_month.year + 1, 1, 1)
        if selected_month.month == 12
        else date(selected_month.year, selected_month.month + 1, 1)
    )
    with app.app_context():
        db.session.add(BalanceCheckpoint(balance=1000, transaction_cutoff_id=0))
        db.session.add_all(
            [
                BudgetItem(
                    month=selected_month,
                    due_date=selected_month.replace(day=1),
                    description="First-period income",
                    amount=500,
                    paid=True,
                ),
                BudgetItem(
                    month=selected_month,
                    due_date=selected_month.replace(day=10),
                    description="First-period bill",
                    amount=-100,
                ),
                BudgetItem(
                    month=selected_month,
                    due_date=selected_month.replace(day=15),
                    description="Second-period income",
                    amount=400,
                ),
                BudgetItem(
                    month=selected_month,
                    due_date=selected_month.replace(day=20),
                    description="Second-period bill",
                    amount=-75,
                    paid=True,
                ),
                Transaction(
                    bank_date=previous_month.replace(day=28),
                    budget_month=selected_month,
                    amount=500,
                    bank_description="Assigned early salary",
                    transaction_type="Income",
                    parent_category="Employment",
                    subcategory="Salary",
                ),
                Transaction(
                    bank_date=selected_month.replace(day=5),
                    budget_month=selected_month,
                    amount=-100,
                    bank_description="Assigned utility",
                    transaction_type="Bills",
                    parent_category="Utilities",
                    subcategory="Electricity",
                ),
                Transaction(
                    bank_date=next_month.replace(day=2),
                    budget_month=next_month,
                    amount=-25,
                    bank_description="Different month transaction",
                ),
            ]
        )
        db.session.commit()

    response = client.get(f"/cash-flow?month={selected_month:%Y-%m}")

    assert response.status_code == 200
    page = response.data.decode()
    assert "Current bank balance" in page
    assert "Available after budget" in page
    assert "Period 1" in page and "Days 1–14" in page
    assert "Period 2" in page and "Days 15–month end" in page
    assert page.count('<details class="period-items" open>') == 2
    assert "First-period income" in page and "$500.00" in page
    assert "First-period bill" in page and "$100.00" in page
    assert "Second-period income" in page and "$400.00" in page
    assert "Second-period bill" in page and "$75.00" in page
    period_tables = re.findall(r'<table class="data-table period-table">(.*?)</table>', page, re.S)
    assert len(period_tables) == 2
    assert all("Actual date" not in table for table in period_tables)
    assert "Assigned early salary" in page
    assert previous_month.replace(day=28).strftime("%m-%d-%Y") in page
    assert "Assigned utility" in page
    assert page.index("Assigned early salary") < page.index("Assigned utility")
    assert "Different month transaction" not in page
    assert f'<option value="{next_month:%Y-%m}"' in page


def test_cash_flow_generates_recurring_items_for_next_month(app, client):
    current_month = date.today().replace(day=1)
    next_month = (
        date(current_month.year + 1, 1, 1)
        if current_month.month == 12
        else date(current_month.year, current_month.month + 1, 1)
    )
    with app.app_context():
        db.session.add(
            RecurringTemplate(
                description="Future rent",
                amount=-1200,
                day_of_month=3,
                anchor_month=current_month,
                interval_months=1,
            )
        )
        db.session.commit()

    response = client.get(f"/cash-flow?month={next_month:%Y-%m}")

    assert response.status_code == 200
    assert b"Future rent" in response.data
    with app.app_context():
        item = BudgetItem.query.filter_by(month=next_month, description="Future rent").one()
        assert item.due_date == next_month.replace(day=3)


def test_budget_generates_newly_configured_recurring_item_for_next_month(app, client):
    current_month = date.today().replace(day=1)
    next_month = (
        date(current_month.year + 1, 1, 1)
        if current_month.month == 12
        else date(current_month.year, current_month.month + 1, 1)
    )
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=current_month,
            amount=-75,
            bank_description="New monthly service",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    recurring_response = client.post(
        f"/transactions/{transaction_id}/recurring",
        data={"enabled": "true", "interval": "1", "create_new": "true"},
    )
    next_budget = client.get(f"/budget?month={next_month:%Y-%m}")

    assert recurring_response.status_code == 200
    assert next_budget.status_code == 200
    assert b"New monthly service" in next_budget.data
    with app.app_context():
        assert BudgetItem.query.filter_by(
            month=next_month,
            description="New monthly service",
        ).one().due_date == next_month.replace(day=date.today().day)


def test_cash_flow_period_balances_use_actual_activity_and_independent_chains(app, client):
    month = date(2026, 9, 1)
    with app.app_context():
        db.session.add(BalanceCheckpoint(balance=1000, transaction_cutoff_id=0))
        db.session.add(MonthRecord(month=date(2026, 8, 1), closed=True, ending_balance=9999))
        income = BudgetItem(
            month=month,
            due_date=date(2026, 9, 1),
            description="Paid income",
            amount=500,
            paid=True,
        )
        first_expense = BudgetItem(
            month=month,
            due_date=date(2026, 9, 10),
            description="First expense",
            amount=-100,
            paid=True,
        )
        first_unpaid_expense = BudgetItem(
            month=month,
            due_date=date(2026, 9, 11),
            description="First unpaid expense",
            amount=-60,
        )
        first_unpaid_income = BudgetItem(
            month=month,
            due_date=date(2026, 9, 12),
            description="First unpaid income",
            amount=200,
        )
        unpaid_income = BudgetItem(
            month=month,
            due_date=date(2026, 9, 15),
            description="Unpaid income",
            amount=400,
        )
        second_expense = BudgetItem(
            month=month,
            due_date=date(2026, 9, 20),
            description="Second expense",
            amount=-75,
        )
        income_transaction = Transaction(
            bank_date=date(2026, 9, 1),
            budget_month=month,
            amount=450,
            bank_description="Paid income",
        )
        expense_transaction = Transaction(
            bank_date=date(2026, 9, 10),
            budget_month=month,
            amount=-90,
            bank_description="First expense",
        )
        non_budget_transaction = Transaction(
            bank_date=date(2026, 9, 12),
            budget_month=month,
            amount=-25,
            bank_description="Unbudgeted purchase",
        )
        db.session.add_all(
            [
                income,
                first_expense,
                first_unpaid_expense,
                first_unpaid_income,
                unpaid_income,
                second_expense,
                income_transaction,
                expense_transaction,
                non_budget_transaction,
            ]
        )
        db.session.flush()
        income.transaction_id = income_transaction.id
        income.actual_amount = income_transaction.amount
        first_expense.transaction_id = expense_transaction.id
        first_expense.actual_amount = expense_transaction.amount
        db.session.commit()

    response = client.get("/cash-flow?month=2026-09")
    page = response.data.decode()

    assert response.status_code == 200
    assert 'data-balance="budget" data-value="540.00"' in page
    assert 'data-balance="all-activity" data-value="1475.00"' in page
    assert 'data-balance="conservative" data-value="1275.00"' in page
    assert 'data-balance="budget" data-value="325.00"' in page
    assert 'data-balance="all-activity" data-value="1800.00"' in page
    assert 'data-balance="conservative" data-value="1200.00"' in page
    assert "Available after budget</span><strong>$1,800.00" in page
    assert "Incoming paid</span><strong class=\"positive-text\">$450.00" in page
    assert "Outgoing paid</span><strong class=\"negative-text\">$90.00" in page
    assert "the current remaining balance" in page
    assert "All activity starts with Period 1's" in page


def test_budget_matches_include_transactions_from_previous_calendar_month(app, client):
    with app.app_context():
        template = RecurringTemplate(
            description="Checking Transfer",
            amount=-500,
            day_of_month=1,
            anchor_month=date(2026, 9, 1),
        )
        db.session.add(template)
        db.session.flush()
        db.session.add_all(
            [
                BudgetItem(
                    month=date(2026, 9, 1),
                    due_date=date(2026, 9, 1),
                    description="Checking Transfer",
                    amount=-500,
                    recurring_template_id=template.id,
                ),
                Transaction(
                    bank_date=date(2026, 8, 26),
                    budget_month=date(2026, 8, 1),
                    amount=-500,
                    bank_description="Checking Transfer 08-26",
                ),
                Transaction(
                    bank_date=date(2026, 7, 31),
                    budget_month=date(2026, 7, 1),
                    amount=-500,
                    bank_description="Too old transfer",
                ),
            ]
        )
        db.session.commit()

    response = client.get("/budget?month=2026-09")

    assert response.status_code == 200
    assert b"08-26 \xc2\xb7 Checking Transfer 08-26" in response.data
    assert b"Too old transfer" not in response.data
    assert b">Recurring</span>" not in response.data
    assert b"sessionStorage.setItem('budget-scroll-position'" in response.data


def test_budget_transaction_association_saves_without_marking_paid(app, client):
    month = date.today().replace(day=1)
    with app.app_context():
        item = BudgetItem(
            month=month,
            due_date=date.today(),
            description="Checking Transfer",
            amount=-500,
        )
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=month,
            amount=-500,
            bank_description="Checking Transfer",
        )
        db.session.add_all([item, transaction])
        db.session.commit()
        item_id = item.id
        transaction_id = transaction.id

    response = client.post(
        f"/budget/{item_id}/paid",
        data={"paid": "false", "transaction_match": f"transaction:{transaction_id}"},
    )

    assert response.status_code == 200
    with app.app_context():
        item = db.session.get(BudgetItem, item_id)
        assert not item.paid
        assert item.transaction_id == transaction_id
        assert item.actual_amount == Decimal("-500.00")

    page = client.get(f"/budget?month={month:%Y-%m}")
    assert f'<option value="transaction:{transaction_id}" selected>'.encode() in page.data


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


def test_transactions_show_budget_months_and_month_after_latest_date(app, client):
    with app.app_context():
        db.session.add(
            Transaction(
                bank_date=date(2099, 12, 15),
                budget_month=date(2099, 11, 1),
                amount=-10,
                bank_description="Future transaction",
            )
        )
        db.session.commit()

    response = client.get("/transactions")

    assert response.status_code == 200
    assert b'<option value="2099-11" selected>November 2099</option>' in response.data
    assert b'<option value="2099-12" >December 2099</option>' in response.data
    assert b'<option value="2100-01" >January 2100</option>' in response.data


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


def test_reconciliation_reviews_description_differences_then_imports_and_removes(app, client):
    with app.app_context():
        exact = Transaction(
            bank_date=date(2026, 6, 10),
            budget_month=date(2026, 6, 1),
            amount=-10,
            bank_description="Exact Match",
        )
        differing = Transaction(
            bank_date=date(2026, 5, 1),
            budget_month=date(2026, 5, 1),
            amount=-5,
            bank_description="PENDING COFFEE",
        )
        extra = Transaction(
            bank_date=date(2026, 5, 20),
            budget_month=date(2026, 5, 1),
            amount=-8,
            bank_description="Duplicate purchase",
        )
        pending = Transaction(
            bank_date=date(2026, 6, 11),
            budget_month=date(2026, 6, 1),
            amount=-7,
            bank_description="Pending card",
        )
        db.session.add_all([exact, differing, extra, pending])
        db.session.commit()
        differing_id = differing.id
        extra_id = extra.id
        pending_id = pending.id

    csv_data = b"Date,Amount,Description\n5/1/2026,-5,CARD PURCHASE COFFEE\n5/5/2026,-9,Missing import\n6/10/2026,-10, exact   match \n"
    response = client.post(
        "/admin/reconcile/preview",
        data={"csv_file": (io.BytesIO(csv_data), "recent.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Description differs" in response.data
    assert b"PENDING COFFEE" in response.data
    token = response.request.path.rsplit("/", 1)[-1]

    response = client.post(
        f"/admin/reconcile/{token}/review",
        data={"match_0": differing_id},
        follow_redirects=True,
    )
    assert b"Not imported" in response.data
    assert b"Missing import" in response.data
    assert b"Pending card" in response.data
    assert b"Duplicate purchase" in response.data
    assert b">2</strong>" in response.data

    response = client.post(
        f"/admin/reconcile/{token}/apply",
        data={"import_row": "1", "remove_transaction": extra_id},
        follow_redirects=True,
    )
    assert b"imported 1 and removed 1 transaction" in response.data
    with app.app_context():
        assert Transaction.query.filter_by(bank_description="Missing import").one().deleted_at is None
        assert db.session.get(Transaction, extra_id).deleted_at is not None
        assert db.session.get(Transaction, pending_id).deleted_at is None


def test_reconciliation_does_not_allow_pending_transaction_removal(app, client):
    with app.app_context():
        pending = Transaction(
            bank_date=date(2026, 6, 2),
            budget_month=date(2026, 6, 1),
            amount=-7,
            bank_description="Pending card",
        )
        db.session.add(pending)
        db.session.commit()
        pending_id = pending.id

    response = client.post(
        "/admin/reconcile/preview",
        data={
            "csv_file": (
                io.BytesIO(b"Date,Amount,Description\n6/1/2026,-1,Only CSV transaction\n"),
                "recent.csv",
            )
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    token = response.request.path.rsplit("/", 1)[-1]

    client.post(
        f"/admin/reconcile/{token}/apply",
        data={"remove_transaction": pending_id},
    )

    with app.app_context():
        assert db.session.get(Transaction, pending_id).deleted_at is None


def test_later_import_defaults_to_the_transaction_date_month(app, client):
    with app.app_context():
        db.session.add(
            Transaction(
                bank_date=date.today(),
                budget_month=date.today().replace(day=1),
                amount=-1,
                bank_description="Existing transaction",
            )
        )
        db.session.add(BalanceCheckpoint(balance=100, transaction_cutoff_id=1))
        db.session.commit()
    response = client.post(
        "/admin/import/preview",
        data={
            "csv_file": (
                io.BytesIO(b"Date,Amount,Description\n4/30/2025,2000,Early salary\n"),
                "later.csv",
            )
        },
        content_type="multipart/form-data",
    )
    preview = max(
        Path(app.instance_path, "import_previews").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
    )

    response = client.post("/admin/import/confirm", data={"token": preview.stem})

    assert response.status_code == 302
    with app.app_context():
        imported = Transaction.query.filter_by(bank_description="Early salary").one()
        assert imported.budget_month == date(2025, 4, 1)


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


def test_deleting_checkpointed_expense_updates_summary_and_cash_flow_balances(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=date.today().replace(day=1),
            amount=Decimal("-7.56"),
            bank_description="Manual transaction",
            custom_description="Temporary expense",
            source="manual",
        )
        db.session.add(transaction)
        db.session.flush()
        db.session.add(
            BalanceCheckpoint(
                balance=Decimal("92.44"),
                transaction_cutoff_id=transaction.id,
            )
        )
        db.session.commit()
        transaction_id = transaction.id

    client.post(f"/transactions/{transaction_id}/delete")
    summary = client.get("/").data.decode()
    cash_flow = client.get("/cash-flow").data.decode()

    assert "Checking balance</span><strong>$100.00" in summary
    assert "Current bank balance</span><strong>$100.00" in cash_flow


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


def test_transaction_budget_month_can_be_changed_without_changing_bulk_matches(app, client):
    with app.app_context():
        selected = Transaction(
            bank_date=date(2026, 8, 30),
            budget_month=date(2026, 8, 1),
            amount=2000,
            bank_description="Twice-monthly pay",
        )
        match = Transaction(
            bank_date=date(2026, 8, 15),
            budget_month=date(2026, 8, 1),
            amount=1900,
            bank_description="Twice-monthly pay",
        )
        db.session.add_all([selected, match])
        db.session.commit()
        selected_id = selected.id
        match_id = match.id

    response = client.post(
        f"/transactions/{selected_id}/edit",
        data={
            "amount": "2000",
            "custom_description": "Salary",
            "budget_month": "2026-09",
            "apply_to": str(match_id),
        },
    )

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Transaction, selected_id).budget_month == date(2026, 9, 1)
        assert db.session.get(Transaction, match_id).budget_month == date(2026, 8, 1)
        assert db.session.get(Transaction, match_id).custom_description == "Salary"


def test_salary_budget_month_change_updates_open_schedule_and_association(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date(2026, 8, 27),
            budget_month=date(2026, 8, 1),
            amount=4118.31,
            bank_description="CONCUR TECHNOLOGPAYMENTS",
            custom_description="Concur Technologies (Salary)",
            transaction_type="Income",
            parent_category="Employment",
            subcategory="Salary",
            is_recurring=True,
        )
        db.session.add(transaction)
        db.session.flush()
        template = RecurringTemplate(
            description=transaction.display_description,
            amount=transaction.amount,
            day_of_month=27,
            anchor_month=date(2026, 8, 1),
            interval_months=1,
            transaction_type="Income",
            parent_category="Employment",
            subcategory="Salary",
            created_from_transaction_id=transaction.id,
        )
        db.session.add(template)
        db.session.flush()
        august_item = BudgetItem(
            month=date(2026, 8, 1),
            due_date=date(2026, 8, 27),
            description=template.description,
            amount=template.amount,
            recurring_template_id=template.id,
        )
        september_item = BudgetItem(
            month=date(2026, 9, 1),
            due_date=date(2026, 9, 27),
            description=template.description,
            amount=template.amount,
            recurring_template_id=template.id,
        )
        db.session.add_all(
            [august_item, september_item, MonthRecord(month=date(2026, 8, 1), closed=True)]
        )
        db.session.commit()
        transaction_id = transaction.id
        template_id = template.id
        august_item_id = august_item.id
        september_item_id = september_item.id

    response = client.post(
        f"/transactions/{transaction_id}/edit",
        data={
            "amount": "4118.31",
            "custom_description": "Concur Technologies (Salary)",
            "transaction_type": "Income",
            "parent_category": "Employment",
            "subcategory": "Salary",
            "budget_month": "2026-09",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        template = db.session.get(RecurringTemplate, template_id)
        assert template.anchor_month == date(2026, 9, 1)
        assert template.day_of_month == 1
        assert db.session.get(BudgetItem, august_item_id).due_date == date(2026, 8, 27)
        september_item = db.session.get(BudgetItem, september_item_id)
        assert september_item.due_date == date(2026, 9, 1)
        assert september_item.transaction_id == transaction_id
        assert september_item.actual_amount == Decimal("4118.31")

    budget_page = client.get("/budget?month=2026-09")
    assert b"Budget date" in budget_page.data
    assert b"Actual date" in budget_page.data
    assert b"08-27-2026" in budget_page.data


def test_second_half_salary_recurs_on_fifteenth(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date(2026, 9, 12),
            budget_month=date(2026, 9, 1),
            amount=4118.31,
            bank_description="CONCUR TECHNOLOGPAYMENTS",
            custom_description="Concur Technologies (Salary)",
            transaction_type="Income",
            parent_category="Employment",
            subcategory="Salary",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    response = client.post(
        f"/transactions/{transaction_id}/recurring",
        data={"enabled": "true", "interval": "1", "create_new": "true"},
    )

    assert response.status_code == 200
    with app.app_context():
        template = RecurringTemplate.query.one()
        item = BudgetItem.query.one()
        assert template.day_of_month == 15
        assert item.due_date == date(2026, 9, 15)


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
    assert [match["amount_difference"] for match in response.json["matches"]] == [100.0, 50.0]
    assert response.json["target_amount"] == 2000.0

    edited_amount_response = client.get(
        f"/transactions/{transaction_id}/matches", query_string={"amount": "2050"}
    )
    assert [match["amount_difference"] for match in edited_amount_response.json["matches"]] == [150.0, 0.0]


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
        data={"enabled": "true", "interval": "1", "create_new": "true"},
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


def test_import_inherits_matching_transaction_metadata(app, client):
    with app.app_context():
        db.session.add(
            Transaction(
                bank_date=date(2026, 8, 15),
                budget_month=date(2026, 8, 1),
                amount=2000,
                bank_description="CONCUR TECHNOLOGPAYMENTS",
                custom_description="Salary",
                transaction_type="Income",
                parent_category="Employment",
                subcategory="Salary",
                is_recurring=True,
            )
        )
        db.session.add(BalanceCheckpoint(balance=2000, transaction_cutoff_id=1))
        db.session.commit()
    response = client.post(
        "/admin/import/preview",
        data={
            "csv_file": (
                io.BytesIO(
                    b"Date,Amount,Description\n9/1/2026,1950,  concur technologpayments  \n"
                ),
                "new.csv",
            )
        },
        content_type="multipart/form-data",
    )
    preview = max(
        Path(app.instance_path, "import_previews").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
    )

    response = client.post("/admin/import/confirm", data={"token": preview.stem})

    assert response.status_code == 302
    with app.app_context():
        imported = Transaction.query.filter_by(amount=1950).one()
        assert imported.custom_description == "Salary"
        assert imported.transaction_type == "Income"
        assert imported.parent_category == "Employment"
        assert imported.subcategory == "Salary"
        assert imported.is_recurring


def test_recurring_transaction_can_associate_existing_budget_item_without_duplicate(app, client):
    month = date.today().replace(day=1)
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=month,
            amount=-125,
            bank_description="Internet provider",
            custom_description="Internet",
            transaction_type="Bills",
            parent_category="Utilities",
            subcategory="Internet",
        )
        budget_item = BudgetItem(
            month=month,
            due_date=date.today(),
            description="Internet",
            amount=-120,
            transaction_type="Bills",
            parent_category="Utilities",
            subcategory="Internet",
        )
        db.session.add_all([transaction, budget_item])
        db.session.commit()
        transaction_id = transaction.id
        budget_item_id = budget_item.id

    matches = client.get(
        f"/transactions/{transaction_id}/recurring-matches",
        query_string={"description": "Internet", "budget_month": month.strftime("%Y-%m")},
    )
    response = client.post(
        f"/transactions/{transaction_id}/recurring",
        data={"enabled": "true", "interval": "1", "budget_item_id": budget_item_id},
    )

    assert matches.status_code == 200
    assert [item["id"] for item in matches.json["matches"]] == [budget_item_id]
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(Transaction, transaction_id).is_recurring
        item = db.session.get(BudgetItem, budget_item_id)
        assert item.transaction_id == transaction_id
        assert item.actual_amount == Decimal("-125.00")
        assert item.recurring_template_id is not None
        assert BudgetItem.query.count() == 1
        assert RecurringTemplate.query.count() == 1


def test_recurring_matches_include_same_amount_with_different_description(app, client):
    month = date.today().replace(day=1)
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=month,
            amount=-89.56,
            bank_description="VERIZON WIRELESS",
            custom_description="Verizon Wireless Samuel reimbursement",
        )
        budget_item = BudgetItem(
            month=month,
            due_date=date.today(),
            description="Samuel phone reimbursement",
            amount=-89.56,
        )
        db.session.add_all([transaction, budget_item])
        db.session.commit()
        transaction_id = transaction.id
        budget_item_id = budget_item.id

    response = client.get(f"/transactions/{transaction_id}/recurring-matches")

    assert response.status_code == 200
    assert [item["id"] for item in response.json["matches"]] == [budget_item_id]
    assert response.json["matches"][0]["suggested"]

    changed_amount_response = client.get(
        f"/transactions/{transaction_id}/recurring-matches",
        query_string={"amount": "-80.00"},
    )
    assert changed_amount_response.json["matches"] == []


def test_recurring_create_reuses_its_existing_budget_item(app, client):
    with app.app_context():
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=date.today().replace(day=1),
            amount=-50,
            bank_description="Subscription",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    first = client.post(
        f"/transactions/{transaction_id}/recurring",
        data={"enabled": "true", "interval": "1", "create_new": "true"},
    )
    second = client.post(
        f"/transactions/{transaction_id}/recurring",
        data={"enabled": "true", "interval": "1"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    with app.app_context():
        assert RecurringTemplate.query.count() == 1
        assert BudgetItem.query.count() == 1


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


def test_transaction_export_includes_recurring_and_budget_status(app, client):
    with app.app_context():
        budgeted = Transaction(
            bank_date=date(2026, 9, 5),
            budget_month=date(2026, 9, 1),
            amount=-25,
            bank_description="Budgeted subscription",
            is_recurring=True,
        )
        unbudgeted = Transaction(
            bank_date=date(2026, 9, 6),
            budget_month=date(2026, 9, 1),
            amount=-10,
            bank_description="One-time purchase",
        )
        db.session.add_all([budgeted, unbudgeted])
        db.session.flush()
        template = RecurringTemplate(
            description="Budgeted subscription",
            amount=-25,
            day_of_month=5,
            anchor_month=date(2026, 9, 1),
            created_from_transaction_id=budgeted.id,
        )
        db.session.add(template)
        db.session.flush()
        db.session.add(
            BudgetItem(
                month=date(2026, 9, 1),
                due_date=date(2026, 9, 5),
                description="Budgeted subscription",
                amount=-25,
                recurring_template_id=template.id,
            )
        )
        db.session.commit()

    response = client.get("/admin/export/transactions")
    rows = list(csv.DictReader(io.StringIO(response.data.decode())))

    assert response.status_code == 200
    assert rows[0]["Budget Month"] == "2026-09"
    assert rows[0]["Recurring"] == "Yes"
    assert rows[0]["In Budget"] == "Yes"
    assert rows[1]["Recurring"] == "No"
    assert rows[1]["In Budget"] == "No"


def test_budget_export_supports_single_month_and_range(app, client):
    with app.app_context():
        db.session.add_all(
            [
                BudgetItem(
                    month=date(2026, 8, 1),
                    due_date=date(2026, 8, 5),
                    description="August",
                    amount=-1,
                ),
                BudgetItem(
                    month=date(2026, 9, 1),
                    due_date=date(2026, 9, 5),
                    description="September",
                    amount=-2,
                ),
                BudgetItem(
                    month=date(2026, 10, 1),
                    due_date=date(2026, 10, 5),
                    description="October",
                    amount=-3,
                ),
            ]
        )
        db.session.commit()

    single = client.get("/admin/export/budget?start_month=2026-09")
    ranged = client.get("/admin/export/budget?start_month=2026-08&end_month=2026-09")
    invalid = client.get("/admin/export/budget?start_month=2026-10&end_month=2026-09")

    assert "September" in single.data.decode()
    assert "August" not in single.data.decode() and "October" not in single.data.decode()
    assert "budgets-2026-09.csv" in single.headers["Content-Disposition"]
    assert "August" in ranged.data.decode() and "September" in ranged.data.decode()
    assert "October" not in ranged.data.decode()
    assert "budgets-2026-08-to-2026-09.csv" in ranged.headers["Content-Disposition"]
    assert invalid.status_code == 400
