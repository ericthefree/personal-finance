from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, UniqueConstraint


db = SQLAlchemy()


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_type = db.Column(db.String(40), nullable=False)
    parent = db.Column(db.String(80), nullable=False)
    subcategory = db.Column(db.String(80), nullable=False)

    __table_args__ = (
        UniqueConstraint("transaction_type", "parent", "subcategory"),
    )


class ImportBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    imported_count = db.Column(db.Integer, default=0, nullable=False)
    duplicate_count = db.Column(db.Integer, default=0, nullable=False)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bank_date = db.Column(db.Date, nullable=False, index=True)
    budget_month = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    bank_description = db.Column(db.String(500), nullable=False)
    custom_description = db.Column(db.String(500))
    transaction_type = db.Column(db.String(40))
    parent_category = db.Column(db.String(80))
    subcategory = db.Column(db.String(80))
    is_recurring = db.Column(db.Boolean, default=False, nullable=False)
    is_reimbursement = db.Column(db.Boolean, default=False, nullable=False)
    reimbursement_for_id = db.Column(db.Integer, db.ForeignKey("transaction.id"))
    source = db.Column(db.String(20), default="import", nullable=False)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batch.id"))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    deleted_at = db.Column(db.DateTime)

    splits = db.relationship(
        "TransactionSplit",
        cascade="all, delete-orphan",
        backref="transaction",
        foreign_keys="TransactionSplit.transaction_id",
    )

    __table_args__ = (
        Index("ix_transaction_duplicate", "bank_date", "bank_description", "amount"),
    )

    @property
    def display_description(self):
        return self.custom_description or self.bank_description


class TransactionSplit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    transaction_type = db.Column(db.String(40))
    parent_category = db.Column(db.String(80))
    subcategory = db.Column(db.String(80))
    is_recurring = db.Column(db.Boolean, default=False, nullable=False)
    is_reimbursement = db.Column(db.Boolean, default=False, nullable=False)
    reimbursement_for_id = db.Column(db.Integer, db.ForeignKey("transaction.id"))


class RecurringTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    day_of_month = db.Column(db.Integer, nullable=False)
    anchor_month = db.Column(db.Date, nullable=False)
    interval_months = db.Column(db.Integer, default=1, nullable=False)
    transaction_type = db.Column(db.String(40))
    parent_category = db.Column(db.String(80))
    subcategory = db.Column(db.String(80))
    is_reimbursement = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_from_transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"))
    created_from_split_id = db.Column(db.Integer, db.ForeignKey("transaction_split.id"))


class MonthRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Date, unique=True, nullable=False)
    closed = db.Column(db.Boolean, default=False, nullable=False)
    ending_balance = db.Column(db.Numeric(12, 2))


class BudgetItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    transaction_type = db.Column(db.String(40))
    parent_category = db.Column(db.String(80))
    subcategory = db.Column(db.String(80))
    is_reimbursement = db.Column(db.Boolean, default=False, nullable=False)
    paid = db.Column(db.Boolean, default=False, nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transaction.id"))
    transaction_split_id = db.Column(db.Integer, db.ForeignKey("transaction_split.id"))
    actual_amount = db.Column(db.Numeric(12, 2))
    recurring_template_id = db.Column(db.Integer, db.ForeignKey("recurring_template.id"))
    deleted_at = db.Column(db.DateTime)

    recurring_template = db.relationship("RecurringTemplate")
    transaction = db.relationship("Transaction", foreign_keys=[transaction_id])
    transaction_split = db.relationship("TransactionSplit", foreign_keys=[transaction_split_id])


class BalanceCheckpoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    balance = db.Column(db.Numeric(12, 2), nullable=False)
    transaction_cutoff_id = db.Column(db.Integer, default=0, nullable=False)
    calculated_before_reset = db.Column(db.Numeric(12, 2))
    discrepancy = db.Column(db.Numeric(12, 2))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class AuditRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
