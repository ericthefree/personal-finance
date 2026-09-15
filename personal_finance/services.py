import calendar
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from .categories import CATEGORY_TREE, default_reporting_group
from .models import (
    BalanceCheckpoint,
    BudgetItem,
    Category,
    CategoryProfile,
    MonthRecord,
    RecurringTemplate,
    Transaction,
    db,
)


def month_start(value=None):
    value = value or date.today()
    return date(value.year, value.month, 1)


def add_months(value, count):
    index = value.year * 12 + value.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def due_date_for(month, day):
    return date(month.year, month.month, min(day, calendar.monthrange(month.year, month.month)[1]))


def seed_categories():
    if not Category.query.first():
        for transaction_type, parents in CATEGORY_TREE.items():
            for parent, subcategories in parents.items():
                for subcategory in subcategories:
                    db.session.add(
                        Category(
                            transaction_type=transaction_type,
                            parent=parent,
                            subcategory=subcategory,
                        )
                    )
        db.session.flush()
    profiled_ids = {
        category_id for (category_id,) in db.session.query(CategoryProfile.category_id).all()
    }
    for category in Category.query.all():
        if category.id not in profiled_ids:
            db.session.add(
                CategoryProfile(
                    category=category,
                    reporting_group=default_reporting_group(
                        category.transaction_type, category.parent
                    ),
                )
            )
    db.session.commit()


def category_tree():
    tree = {}
    categories = sorted(
        Category.query.all(),
        key=lambda category: (
            category.transaction_type.casefold(),
            category.parent.casefold(),
            category.subcategory.casefold(),
        ),
    )
    for category in categories:
        tree.setdefault(category.transaction_type, {}).setdefault(category.parent, []).append(
            category.subcategory
        )
    return tree


def reporting_group_maps():
    exact = {}
    parents = {}
    types = {}
    for category in Category.query.options(joinedload(Category.profile)).all():
        group = category.profile.reporting_group if category.profile else "other"
        exact[(category.transaction_type, category.parent, category.subcategory)] = group
        parent_key = (category.transaction_type, category.parent)
        parents[parent_key] = group if parent_key not in parents else (
            group if parents[parent_key] == group else None
        )
        type_key = category.transaction_type
        types[type_key] = group if type_key not in types else (
            group if types[type_key] == group else None
        )
    return exact, parents, types


def reporting_group_for(entry, maps):
    exact, parents, types = maps
    return (
        exact.get((entry.transaction_type, entry.parent_category, entry.subcategory))
        or parents.get((entry.transaction_type, entry.parent_category))
        or types.get(entry.transaction_type)
        or "other"
    )


def current_balance():
    checkpoint = BalanceCheckpoint.query.order_by(BalanceCheckpoint.id.desc()).first()
    if not checkpoint:
        return None
    active_delta = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.id > checkpoint.transaction_cutoff_id, Transaction.deleted_at.is_(None))
        .scalar()
    )
    deleted_checkpoint_delta = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.id <= checkpoint.transaction_cutoff_id,
            Transaction.deleted_at.is_not(None),
            Transaction.deleted_at >= checkpoint.created_at,
        )
        .scalar()
    )
    return (
        Decimal(checkpoint.balance)
        + Decimal(active_delta)
        - Decimal(deleted_checkpoint_delta)
    )


def ensure_current_month():
    current = month_start()
    records = MonthRecord.query.order_by(MonthRecord.month).all()
    for record in records:
        if record.month < current and not record.closed:
            record.closed = True
            record.ending_balance = current_balance()
    record = MonthRecord.query.filter_by(month=current).first()
    if not record:
        record = MonthRecord(month=current)
        db.session.add(record)
        db.session.flush()
    generate_budget_items(current)
    db.session.commit()
    return record


def generate_budget_items(month):
    for template in RecurringTemplate.query.filter_by(active=True).all():
        elapsed = (month.year - template.anchor_month.year) * 12 + month.month - template.anchor_month.month
        if elapsed < 0 or elapsed % template.interval_months:
            continue
        exists = BudgetItem.query.filter_by(
            month=month, recurring_template_id=template.id
        ).first()
        if not exists:
            db.session.add(
                BudgetItem(
                    month=month,
                    due_date=due_date_for(month, template.day_of_month),
                    description=template.description,
                    amount=template.amount,
                    transaction_type=template.transaction_type,
                    parent_category=template.parent_category,
                    subcategory=template.subcategory,
                    is_reimbursement=template.is_reimbursement,
                    recurring_template_id=template.id,
                )
            )


