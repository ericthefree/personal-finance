import calendar
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func

from .categories import CATEGORY_TREE
from .models import (
    BalanceCheckpoint,
    BudgetItem,
    Category,
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
    if Category.query.first():
        return
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
    db.session.commit()


def current_balance():
    checkpoint = BalanceCheckpoint.query.order_by(BalanceCheckpoint.id.desc()).first()
    if not checkpoint:
        return None
    delta = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(Transaction.id > checkpoint.transaction_cutoff_id, Transaction.deleted_at.is_(None))
        .scalar()
    )
    return Decimal(checkpoint.balance) + Decimal(delta)


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
    month = month or month_start()
    transactions = Transaction.query.filter_by(budget_month=month).filter(
        Transaction.deleted_at.is_(None)
    )
    total = Decimal("0")
    for transaction in transactions:
        entries = transaction.splits or [transaction]
        for entry in entries:
            amount = Decimal(entry.amount)
            if entry.transaction_type == "Transfers":
                continue
            if amount < 0:
                total += abs(amount)
            elif entry.is_reimbursement and entry.reimbursement_for_id:
                total -= amount
    return total


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
            bank_date = datetime.strptime(row[headers["date"]].strip(), "%m/%d/%Y").date()
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


def budget_totals(month):
    items = BudgetItem.query.filter_by(month=month).filter(BudgetItem.deleted_at.is_(None)).all()
    credits = sum((Decimal(item.amount) for item in items if item.amount > 0), Decimal("0"))
    debits = sum((abs(Decimal(item.amount)) for item in items if item.amount < 0), Decimal("0"))
    return {"credits": credits, "debits": debits, "difference": credits - debits}


def budget_type_totals(month):
    items = BudgetItem.query.filter_by(month=month).filter(BudgetItem.deleted_at.is_(None)).all()

    def total_for(predicate):
        return sum((abs(Decimal(item.amount)) for item in items if predicate(item)), Decimal("0"))

    return {
        "income": total_for(lambda item: item.transaction_type == "Income"),
        "expenses": total_for(lambda item: item.transaction_type == "Expenses"),
        "bills": total_for(lambda item: item.transaction_type == "Bills"),
        "loans": total_for(
            lambda item: item.transaction_type == "Debts"
            and item.parent_category in {"Loans", "Mortgage"}
        ),
        "credit_cards": total_for(
            lambda item: item.transaction_type == "Debts"
            and item.parent_category == "Credit Cards"
        ),
        "difference": budget_totals(month)["difference"],
    }
