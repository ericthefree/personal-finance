from datetime import date
from decimal import Decimal

import pytest

from personal_finance.models import (
    BalanceCheckpoint,
    BudgetItem,
    Category,
    RecurringTemplate,
    Transaction,
    db,
)
from personal_finance.services import (
    available_balance,
    category_tree,
    current_balance,
    generate_budget_items,
    month_start,
    monthly_activity,
    monthly_spending,
    parse_csv_upload,
    reconcile_transactions,
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
    raw = b"Date,Amount,Description\n8/21/26,-2,Coffee\n"

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


def test_csv_limits_invalid_row_report():
    invalid_rows = "".join(f"bad-date-{index},5,Bad\n" for index in range(100))
    raw = f"Date,Amount,Description\n{invalid_rows}".encode()

    with pytest.raises(ValueError) as error:
        parse_csv_upload(raw)

    message = str(error.value)
    assert "Row 2:" in message
    assert "Row 6:" in message
    assert "95 more invalid rows" in message
    assert "Row 7:" not in message
    assert len(message) < 1_000


def test_reconcile_matches_normalized_descriptions_once_and_classifies_unmatched(app):
    rows = [
        {"bank_date": "2026-06-01", "description": "  COFFEE   SHOP ", "amount": "-5.00"},
        {"bank_date": "2026-06-01", "description": "Coffee Shop", "amount": "-5.00"},
        {"bank_date": "2026-05-01", "description": "Missing import", "amount": "-9.00"},
    ]
    with app.app_context():
        db.session.add_all(
            [
                Transaction(bank_date=date(2026, 6, 1), budget_month=date(2026, 6, 1), amount=-5, bank_description="coffee shop"),
                Transaction(bank_date=date(2026, 6, 1), budget_month=date(2026, 6, 1), amount=-7, bank_description="Pending card"),
                Transaction(bank_date=date(2026, 5, 15), budget_month=date(2026, 5, 1), amount=-8, bank_description="Extra copy"),
            ]
        )
        db.session.commit()

        result = reconcile_transactions(rows, Transaction.query.all(), reviewed=True)

        assert result["matched_count"] == 1
        assert [row["index"] for row in result["csv_only"]] == [1, 2]
        assert [transaction.bank_description for transaction in result["pending"]] == ["Pending card"]
        assert [transaction.bank_description for transaction in result["extra"]] == ["Extra copy"]


def test_reconcile_offers_and_applies_manual_description_match(app):
    rows = [
        {"bank_date": "2026-06-01", "description": "CARD PURCHASE COFFEE", "amount": "-5.00"}
    ]
    with app.app_context():
        transaction = Transaction(
            bank_date=date(2026, 6, 1),
            budget_month=date(2026, 6, 1),
            amount=-5,
            bank_description="PENDING COFFEE",
        )
        db.session.add(transaction)
        db.session.commit()

        initial = reconcile_transactions(rows, [transaction])
        reviewed = reconcile_transactions(
            rows, [transaction], manual_matches={0: transaction.id}, reviewed=True
        )

        assert initial["matched_count"] == 0
        assert initial["possible_matches"][0]["candidates"] == [transaction]
        assert initial["csv_only"] == []
        assert initial["pending"] == []
        assert reviewed["matched_count"] == 1
        assert reviewed["csv_only"] == []
        assert reviewed["pending"] == []


def test_category_tree_is_sorted_alphabetically_without_case_sensitivity(app):
    with app.app_context():
        db.session.add_all(
            [
                Category(transaction_type="Test", parent="zebra", subcategory="zulu"),
                Category(transaction_type="Test", parent="Alpha", subcategory="Zulu"),
                Category(transaction_type="Test", parent="Alpha", subcategory="apple"),
            ]
        )
        db.session.commit()

        tree = category_tree()

        assert list(tree) == sorted(tree, key=str.casefold)
        assert list(tree["Test"]) == ["Alpha", "zebra"]
        assert tree["Test"]["Alpha"] == ["apple", "Zulu"]


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
        assert monthly_activity() == {
            "income": Decimal("0"),
            "expenses": Decimal("350.00"),
        }


def test_monthly_activity_separates_income_and_expenses(app):
    with app.app_context():
        db.session.add_all(
            [
                Transaction(
                    bank_date=date.today(),
                    budget_month=month_start(),
                    amount=2500,
                    bank_description="Income",
                ),
                Transaction(
                    bank_date=date.today(),
                    budget_month=month_start(),
                    amount=-625,
                    bank_description="Expense",
                ),
            ]
        )
        db.session.commit()

        assert monthly_activity() == {
            "income": Decimal("2500.00"),
            "expenses": Decimal("625.00"),
        }


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