def available_balance(month=None, base_balance=None):
    balance = current_balance() if base_balance is None else Decimal(base_balance)
    if balance is None:
        return None
    month = month or month_start()
    remaining = BudgetItem.query.filter_by(month=month, paid=False).filter(
        BudgetItem.deleted_at.is_(None)
    )
    return balance + sum((Decimal(item.amount) for item in remaining), Decimal("0"))


def monthly_spending(month=None):
    return monthly_activity(month)["expenses"]


def monthly_activity(month=None):
    month = month or month_start()
    transactions = Transaction.query.filter_by(budget_month=month).filter(
        Transaction.deleted_at.is_(None)
    )
    income = Decimal("0")
    expenses = Decimal("0")
    group_maps = reporting_group_maps()
    for transaction in transactions:
        entries = transaction.splits or [transaction]
        for entry in entries:
            amount = Decimal(entry.amount)
            if reporting_group_for(entry, group_maps) == "transfer":
                continue
            if amount < 0:
                expenses += abs(amount)
            elif entry.is_reimbursement and entry.reimbursement_for_id:
                expenses -= amount
            elif amount > 0 and not entry.is_reimbursement:
                income += amount
    return {"income": income, "expenses": expenses}


def normalize_header(value):
    return re.sub(r"[^a-z]", "", (value or "").lower())


