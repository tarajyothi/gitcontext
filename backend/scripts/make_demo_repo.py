"""Create a small local git repository used by the Day-6 demo (fake credentials + a hostile symlink).
Credentials are assembled from fragments so no complete token-shaped string is committed to this project."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
FAKE = {"aws": "AKIA" + "IOSFODNN7EXAMPLE", "gh": "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", "stripe": "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"}
KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA0fakefakefakefakefake\nZm9vYmFyYmF6cXV4\n-----END RSA PRIVATE KEY-----"
files = {
    "README.md": "# payments-service\n\nSmall internal service that charges customers, issues refunds and signs users in.\n",
    "app/__init__.py": "",
    "app/billing.py": '"""Billing: charge customers and refund payments."""\n\n\ndef charge_customer(customer_id, amount_cents):\n    """Charge the customer\'s saved card for the given amount."""\n    if amount_cents <= 0:\n        raise ValueError("amount must be positive")\n    return {"customer": customer_id, "charged": amount_cents}\n\n\ndef refund_payment(payment_id, reason="requested_by_customer"):\n    """Refund a previous payment back to the customer."""\n    return {"payment": payment_id, "refunded": True, "reason": reason}\n',
    "app/auth.py": '"""Authentication helpers."""\nimport hashlib\n\n\ndef hash_password(password, salt):\n    """Return a salted sha256 digest of the password."""\n    return hashlib.sha256((salt + password).encode()).hexdigest()\n\n\ndef login_user(username, password, store):\n    """Check the credentials and create a session for the user."""\n    user = store.get(username)\n    if user is None or user["hash"] != hash_password(password, user["salt"]):\n        raise PermissionError("invalid credentials")\n    return {"user": username, "session": "token"}\n',
    "app/config.py": f'"""Runtime configuration (this file accidentally contains real-looking credentials)."""\n\nAWS_ACCESS_KEY_ID = "{FAKE["aws"]}"\nGITHUB_TOKEN = "{FAKE["gh"]}"\nSTRIPE_SECRET_KEY = "{FAKE["stripe"]}"\n\n\ndef database_url():\n    """Build the database connection string."""\n    return "postgresql://app@db/payments"\n',
    "deploy/keys.py": f'"""Deployment helpers."""\n\nSIGNING_KEY = """\n{KEY}\n"""\n\n\ndef rotate_keys():\n    """Rotate the signing keys."""\n    return True\n',
    "tests/test_billing.py": "from app.billing import charge_customer\n\n\ndef test_charge_customer_rejects_zero():\n    # charging zero must fail\n    charge_customer('c1', 0)\n",
    "docs/guide.md": "# Billing guide\n\nCustomers are charged with charge_customer and refunded with refund_payment.\n",
}


def git(*a):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=demo", "-c", "user.email=demo@example.com", *a], check=True, capture_output=True)


root.mkdir(parents=True, exist_ok=True)
subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
for p, c in files.items():
    (root / p).parent.mkdir(parents=True, exist_ok=True)
    (root / p).write_text(c)
os.symlink("/etc/passwd", root / "etc_passwd.py")  # hostile symlink: must never be read
git("add", "-A")
git("commit", "-qm", "initial commit")
print("fixture ready:", root, len(files) + 1, "entries incl. symlink")
