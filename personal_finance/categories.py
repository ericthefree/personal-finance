CATEGORY_TREE = {
    "Income": {
        "Employment": ["Salary", "Bonus", "Commission"],
        "Business": ["Sales", "Services", "Consulting"],
        "Investments": ["Dividends", "Interest", "Capital Gains"],
        "Other": ["Gifts", "Refunds", "Miscellaneous"],
    },
    "Bills": {
        "Housing": ["Rent/Mortgage", "Property Tax", "HOA Fees", "Insurance"],
        "Utilities": ["Electric", "Gas", "Water", "Internet", "Phone"],
        "Insurance": ["Health", "Auto", "Life", "Home", "Legal", "Identity Theft"],
        "Subscriptions": ["Streaming", "Software", "Memberships"],
    },
    "Expenses": {
        "Food": ["Groceries", "Restaurants", "Fast Food", "Coffee", "Drinks & Snacks"],
        "Transportation": ["Gas", "Parking", "Public Transit", "Rideshare"],
        "Shopping": ["Clothing", "Electronics", "Home Goods", "Personal Care"],
        "Personal Care": ["Hair", "Beauty", "Health", "Fitness"],
        "Entertainment": ["Movies", "Events", "Hobbies", "Games"],
        "Healthcare": ["Doctor", "Pharmacy", "Dental", "Vision"],
        "Other": ["Miscellaneous"],
    },
    "Debts": {
        "Credit Cards": ["Payment", "Interest"],
        "Loans": ["Auto Loan", "Student Loan", "Personal Loan"],
        "Mortgage": ["Principal", "Interest"],
    },
    "Investments": {
        "Retirement": ["401k", "IRA", "Roth IRA"],
        "Brokerage": ["Stocks", "Bonds", "ETFs", "Mutual Funds"],
        "Savings": ["Emergency Fund", "Goal Savings"],
    },
    "Transfers": {
        "Between Accounts": ["Checking to Savings", "Savings to Checking"],
        "External": ["To Other Person", "From Other Person"],
    },
}


REPORTING_GROUPS = {
    "income": "Income",
    "expense": "Expense",
    "bill": "Bill",
    "loan": "Loan",
    "credit_card": "Credit card",
    "transfer": "Transfer / excluded",
    "other": "Other",
}


def default_reporting_group(transaction_type, parent):
    if transaction_type == "Income":
        return "income"
    if transaction_type == "Bills":
        return "bill"
    if transaction_type == "Expenses":
        return "expense"
    if transaction_type == "Debts" and parent == "Credit Cards":
        return "credit_card"
    if transaction_type == "Debts" and parent in {"Loans", "Mortgage"}:
        return "loan"
    if transaction_type == "Transfers":
        return "transfer"
    return "other"
