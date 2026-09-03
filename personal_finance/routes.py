import csv
import io
import json
import sqlite3
import tempfile
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import asc, desc, func, or_

from .categories import REPORTING_GROUPS
from .models import (
    AuditRecord,
    BalanceCheckpoint,
    BudgetItem,
    Category,
    CategoryProfile,
    ImportBatch,
    MonthRecord,
    RecurringTemplate,
    Transaction,
    TransactionSplit,
    db,
)
from .services import (
    available_balance,
    add_months,
    budget_type_totals,
    budget_totals,
    category_tree,
    current_balance,
    due_date_for,
    duplicate_exists,
    ensure_current_month,
    month_start,
    monthly_activity,
    parse_csv_upload,
)


bp = Blueprint("main", __name__)
VALID_INTERVALS = {1, 3, 6, 12}
CATEGORIZED_MODELS = (Transaction, TransactionSplit, RecurringTemplate, BudgetItem)


def parse_month(value):
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        return month_start()


def form_decimal(name, *, signed=True):
    try:
        value = Decimal(request.form[name].replace("$", "").replace(",", "")).quantize(
            Decimal("0.01")
        )
    except (KeyError, InvalidOperation):
        raise ValueError(f"{name.replace('_', ' ').title()} must be a valid amount.")
    if not signed and value < 0:
        raise ValueError(f"{name.replace('_', ' ').title()} cannot be negative.")
    return value


def recurrence_interval(value):
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recurrence frequency is invalid.") from exc
    if interval not in VALID_INTERVALS:
        raise ValueError("Recurrence frequency is invalid.")
    return interval


def match_text(value):
    return " ".join((value or "").casefold().split())


def require_date_in_month(value, month):
    if month_start(value) != month:
        raise ValueError("Due date must be within the selected budget month.")


def transaction_location(transaction_id):
    page = request.referrer or url_for("main.transactions")
    return f"{page}#transaction-{transaction_id}"


def category_scope(level, transaction_type, parent=None, subcategory=None):
    query = Category.query.filter_by(transaction_type=transaction_type)
    if level in {"parent", "subcategory"}:
        query = query.filter_by(parent=parent)
    if level == "subcategory":
        query = query.filter_by(subcategory=subcategory)
    return query


def category_usage_scope(model, level, transaction_type, parent=None, subcategory=None):
    query = model.query.filter(model.transaction_type == transaction_type)
    if level in {"parent", "subcategory"}:
        query = query.filter(model.parent_category == parent)
    if level == "subcategory":
        query = query.filter(model.subcategory == subcategory)
    return query


def category_name(value, label, maximum):
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    if len(value) > maximum:
        raise ValueError(f"{label} must be {maximum} characters or fewer.")
    return value


@bp.before_app_request
def maintain_months():
    ensure_current_month()


@bp.app_template_filter("currency")
def currency(value):
    if value is None:
        return "—"
    return f"${abs(Decimal(value)):,.2f}"


@bp.app_template_filter("date_us")
def date_us(value):
    return value.strftime("%m-%d-%Y") if value else ""


@bp.app_context_processor
def shared_template_data():
    return {"category_tree": category_tree(), "today": date.today(), "today_month": month_start()}


@bp.route("/")
def summary():
    month = parse_month(request.args.get("month"))
    previous_month = add_months(month, -1)
    record = MonthRecord.query.filter_by(month=month).first()
    balance = record.ending_balance if record and record.closed else current_balance()
    items = BudgetItem.query.filter_by(month=month).filter(BudgetItem.deleted_at.is_(None)).all()
    remaining = [item for item in items if not item.paid]
    type_totals = {}
    for item in items:
        key = item.transaction_type or "Uncategorized"
        type_totals[key] = type_totals.get(key, Decimal("0")) + abs(Decimal(item.amount))
    records = MonthRecord.query.order_by(MonthRecord.month.desc()).all()
    return render_template(
        "summary.html",
        selected_month=month,
        activity=monthly_activity(month),
        previous_month=previous_month,
        previous_activity=monthly_activity(previous_month),
        balance=balance,
        available=available_balance(month, balance) if balance is not None else None,
        remaining=remaining,
        totals=budget_totals(month),
        type_totals=type_totals,
        month_records=records,
    )