def parse_csv_upload(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The CSV must use UTF-8 text encoding.") from exc
    lines = text.splitlines()
    required = {"date", "description", "amount"}
    header_index = None
    for index, line in enumerate(lines):
        try:
            columns = next(csv.reader([line]))
        except csv.Error:
            continue
        if required.issubset({normalize_header(column) for column in columns}):
            header_index = index
            break
    if header_index is None:
        raise ValueError("The CSV header must include Date, Description, and Amount.")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    headers = {normalize_header(header): header for header in (reader.fieldnames or [])}

    parsed = []
    errors = []
    error_count = 0
    seen = set()
    for row_number, row in enumerate(reader, start=header_index + 2):
        if not any((row.get(headers[name]) or "").strip() for name in required):
            continue
        try:
            raw_date = row[headers["date"]].strip()
            bank_date = None
            for date_format in ("%m/%d/%Y", "%m/%d/%y"):
                try:
                    bank_date = datetime.strptime(raw_date, date_format).date()
                    break
                except ValueError:
                    continue
            if bank_date is None:
                raise ValueError("date must use M/D/YY or M/D/YYYY")
            description = row[headers["description"]].strip()
            if not description:
                raise ValueError("description is blank")
            amount = Decimal(row[headers["amount"]].replace("$", "").replace(",", "").strip())
            amount = amount.quantize(Decimal("0.01"))
        except (ValueError, InvalidOperation, AttributeError) as exc:
            error_count += 1
            if len(errors) < 5:
                errors.append(f"Row {row_number}: {str(exc)[:160]}")
            continue
        key = (bank_date.isoformat(), description, str(amount))
        duplicate_in_file = key in seen
        seen.add(key)
        parsed.append(
            {
                "bank_date": bank_date.isoformat(),
                "description": description,
                "amount": str(amount),
                "duplicate_in_file": duplicate_in_file,
            }
        )
    if error_count:
        remaining = error_count - len(errors)
        suffix = f" ({remaining} more invalid row{'s' if remaining != 1 else ''}.)" if remaining else ""
        raise ValueError("Import blocked. " + " ".join(errors) + suffix)
    if not parsed:
        raise ValueError("The CSV contains no transaction rows.")
    return parsed


def duplicate_exists(row):
    return Transaction.query.filter_by(
        bank_date=date.fromisoformat(row["bank_date"]),
        bank_description=row["description"],
        amount=Decimal(row["amount"]),
    ).first() is not None


def reconcile_description(value):
    return " ".join((value or "").casefold().split())


def reconcile_transactions(rows, transactions, manual_matches=None, reviewed=False):
    manual_matches = manual_matches or {}
    oldest_date = min(date.fromisoformat(row["bank_date"]) for row in rows)
    newest_date = max(date.fromisoformat(row["bank_date"]) for row in rows)
    available = {
        transaction.id: transaction
        for transaction in transactions
        if transaction.deleted_at is None and transaction.bank_date >= oldest_date
    }
    ignored_duplicate_count = sum(bool(row.get("duplicate_in_file")) for row in rows)
    unmatched_rows = {
        index for index, row in enumerate(rows) if not row.get("duplicate_in_file", False)
    }
    matched_count = 0

    for index in sorted(unmatched_rows.copy()):
        row = rows[index]
        row_key = (
            date.fromisoformat(row["bank_date"]),
            Decimal(row["amount"]),
            reconcile_description(row["description"]),
        )
        match_id = next(
            (
                transaction_id
                for transaction_id, transaction in available.items()
                if (
                    transaction.bank_date,
                    Decimal(transaction.amount),
                    reconcile_description(transaction.bank_description),
                )
                == row_key
            ),
            None,
        )
        if match_id is not None:
            available.pop(match_id)
            unmatched_rows.remove(index)
            matched_count += 1

    for index, transaction_id in manual_matches.items():
        if index not in unmatched_rows or transaction_id not in available:
            continue
        row = rows[index]
        transaction = available[transaction_id]
        if (
            transaction.bank_date == date.fromisoformat(row["bank_date"])
            and Decimal(transaction.amount) == Decimal(row["amount"])
        ):
            available.pop(transaction_id)
            unmatched_rows.remove(index)
            matched_count += 1

    possible_matches = []
    possible_transaction_ids = set()
    possible_row_indexes = set()
    if not reviewed:
        for index in sorted(unmatched_rows):
            row = rows[index]
            candidates = [
                transaction
                for transaction in available.values()
                if transaction.bank_date == date.fromisoformat(row["bank_date"])
                and Decimal(transaction.amount) == Decimal(row["amount"])
            ]
            if candidates:
                possible_matches.append({"row": {**row, "index": index}, "candidates": candidates})
                possible_row_indexes.add(index)
                possible_transaction_ids.update(transaction.id for transaction in candidates)

    csv_only = [
        {**rows[index], "index": index}
        for index in sorted(unmatched_rows - possible_row_indexes)
    ]
    remaining_transactions = [
        transaction
        for transaction_id, transaction in available.items()
        if transaction_id not in possible_transaction_ids
    ]
    pending = sorted(
        (transaction for transaction in remaining_transactions if transaction.bank_date >= newest_date),
        key=lambda transaction: (transaction.bank_date, transaction.id),
        reverse=True,
    )
    extra = sorted(
        (transaction for transaction in remaining_transactions if transaction.bank_date < newest_date),
        key=lambda transaction: (transaction.bank_date, transaction.id),
        reverse=True,
    )
    return {
        "oldest_date": oldest_date,
        "newest_date": newest_date,
        "matched_count": matched_count,
        "ignored_duplicate_count": ignored_duplicate_count,
        "possible_matches": possible_matches,
        "csv_only": csv_only,
        "pending": pending,
        "extra": extra,
    }


def budget_totals(month):
    items = BudgetItem.query.filter_by(month=month).filter(BudgetItem.deleted_at.is_(None)).all()
    credits = sum((Decimal(item.amount) for item in items if item.amount > 0), Decimal("0"))
    debits = sum((abs(Decimal(item.amount)) for item in items if item.amount < 0), Decimal("0"))
    return {"credits": credits, "debits": debits, "difference": credits - debits}


def budget_type_totals(month):
    items = BudgetItem.query.filter_by(month=month).filter(BudgetItem.deleted_at.is_(None)).all()
    group_maps = reporting_group_maps()

    def total_for(group):
        return sum(
            (
                abs(Decimal(item.amount))
                for item in items
                if reporting_group_for(item, group_maps) == group
            ),
            Decimal("0"),
        )

    return {
        "income": total_for("income"),
        "expenses": total_for("expense"),
        "bills": total_for("bill"),
        "loans": total_for("loan"),
        "credit_cards": total_for("credit_card"),
        "difference": budget_totals(month)["difference"],
    }
