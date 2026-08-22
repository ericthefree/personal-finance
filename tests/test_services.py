from datetime import date
from decimal import Decimal

import pytest

from personal_finance.models import (
    BalanceCheckpoint,
    BudgetItem,
    RecurringTemplate,
    Transaction,
    db,
)
from personal_finance.services import (
    available_balance,
    current_balance,
    generate_budget_items,
    month_start,
    monthly_spending,
    parse_csv_upload,
)


def test_csv_finds_header_after_preamble_and_normalizes_amounts():
    raw = b"\nAccount ending 1234\nDate,Amount,Description,Ref. #\n8/21/2026,-2,Coffee,abc\n8/22/2026,4118.3,Salary,def\n"

    rows = parse_csv_upload(raw)

    assert rows == [
        {
            "bank_date": "2026-08-21",
            "description": "Coffee",
            "amount": "-2.00",
            "duplicate_in_file": False,
        },
        {
            "bank_date": "2026-08-22",
            "description": "Salary",
            "amount": "4118.30",
            "duplicate_in_file": False,
        },
    ]


def test_csv_accepts_header_as_first_line():
    raw = b"Date,Amount,Description\n8/21/2026,-2,Coffee\n"

    rows = parse_csv_upload(raw)

    assert rows == [
        {
            "bank_date": "2026-08-21",
            "description": "Coffee",
            "amount": "-2.00",
            "duplicate_in_file": False,
        }
    ]


def test_csv_blocks_entire_file_for_invalid_row():
    raw = b"\nAccount\nDate,Amount,Description\n8/21/2026,-2,Coffee\nnot-a-date,5,Bad\n"

    with pytest.raises(ValueError, match="Import blocked"):
        parse_csv_upload(raw)


def test_balance_uses_checkpoint_then_new_signed_transactions(app):
    with app.app_context():
        db.session.add(BalanceCheckpoint(balance=Decimal("2000"), transaction_cutoff_id=0))
        db.session.add_all(
            [
                Transaction(bank_date=date.today(), budget_month=month_start(), amount=-50, bank_description="Debit"),
                Transaction(bank_date=date.today(), budget_month=month_start(), amount=200, bank_description="Credit"),
            ]
        )
        db.session.commit()

        assert current_balance() == Decimal("2150.00")


def test_available_balance_applies_only_remaining_budget(app):
    with app.app_context():
        db.session.add(BalanceCheckpoint(balance=Decimal("1000"), transaction_cutoff_id=0))
        db.session.add_all(
            [
                BudgetItem(month=month_start(), due_date=date.today(), description="Bill", amount=-100),
                BudgetItem(month=month_start(), due_date=date.today(), description="Income", amount=20),
                BudgetItem(month=month_start(), due_date=date.today(), description="Paid", amount=-500, paid=True),
            ]
        )
        db.session.commit()

        assert available_balance() == Decimal("920.00")


def test_spending_excludes_transfers_and_subtracts_reimbursements(app):
    with app.app_context():
        expense = Transaction(
            bank_date=date.today(),
            budget_month=month_start(),
            amount=-450,
            bank_description="Verizon",
            transaction_type="Bills",
        )
        db.session.add(expense)
        db.session.flush()
        db.session.add_all(
            [
                Transaction(
                    bank_date=date.today(),
                    budget_month=month_start(),
                    amount=100,
                    bank_description="Reimbursement",
                    is_reimbursement=True,
                    reimbursement_for_id=expense.id,
                ),
                Transaction(bank_date=date.today(), budget_month=month_start(), amount=-200, bank_description="Savings", transaction_type="Transfers"),
            ]
        )
        db.session.commit()

        assert monthly_spending() == Decimal("350.00")


def test_recurring_day_uses_last_day_of_short_month(app):
    with app.app_context():
        template = RecurringTemplate(
            description="Month end",
            amount=-25,
            day_of_month=31,
            anchor_month=date(2026, 1, 1),
            interval_months=1,
        )
        db.session.add(template)
        db.session.commit()

        generate_budget_items(date(2026, 2, 1))
        db.session.commit()

        item = BudgetItem.query.one()
        assert item.due_date == date(2026, 2, 28)