@bp.route("/transactions")
def transactions():
    page = max(request.args.get("page", 1, type=int), 1)
    query_text = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date")
    direction = request.args.get("direction", "desc")
    query = Transaction.query.filter(Transaction.deleted_at.is_(None))
    if query_text:
        like = f"%{query_text}%"
        query = query.filter(
            or_(Transaction.bank_description.ilike(like), Transaction.custom_description.ilike(like))
        )
    sort_column = Transaction.amount if sort == "amount" else Transaction.bank_date
    query = query.order_by((asc if direction == "asc" else desc)(sort_column), Transaction.id.desc())
    pagination = query.paginate(page=page, per_page=50, error_out=False)
    transaction_dates = db.session.query(
        Transaction.bank_date, Transaction.budget_month
    ).filter(Transaction.deleted_at.is_(None)).all()
    transaction_months = {
        month_start(value)
        for bank_date, budget_month in transaction_dates
        for value in (bank_date, budget_month)
        if value
    }
    current_month = month_start()
    latest_bank_date = max(
        (bank_date for bank_date, _ in transaction_dates),
        default=None,
    )
    latest_month = max(
        current_month,
        month_start(latest_bank_date) if latest_bank_date else current_month,
    )
    transaction_months.update({current_month, add_months(latest_month, 1)})
    month_options = sorted(transaction_months, reverse=True)
    expenses = Transaction.query.filter(
        Transaction.amount < 0, Transaction.deleted_at.is_(None)
    ).order_by(Transaction.bank_date.desc()).limit(200).all()
    expense_options = [
        {
            "id": expense.id,
            "label": f"{expense.bank_date:%m-%d} · {expense.display_description} · {currency(expense.amount)}",
        }
        for expense in expenses
    ]
    recurring_intervals = {
        template.created_from_transaction_id: template.interval_months
        for template in RecurringTemplate.query.filter(
            RecurringTemplate.created_from_transaction_id.is_not(None)
        )
    }
    return render_template(
        "transactions.html",
        transactions=pagination.items,
        pagination=pagination,
        query_text=query_text,
        sort=sort,
        direction=direction,
        month_options=month_options,
        expenses=expenses,
        expense_options=expense_options,
        recurring_intervals=recurring_intervals,
    )


@bp.post("/transactions/add")
def add_transaction():
    try:
        bank_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        amount = form_decimal("amount")
        description = request.form["description"].strip()
        if not description:
            raise ValueError("Description is required.")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.transactions"))
    transaction = Transaction(
        bank_date=bank_date,
        budget_month=month_start(bank_date),
        amount=amount,
        bank_description="Manual transaction",
        custom_description=description,
        transaction_type=request.form.get("transaction_type") or None,
        parent_category=request.form.get("parent_category") or None,
        subcategory=request.form.get("subcategory") or None,
        is_reimbursement=request.form.get("is_reimbursement") == "on",
        reimbursement_for_id=request.form.get("reimbursement_for_id", type=int),
        source="manual",
    )
    db.session.add(transaction)
    db.session.commit()
    flash("Transaction added.", "success")
    return redirect(url_for("main.transactions"))


