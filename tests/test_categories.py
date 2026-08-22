from datetime import date

import pytest

from personal_finance.models import (
    BudgetItem,
    Category,
    CategoryProfile,
    RecurringTemplate,
    Transaction,
    TransactionSplit,
    db,
)
from personal_finance.services import month_start, monthly_activity


def add_custom_category(transaction_type="Custom", parent="Parent", subcategory="Child"):
    category = Category(
        transaction_type=transaction_type,
        parent=parent,
        subcategory=subcategory,
        profile=CategoryProfile(reporting_group="expense"),
    )
    db.session.add(category)
    db.session.flush()
    return category


def test_category_page_and_add_complete_path(app, client):
    response = client.get("/admin/categories")
    assert response.status_code == 200
    assert b"Category management" in response.data

    response = client.post(
        "/admin/categories/add",
        data={
            "transaction_type": "Family",
            "parent": "Children",
            "subcategory": "School",
            "reporting_group": "expense",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        category = Category.query.filter_by(
            transaction_type="Family", parent="Children", subcategory="School"
        ).one()
        assert category.profile.reporting_group == "expense"


@pytest.mark.parametrize(
    ("level", "new_name", "expected"),
    [
        ("type", "Renamed Type", ("Renamed Type", "Parent", "Child")),
        ("parent", "Renamed Parent", ("Custom", "Renamed Parent", "Child")),
        ("subcategory", "Renamed Child", ("Custom", "Parent", "Renamed Child")),
    ],
)
def test_rename_category_level_updates_transaction(app, client, level, new_name, expected):
    with app.app_context():
        add_custom_category()
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=month_start(),
            amount=-10,
            bank_description="Categorized",
            transaction_type="Custom",
            parent_category="Parent",
            subcategory="Child",
        )
        db.session.add(transaction)
        db.session.commit()
        transaction_id = transaction.id

    response = client.post(
        "/admin/categories/rename",
        data={
            "level": level,
            "transaction_type": "Custom",
            "parent": "Parent",
            "subcategory": "Child",
            "new_name": new_name,
        },
    )

    assert response.status_code == 302
    with app.app_context():
        transaction = db.session.get(Transaction, transaction_id)
        assert (
            transaction.transaction_type,
            transaction.parent_category,
            transaction.subcategory,
        ) == expected
        assert Category.query.filter_by(
            transaction_type=expected[0], parent=expected[1], subcategory=expected[2]
        ).one()


def test_renamed_transfer_type_stays_excluded_from_activity(app, client):
    with app.app_context():
        category = Category.query.filter_by(transaction_type="Transfers").first()
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=month_start(),
            amount=-500,
            bank_description="Transfer",
            transaction_type=category.transaction_type,
            parent_category=category.parent,
            subcategory=category.subcategory,
        )
        db.session.add(transaction)
        db.session.commit()

    response = client.post(
        "/admin/categories/rename",
        data={
            "level": "type",
            "transaction_type": "Transfers",
            "new_name": "Money Movement",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        assert monthly_activity()["expenses"] == 0


def test_delete_category_reassigns_every_usage(app, client):
    with app.app_context():
        source = add_custom_category()
        replacement = Category.query.filter_by(
            transaction_type="Expenses", parent="Food", subcategory="Groceries"
        ).one()
        transaction = Transaction(
            bank_date=date.today(),
            budget_month=month_start(),
            amount=-100,
            bank_description="Combined",
            transaction_type="Custom",
            parent_category="Parent",
            subcategory="Child",
        )
        db.session.add(transaction)
        db.session.flush()
        split = TransactionSplit(
            transaction_id=transaction.id,
            description="Part",
            amount=-100,
            transaction_type="Custom",
            parent_category="Parent",
            subcategory="Child",
        )
        template = RecurringTemplate(
            description="Recurring",
            amount=-100,
            day_of_month=1,
            anchor_month=month_start(),
            transaction_type="Custom",
            parent_category="Parent",
            subcategory="Child",
        )
        budget_item = BudgetItem(
            month=month_start(),
            due_date=date.today(),
            description="Budget",
            amount=-100,
            transaction_type="Custom",
            parent_category="Parent",
            subcategory="Child",
        )
        db.session.add_all([split, template, budget_item])
        db.session.commit()
        ids = (transaction.id, split.id, template.id, budget_item.id)
        source_id = source.id
        replacement_id = replacement.id

    response = client.post(
        "/admin/categories/delete",
        data={
            "level": "subcategory",
            "transaction_type": "Custom",
            "parent": "Parent",
            "subcategory": "Child",
            "replacement_id": replacement_id,
        },
    )

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Category, source_id) is None
        records = [
            db.session.get(Transaction, ids[0]),
            db.session.get(TransactionSplit, ids[1]),
            db.session.get(RecurringTemplate, ids[2]),
            db.session.get(BudgetItem, ids[3]),
        ]
        for record in records:
            assert (
                record.transaction_type,
                record.parent_category,
                record.subcategory,
            ) == ("Expenses", "Food", "Groceries")