@bp.get("/transactions/<int:transaction_id>/matches")
def transaction_matches(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    matches = Transaction.query.filter(
        Transaction.id != transaction.id,
        Transaction.deleted_at.is_(None),
        Transaction.bank_description == transaction.bank_description,
    ).order_by(Transaction.bank_date.desc()).all()
    return {
        "matches": [
            {
                "id": match.id,
                "date": match.bank_date.strftime("%m-%d-%Y"),
                "description": match.display_description,
                "amount": currency(match.amount),
            }
            for match in matches
        ]
    }


@bp.post("/transactions/<int:transaction_id>/edit")
def edit_transaction(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    try:
        amount = form_decimal("amount")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(transaction_location(transaction_id))
    budget_month_value = request.form.get("budget_month")
    try:
        budget_month = (
            datetime.strptime(budget_month_value, "%Y-%m").date().replace(day=1)
            if budget_month_value
            else transaction.budget_month
        )
    except ValueError:
        flash("Budget month must be a valid month and year.", "error")
        return redirect(transaction_location(transaction_id))
    if transaction.splits and amount != transaction.amount:
        flash("Update the split amounts before changing this transaction total.", "error")
        return redirect(transaction_location(transaction_id))
    selected = {int(value) for value in request.form.getlist("apply_to")}
    selected.add(transaction.id)
    targets = Transaction.query.filter(Transaction.id.in_(selected), Transaction.deleted_at.is_(None)).all()
    fields = {
        "custom_description": request.form.get("custom_description", "").strip() or None,
        "transaction_type": request.form.get("transaction_type") or None,
        "parent_category": request.form.get("parent_category") or None,
        "subcategory": request.form.get("subcategory") or None,
    }
    transaction.is_reimbursement = request.form.get("is_reimbursement") == "on"
    transaction.reimbursement_for_id = request.form.get("reimbursement_for_id", type=int)
    transaction.amount = amount
    transaction.budget_month = budget_month
    for budget_item in BudgetItem.query.filter_by(transaction_id=transaction.id).all():
        budget_item.actual_amount = amount
    for target in targets:
        for name, value in fields.items():
            setattr(target, name, value)
        audit_detail = fields.copy()
        if target.id == transaction.id:
            audit_detail["amount"] = str(amount)
            audit_detail["budget_month"] = budget_month.isoformat()
        db.session.add(
            AuditRecord(
                entity_type="transaction",
                entity_id=target.id,
                action="edit",
                detail=json.dumps(audit_detail),
            )
        )
        template = RecurringTemplate.query.filter_by(
            created_from_transaction_id=target.id
        ).first()
        if template:
            template.description = target.display_description
            if target.id == transaction.id:
                template.amount = amount
            template.transaction_type = target.transaction_type
            template.parent_category = target.parent_category
            template.subcategory = target.subcategory
            template.is_reimbursement = target.is_reimbursement
            for budget_item in BudgetItem.query.filter_by(
                recurring_template_id=template.id
            ).all():
                month_record = MonthRecord.query.filter_by(month=budget_item.month).first()
                if month_record and month_record.closed:
                    continue
                budget_item.description = template.description
                budget_item.amount = template.amount
                budget_item.transaction_type = template.transaction_type
                budget_item.parent_category = template.parent_category
                budget_item.subcategory = template.subcategory
                budget_item.is_reimbursement = template.is_reimbursement
    db.session.commit()
    flash(f"Updated {len(targets)} transaction(s).", "success")
    return redirect(transaction_location(transaction_id))


@bp.post("/transactions/<int:transaction_id>/recurring")
def toggle_recurring(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    enabled = request.form.get("enabled") == "true"
    transaction.is_recurring = enabled
    template = RecurringTemplate.query.filter_by(created_from_transaction_id=transaction.id).first()
    if enabled:
        try:
            interval = recurrence_interval(request.form.get("interval", 1))
        except ValueError as exc:
            return {"error": str(exc)}, 400
        budget_item_id = request.form.get("budget_item_id", type=int)
        create_new = request.form.get("create_new") == "true"
        if not budget_item_id and not create_new and not template:
            return {"error": "Choose an existing budget item or create a new one."}, 400
        budget_item = None
        if budget_item_id:
            budget_item = db.get_or_404(BudgetItem, budget_item_id)
            if budget_item.deleted_at or budget_item.month != transaction.budget_month:
                abort(409, "That budget item is not available for this transaction month.")
            budget_item.transaction_id = transaction.id
            budget_item.transaction_split_id = None
            budget_item.actual_amount = transaction.amount
            if budget_item.recurring_template:
                template = budget_item.recurring_template
        if template:
            template.active = True
            template.interval_months = interval
        else:
            template = RecurringTemplate(
                description=transaction.display_description,
                amount=transaction.amount,
                day_of_month=transaction.bank_date.day,
                anchor_month=transaction.budget_month,
                interval_months=interval,
                transaction_type=transaction.transaction_type,
                parent_category=transaction.parent_category,
                subcategory=transaction.subcategory,
                is_reimbursement=transaction.is_reimbursement,
                created_from_transaction_id=transaction.id,
            )
            db.session.add(template)
            db.session.flush()
        if budget_item:
            budget_item.recurring_template_id = template.id
        else:
            budget_item = BudgetItem.query.filter_by(
                month=transaction.budget_month,
                recurring_template_id=template.id,
            ).filter(BudgetItem.deleted_at.is_(None)).first()
        if not budget_item:
            db.session.add(
                BudgetItem(
                    month=transaction.budget_month,
                    due_date=due_date_for(transaction.budget_month, transaction.bank_date.day),
                    description=template.description,
                    amount=template.amount,
                    transaction_type=template.transaction_type,
                    parent_category=template.parent_category,
                    subcategory=template.subcategory,
                    recurring_template_id=template.id,
                )
            )
    elif template:
        template.active = False
    db.session.commit()
    return {"ok": True, "enabled": enabled}


@bp.get("/transactions/<int:transaction_id>/recurring-matches")
def recurring_budget_matches(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    description = match_text(request.args.get("description") or transaction.display_description)
    transaction_type = request.args.get("transaction_type") or transaction.transaction_type
    parent = request.args.get("parent_category") or transaction.parent_category
    subcategory = request.args.get("subcategory") or transaction.subcategory
    budget_month_value = request.args.get("budget_month")
    try:
        budget_month = (
            datetime.strptime(budget_month_value, "%Y-%m").date().replace(day=1)
            if budget_month_value
            else transaction.budget_month
        )
    except ValueError:
        return {"error": "Budget month must be a valid month and year."}, 400

    configured = bool(
        RecurringTemplate.query.filter_by(
            created_from_transaction_id=transaction.id,
            active=True,
        ).first()
        or BudgetItem.query.filter_by(transaction_id=transaction.id).filter(
            BudgetItem.recurring_template_id.is_not(None),
            BudgetItem.deleted_at.is_(None),
        ).first()
    )
    matches = []
    for item in BudgetItem.query.filter_by(month=budget_month).filter(
        BudgetItem.deleted_at.is_(None)
    ):
        description_matches = description and match_text(item.description) == description
        category_matches = bool(
            parent
            and item.transaction_type == transaction_type
            and item.parent_category == parent
            and (not subcategory or item.subcategory == subcategory)
        )
        if not description_matches and not category_matches:
            continue
        matches.append(
            {
                "id": item.id,
                "date": item.due_date.strftime("%m-%d-%Y"),
                "description": item.description,
                "amount": currency(item.amount),
                "recurring": bool(item.recurring_template_id),
            }
        )
    matches.sort(key=lambda item: item["date"])
    return {"matches": matches, "configured": configured}


@bp.post("/transactions/<int:transaction_id>/delete")
def delete_transaction(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    transaction.deleted_at = datetime.now()
    db.session.add(
        AuditRecord(entity_type="transaction", entity_id=transaction.id, action="delete")
    )
    db.session.commit()
    flash("Transaction removed and retained in the audit record.", "success")
    return redirect(url_for("main.transactions"))


@bp.post("/transactions/<int:transaction_id>/splits")
def save_splits(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    payload = request.get_json(force=True)
    splits = payload.get("splits", [])
    try:
        amounts = [Decimal(str(split["amount"])) for split in splits]
        intervals = [
            recurrence_interval(split.get("interval_months", 1))
            for split in splits
        ]
    except (InvalidOperation, KeyError, ValueError):
        return {"error": "Every split needs a valid amount."}, 400
    if sum(amounts, Decimal("0")) != Decimal(transaction.amount):
        return {"error": "Split amounts must equal the bank transaction amount."}, 400
    old_split_ids = [split.id for split in transaction.splits]
    if old_split_ids:
        RecurringTemplate.query.filter(
            RecurringTemplate.created_from_split_id.in_(old_split_ids)
        ).update({RecurringTemplate.active: False}, synchronize_session=False)
    transaction.splits.clear()
    for split, amount, interval in zip(splits, amounts, intervals):
        transaction_split = TransactionSplit(
            description=split.get("description", "").strip() or transaction.display_description,
            amount=amount,
            transaction_type=split.get("transaction_type") or None,
            parent_category=split.get("parent_category") or None,
            subcategory=split.get("subcategory") or None,
            is_recurring=bool(split.get("is_recurring")),
            is_reimbursement=bool(split.get("is_reimbursement")),
            reimbursement_for_id=split.get("reimbursement_for_id") or None,
        )
        transaction.splits.append(transaction_split)
        db.session.flush()
        if transaction_split.is_recurring:
            template = RecurringTemplate(
                description=transaction_split.description,
                amount=transaction_split.amount,
                day_of_month=transaction.bank_date.day,
                anchor_month=transaction.budget_month,
                interval_months=interval,
                transaction_type=transaction_split.transaction_type,
                parent_category=transaction_split.parent_category,
                subcategory=transaction_split.subcategory,
                is_reimbursement=transaction_split.is_reimbursement,
                created_from_split_id=transaction_split.id,
            )
            db.session.add(template)
            db.session.flush()
            db.session.add(
                BudgetItem(
                    month=month_start(),
                    due_date=due_date_for(month_start(), transaction.bank_date.day),
                    description=template.description,
                    amount=template.amount,
                    transaction_type=template.transaction_type,
                    parent_category=template.parent_category,
                    subcategory=template.subcategory,
                    is_reimbursement=template.is_reimbursement,
                    recurring_template_id=template.id,
                )
            )
    db.session.commit()
    return {"ok": True}


@bp.get("/transactions/<int:transaction_id>/splits")
def get_splits(transaction_id):
    transaction = db.get_or_404(Transaction, transaction_id)
    return {
        "splits": [
            {
                "description": split.description,
                "amount": str(split.amount),
                "transaction_type": split.transaction_type or "",
                "parent_category": split.parent_category or "",
                "subcategory": split.subcategory or "",
                "is_recurring": split.is_recurring,
                "is_reimbursement": split.is_reimbursement,
                "reimbursement_for_id": split.reimbursement_for_id,
                "interval_months": (
                    RecurringTemplate.query.filter_by(
                        created_from_split_id=split.id, active=True
                    ).first().interval_months
                    if split.is_recurring
                    and RecurringTemplate.query.filter_by(
                        created_from_split_id=split.id, active=True
                    ).first()
                    else 1
                ),
            }
            for split in transaction.splits
        ]
    }


@bp.route("/budget")
def budget():
    month = parse_month(request.args.get("month"))
    record = MonthRecord.query.filter_by(month=month).first()
    items = BudgetItem.query.filter_by(month=month).filter(BudgetItem.deleted_at.is_(None)).order_by(
        BudgetItem.due_date
    ).all()
    all_history = [
        history_record
        for history_record in MonthRecord.query.order_by(MonthRecord.month.desc()).all()
        if history_record.month != month
    ]
    recent = all_history[:3]
    older = all_history[3:]
    available_transactions = Transaction.query.filter_by(budget_month=month).filter(
        Transaction.deleted_at.is_(None)
    ).order_by(Transaction.bank_date.desc()).all()
    available_matches = []
    for transaction in available_transactions:
        available_matches.append(
            {
                "value": f"transaction:{transaction.id}",
                "label": f"{transaction.bank_date:%m-%d} · {transaction.display_description} · {currency(transaction.amount)}",
                "date": transaction.bank_date,
                "description": transaction.display_description,
                "amount": Decimal(transaction.amount),
                "selected_for": [
                    item.id for item in items if item.transaction_id == transaction.id
                ],
            }
        )
        for split in transaction.splits:
            available_matches.append(
                {
                    "value": f"split:{split.id}",
                    "label": f"{transaction.bank_date:%m-%d} · {split.description} (split) · {currency(split.amount)}",
                    "date": transaction.bank_date,
                    "description": split.description,
                    "amount": Decimal(split.amount),
                    "selected_for": [
                        item.id for item in items if item.transaction_split_id == split.id
                    ],
                }
            )
    budget_matches = {}
    for item in items:
        item_description = item.description.casefold()

        def match_score(match):
            match_description = match["description"].casefold()
            description_score = 3 if match_description == item_description else 0
            if not description_score and (
                match_description in item_description or item_description in match_description
            ):
                description_score = 1
            return (
                (5 if match["amount"] == Decimal(item.amount) else 0)
                + (2 if match["date"].day == item.due_date.day else 0)
                + description_score
            )

        ranked = sorted(available_matches, key=match_score, reverse=True)
        budget_matches[item.id] = [
            {
                **match,
                "suggested": match_score(match) >= 7,
            }
            for match in ranked
        ]
    history_summaries = [
        {"record": history_record, "totals": budget_type_totals(history_record.month)}
        for history_record in recent
    ]
    return render_template(
        "budget.html",
        selected_month=month,
        record=record,
        items=items,
        totals=budget_totals(month),
        recent=recent,
        older=older,
        budget_matches=budget_matches,
        history_summaries=history_summaries,
    )


@bp.post("/budget/add")
def add_budget_item():
    month = parse_month(request.form.get("month"))
    record = MonthRecord.query.filter_by(month=month).first()
    if record and record.closed:
        abort(409, "Closed months are read-only.")
    try:
        amount = form_decimal("amount")
        due_date = datetime.strptime(request.form["due_date"], "%Y-%m-%d").date()
        require_date_in_month(due_date, month)
        description = request.form["description"].strip()
        if not description:
            raise ValueError("Description is required.")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.budget", month=month.strftime("%Y-%m")))
    db.session.add(
        BudgetItem(
            month=month,
            due_date=due_date,
            description=description,
            amount=amount,
            transaction_type=request.form.get("transaction_type") or None,
            parent_category=request.form.get("parent_category") or None,
            subcategory=request.form.get("subcategory") or None,
            is_reimbursement=request.form.get("is_reimbursement") == "on",
        )
    )
    db.session.commit()
    flash("Budget item added.", "success")
    return redirect(url_for("main.budget", month=month.strftime("%Y-%m")))


@bp.post("/budget/<int:item_id>/edit")
def edit_budget_item(item_id):
    item = db.get_or_404(BudgetItem, item_id)
    record = MonthRecord.query.filter_by(month=item.month).first()
    if record and record.closed:
        abort(409, "Closed months are read-only.")
    try:
        item.amount = form_decimal("amount")
        item.due_date = datetime.strptime(request.form["due_date"], "%Y-%m-%d").date()
        require_date_in_month(item.due_date, item.month)
        description = request.form["description"].strip()
        if not description:
            raise ValueError("Description is required.")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.budget", month=item.month.strftime("%Y-%m")))
    item.description = description
    item.transaction_type = request.form.get("transaction_type") or None
    item.parent_category = request.form.get("parent_category") or None
    item.subcategory = request.form.get("subcategory") or None
    item.is_reimbursement = request.form.get("is_reimbursement") == "on"
    if item.recurring_template:
        template = item.recurring_template
        template.description = item.description
        template.amount = item.amount
        template.day_of_month = item.due_date.day
        template.transaction_type = item.transaction_type
        template.parent_category = item.parent_category
        template.subcategory = item.subcategory
        template.is_reimbursement = item.is_reimbursement
    db.session.commit()
    flash("Budget item updated.", "success")
    return redirect(url_for("main.budget", month=item.month.strftime("%Y-%m")))


@bp.post("/budget/<int:item_id>/paid")
def mark_budget_paid(item_id):
    item = db.get_or_404(BudgetItem, item_id)
    record = MonthRecord.query.filter_by(month=item.month).first()
    if record and record.closed:
        abort(409, "Closed months are read-only.")
    item.paid = request.form.get("paid") == "true"
    match_value = request.form.get("transaction_match", "")
    if item.paid and match_value:
        try:
            match_type, raw_match_id = match_value.split(":", 1)
            match_id = int(raw_match_id)
        except (ValueError, TypeError):
            return {"error": "Transaction match is invalid."}, 400
        if match_type not in {"transaction", "split"}:
            return {"error": "Transaction match is invalid."}, 400
        if match_type == "split":
            split = db.get_or_404(TransactionSplit, match_id)
            item.transaction_id = None
            item.transaction_split_id = split.id
            item.actual_amount = split.amount
        else:
            transaction = db.get_or_404(Transaction, match_id)
            item.transaction_id = transaction.id
            item.transaction_split_id = None
            item.actual_amount = transaction.amount
        if item.recurring_template:
            item.recurring_template.amount = item.actual_amount
    elif not item.paid:
        item.transaction_id = None
        item.transaction_split_id = None
        item.actual_amount = None
    db.session.commit()
    return {"ok": True}


@bp.post("/budget/<int:item_id>/delete")
def delete_budget_item(item_id):
    item = db.get_or_404(BudgetItem, item_id)
    record = MonthRecord.query.filter_by(month=item.month).first()
    if record and record.closed:
        abort(409, "Closed months are read-only.")
    item.deleted_at = datetime.now()
    if item.recurring_template:
        item.recurring_template.active = False
    db.session.commit()
    flash("Budget item removed from this and future months.", "success")
    return redirect(url_for("main.budget", month=item.month.strftime("%Y-%m")))


@bp.route("/admin")
def admin():
    batches = ImportBatch.query.order_by(ImportBatch.imported_at.desc()).all()
    checkpoints = BalanceCheckpoint.query.order_by(BalanceCheckpoint.created_at.desc()).all()
    return render_template(
        "admin.html",
        batches=batches,
        checkpoints=checkpoints,
        current_balance=current_balance(),
        needs_initial_balance=not bool(checkpoints),
    )


@bp.get("/admin/categories")
def manage_categories():
    categories = Category.query.order_by(
        Category.transaction_type, Category.parent, Category.subcategory
    ).all()
    grouped = {}
    for category in categories:
        grouped.setdefault(category.transaction_type, {}).setdefault(category.parent, []).append(
            category
        )
    return render_template(
        "categories.html",
        grouped_categories=grouped,
        categories=categories,
        reporting_groups=REPORTING_GROUPS,
    )


@bp.post("/admin/categories/add")
def add_category():
    try:
        transaction_type = category_name(request.form.get("transaction_type"), "Type", 40)
        parent = category_name(request.form.get("parent"), "Parent", 80)
        subcategory = category_name(request.form.get("subcategory"), "Subcategory", 80)
        reporting_group = request.form.get("reporting_group")
        if reporting_group not in REPORTING_GROUPS:
            raise ValueError("Reporting group is invalid.")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.manage_categories"))
    exists = Category.query.filter(
        func.lower(Category.transaction_type) == transaction_type.casefold(),
        func.lower(Category.parent) == parent.casefold(),
        func.lower(Category.subcategory) == subcategory.casefold(),
    ).first()
    if exists:
        flash("That category already exists.", "error")
        return redirect(url_for("main.manage_categories"))
    category = Category(
        transaction_type=transaction_type,
        parent=parent,
        subcategory=subcategory,
    )
    category.profile = CategoryProfile(reporting_group=reporting_group)
    db.session.add(category)
    db.session.commit()
    flash("Category added.", "success")
    return redirect(url_for("main.manage_categories"))


@bp.post("/admin/categories/rename")
def rename_category():
    level = request.form.get("level")
    if level not in {"type", "parent", "subcategory"}:
        abort(400)
    transaction_type = request.form.get("transaction_type", "")
    parent = request.form.get("parent", "")
    subcategory = request.form.get("subcategory", "")
    maximum = 40 if level == "type" else 80
    try:
        new_name = category_name(request.form.get("new_name"), level.title(), maximum)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.manage_categories"))
    source = category_scope(level, transaction_type, parent, subcategory).all()
    if not source:
        abort(404)
    if level == "type":
        collision = any(
            category.transaction_type.casefold() == new_name.casefold()
            and category.transaction_type.casefold() != transaction_type.casefold()
            for category in Category.query.all()
        )
    elif level == "parent":
        collision = any(
            category.transaction_type == transaction_type
            and category.parent.casefold() == new_name.casefold()
            and category.parent.casefold() != parent.casefold()
            for category in Category.query.all()
        )
    else:
        collision = any(
            category.transaction_type == transaction_type
            and category.parent == parent
            and category.subcategory.casefold() == new_name.casefold()
            and category.subcategory.casefold() != subcategory.casefold()
            for category in Category.query.all()
        )
    if collision:
        flash(f"A {level} with that name already exists in this group.", "error")
        return redirect(url_for("main.manage_categories"))
    for model in CATEGORIZED_MODELS:
        usage = category_usage_scope(model, level, transaction_type, parent, subcategory)
        column = {
            "type": model.transaction_type,
            "parent": model.parent_category,
            "subcategory": model.subcategory,
        }[level]
        usage.update({column: new_name}, synchronize_session=False)
    for category in source:
        setattr(
            category,
            {"type": "transaction_type", "parent": "parent", "subcategory": "subcategory"}[
                level
            ],
            new_name,
        )
    db.session.commit()
    flash(f"{level.title()} renamed everywhere it is used.", "success")
    return redirect(url_for("main.manage_categories"))


@bp.post("/admin/categories/reporting-group")
def update_reporting_group():
    category = db.get_or_404(Category, request.form.get("category_id", type=int))
    reporting_group = request.form.get("reporting_group")
    if reporting_group not in REPORTING_GROUPS:
        abort(400)
    category.profile.reporting_group = reporting_group
    db.session.commit()
    flash("Reporting group updated.", "success")
    return redirect(url_for("main.manage_categories"))


@bp.post("/admin/categories/delete")
def delete_category():
    level = request.form.get("level")
    if level not in {"type", "parent", "subcategory"}:
        abort(400)
    transaction_type = request.form.get("transaction_type", "")
    parent = request.form.get("parent", "")
    subcategory = request.form.get("subcategory", "")
    source = category_scope(level, transaction_type, parent, subcategory).all()
    if not source:
        abort(404)
    replacement = db.get_or_404(Category, request.form.get("replacement_id", type=int))
    if replacement.id in {category.id for category in source}:
        flash("Choose a replacement outside the category being deleted.", "error")
        return redirect(url_for("main.manage_categories"))
    updated = 0
    values = {
        "transaction_type": replacement.transaction_type,
        "parent_category": replacement.parent,
        "subcategory": replacement.subcategory,
    }
    for model in CATEGORIZED_MODELS:
        updated += category_usage_scope(
            model, level, transaction_type, parent, subcategory
        ).update(
            {
                model.transaction_type: values["transaction_type"],
                model.parent_category: values["parent_category"],
                model.subcategory: values["subcategory"],
            },
            synchronize_session=False,
        )
    for category in source:
        db.session.delete(category)
    db.session.commit()
    flash(f"Category deleted; reassigned {updated} existing record(s).", "success")
    return redirect(url_for("main.manage_categories"))


@bp.post("/admin/import/preview")
def import_preview():
    upload = request.files.get("csv_file")
    if not upload or not upload.filename:
        flash("Choose a CSV file.", "error")
        return redirect(url_for("main.admin"))
    try:
        rows = parse_csv_upload(upload.read())
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.admin"))
    for row in rows:
        row["duplicate"] = row["duplicate_in_file"] or duplicate_exists(row)
        row["display_date"] = date.fromisoformat(row["bank_date"]).strftime("%m-%d-%Y")
    token = uuid.uuid4().hex
    payload = {"filename": upload.filename, "rows": rows}
    preview_path = Path(current_app.instance_path, "import_previews", f"{token}.json")
    preview_path.write_text(json.dumps(payload), encoding="utf-8")
    return render_template(
        "import_preview.html",
        token=token,
        filename=upload.filename,
        rows=rows,
        needs_initial_balance=BalanceCheckpoint.query.first() is None,
    )


@bp.post("/admin/import/confirm")
def import_confirm():
    token = request.form.get("token", "")
    if not token.isalnum():
        abort(400)
    preview_path = Path(current_app.instance_path, "import_previews", f"{token}.json")
    if not preview_path.exists():
        flash("That import preview expired. Upload the file again.", "error")
        return redirect(url_for("main.admin"))
    payload = json.loads(preview_path.read_text(encoding="utf-8"))
    batch = ImportBatch(filename=payload["filename"])
    db.session.add(batch)
    db.session.flush()
    imported = 0
    duplicates = 0
    current = month_start()
    inherited_settings = {}
    existing_transactions = Transaction.query.filter(
        Transaction.deleted_at.is_(None)
    ).order_by(Transaction.bank_date.desc(), Transaction.id.desc())
    for existing in existing_transactions:
        key = match_text(existing.bank_description)
        has_settings = any(
            (
                existing.custom_description,
                existing.transaction_type,
                existing.parent_category,
                existing.subcategory,
                existing.is_recurring,
            )
        )
        if key and has_settings and key not in inherited_settings:
            inherited_settings[key] = existing
    for row in payload["rows"]:
        if row["duplicate"] or duplicate_exists(row):
            duplicates += 1
            continue
        bank_date = date.fromisoformat(row["bank_date"])
        row_month = month_start(bank_date)
        month_record = MonthRecord.query.filter_by(month=row_month).first()
        closed = month_record.closed if month_record else row_month < current
        if not month_record:
            db.session.add(MonthRecord(month=row_month, closed=closed))
        inherited = inherited_settings.get(match_text(row["description"]))
        db.session.add(
            Transaction(
                bank_date=bank_date,
                budget_month=row_month,
                amount=Decimal(row["amount"]),
                bank_description=row["description"],
                custom_description=inherited.custom_description if inherited else None,
                transaction_type=inherited.transaction_type if inherited else None,
                parent_category=inherited.parent_category if inherited else None,
                subcategory=inherited.subcategory if inherited else None,
                is_recurring=inherited.is_recurring if inherited else False,
                import_batch_id=batch.id,
            )
        )
        imported += 1
    db.session.flush()
    batch.imported_count = imported
    batch.duplicate_count = duplicates
    if BalanceCheckpoint.query.first() is None:
        try:
            initial_balance = form_decimal("initial_balance")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("main.admin"))
        max_id = db.session.query(func.max(Transaction.id)).scalar() or 0
        db.session.add(BalanceCheckpoint(balance=initial_balance, transaction_cutoff_id=max_id))
    db.session.commit()
    preview_path.unlink(missing_ok=True)
    flash(f"Imported {imported} transaction(s); discarded {duplicates} duplicate(s).", "success")
    return redirect(url_for("main.transactions"))


@bp.post("/admin/balance")
def reset_balance():
    try:
        entered = form_decimal("balance")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.admin"))
    calculated = current_balance()
    max_id = db.session.query(func.max(Transaction.id)).scalar() or 0
    db.session.add(
        BalanceCheckpoint(
            balance=entered,
            transaction_cutoff_id=max_id,
            calculated_before_reset=calculated,
            discrepancy=entered - calculated if calculated is not None else None,
        )
    )
    db.session.commit()
    flash("Balance checkpoint saved.", "success")
    return redirect(url_for("main.admin"))


@bp.get("/admin/backup")
def backup_database():
    database = Path(db.engine.url.database)
    with tempfile.NamedTemporaryFile(suffix=".db") as temporary:
        with sqlite3.connect(database) as source, sqlite3.connect(temporary.name) as destination:
            source.backup(destination)
        backup = io.BytesIO(Path(temporary.name).read_bytes())
    return send_file(
        backup,
        as_attachment=True,
        download_name=f"personal-finance-{date.today()}.db",
        mimetype="application/vnd.sqlite3",
    )


@bp.get("/admin/export/transactions")
def export_transactions():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Amount", "Custom Description", "Bank Description", "Type", "Parent", "Subcategory"])
    for transaction in Transaction.query.filter(Transaction.deleted_at.is_(None)).order_by(Transaction.bank_date):
        writer.writerow(
            [
                transaction.bank_date.strftime("%m-%d-%Y"),
                transaction.amount,
                transaction.display_description,
                transaction.bank_description,
                transaction.transaction_type or "",
                transaction.parent_category or "",
                transaction.subcategory or "",
            ]
        )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


@bp.get("/admin/export/budget")
def export_budget():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Month", "Due Date", "Description", "Amount", "Paid", "Actual"])
    for item in BudgetItem.query.filter(BudgetItem.deleted_at.is_(None)).order_by(BudgetItem.month, BudgetItem.due_date):
        writer.writerow([item.month.strftime("%Y-%m"), item.due_date, item.description, item.amount, item.paid, item.actual_amount or ""])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=budgets.csv"},
    )
