"""Idempotent demo fixtures. Never seeds unless explicitly invoked."""

import time
from sqlalchemy import select
from .business_rules import RETURN_WINDOW_DAYS, STANDARD_SHIPPING_DAYS
from .config import settings
from .db import SessionLocal
from .models import Customer, Order, OrderItem, Policy, Product, Refund, Return, Ticket, User
from .security import passwords


def seed(db):
    if db.scalar(select(User).limit(1)):
        return None
    password = "Demo-support-2026!"
    users = [
        User(
            id="user-aarav",
            email="aarav@example.com",
            name="Aarav Sharma",
            role="customer",
            password_hash=passwords.hash(password),
        ),
        User(
            id="user-meera",
            email="meera@example.com",
            name="Meera Kapoor",
            role="customer",
            password_hash=passwords.hash(password),
        ),
        User(
            id="user-staff",
            email="support@example.com",
            name="Priya · Support",
            role="staff",
            password_hash=passwords.hash(password),
        ),
        User(
            id="user-staff2",
            email="support2@example.com",
            name="Kabir · Support",
            role="staff",
            password_hash=passwords.hash(password),
        ),
    ]
    for i, name in enumerate(["Sia Patel", "Ishaan Rao", "Rohan Das"], start=1):
        users.append(
            User(
                id=f"user-sim{i}",
                email=f"sim{i}@example.com",
                name=name,
                role="customer",
                password_hash=passwords.hash(password),
            )
        )
    db.add_all(users)
    db.flush()
    db.add_all(
        [
            Customer(id="cust-aarav", user_id=users[0].id),
            Customer(id="cust-meera", user_id=users[1].id, preferred_language="hi"),
        ]
    )
    for i in range(1, 4):
        db.add(Customer(id=f"cust-sim{i}", user_id=f"user-sim{i}"))
    products = [
        Product(
            id="prod-headphones",
            name="Studio Wireless Headphones",
            description="40-hour battery, USB-C charging, active noise cancellation. Available in charcoal.",
            price_paise=499900,
        ),
        Product(
            id="prod-speaker",
            name="Pocket Bluetooth Speaker",
            description="Water-resistant portable speaker. 12-hour playback. USB-C charging.",
            price_paise=249900,
        ),
        Product(
            id="prod-earbuds",
            name="Everyday Earbuds",
            description="In-ear audio product. Non-returnable for hygiene unless defective; contact human support for exceptions.",
            price_paise=199900,
            returnable=False,
        ),
    ]
    db.add_all(products)
    db.flush()
    fixtures = [
        ("ORD-1001", "cust-aarav", "prod-headphones", "delivered", 12),
        ("ORD-1002", "cust-aarav", "prod-speaker", "shipped", None),
        ("ORD-1003", "cust-aarav", "prod-speaker", "delivered", 8),
        ("ORD-1004", "cust-aarav", "prod-headphones", "delivered", 45),
        ("ORD-1005", "cust-aarav", "prod-earbuds", "delivered", 2),
        ("ORD-1006", "cust-aarav", "prod-speaker", "delivered", 15),
        ("ORD-1007", "cust-aarav", "prod-headphones", "delivered", 10),
        ("ORD-2001", "cust-meera", "prod-headphones", "delivered", 5),
    ]
    by_id = {p.id: p for p in products}
    for oid, cid, pid, status, days in fixtures:
        db.add(
            Order(
                id=oid,
                customer_id=cid,
                status=status,
                delivered_at=time.time() - days * 86400 if days else None,
                total_paise=by_id[pid].price_paise,
            )
        )
        db.flush()
        db.add(OrderItem(order_id=oid, product_id=pid))
    db.flush()
    for oid in ["ORD-1001", "ORD-1006", "ORD-1007"]:
        db.add(
            Return(
                id="ret-" + oid,
                order_id=oid,
                status="received",
                reason="Demo returned item",
                created_at=time.time() - 5 * 86400,
            )
        )
    db.flush()
    db.add_all(
        [
            Refund(
                id="refund-processing",
                order_id="ORD-1001",
                amount_paise=499900,
                status="processing",
                reason="Headphones returned five days ago",
                decided_by="user-staff",
                decision_reason="Return inspected",
                processing_at=None,
            ),
            Refund(
                id="refund-failed",
                order_id="ORD-1006",
                amount_paise=249900,
                status="failed",
                reason="Bank simulation failure",
                decided_by="user-staff",
                decision_reason="Approved earlier",
            ),
        ]
    )
    db.add(
        Ticket(
            id="ticket-demo",
            customer_id="cust-aarav",
            title="Delivery update",
            description="Please check shipping progress for ORD-1002.",
        )
    )
    db.add_all(
        [
            Policy(
                id="policy-returns",
                title="Returns and eligibility",
                body=f"Whole-order returns are available within {RETURN_WINDOW_DAYS} days of delivery for returnable products. Earbuds are non-returnable for hygiene. Defective non-returnable items and partial-order returns require human review. A received return is required for a refund request.",
            ),
            Policy(
                id="policy-refunds",
                title="Refunds and processing",
                body="Every refund requires a human representative's approval. Once approved and processed, banks may take 5–7 business days to reflect funds. Never promise a specific payment date. Failed or overdue refunds should be escalated. All payments in this application are simulated.",
            ),
            Policy(
                id="policy-shipping",
                title="Shipping and support",
                body=f"Standard delivery usually takes {STANDARD_SHIPPING_DAYS[0]}–{STANDARD_SHIPPING_DAYS[1]} business days. Check the order record for its current status. Support can create a confirmed ticket or connect a human representative. Do not invent tracking numbers or delivery dates.",
            ),
            Policy(
                id="policy-privacy",
                title="Identity and confirmation",
                body="Customer data is scoped to the authenticated account. Sensitive actions require an on-screen identity challenge and confirmation of the exact proposed action. Verification is consumed by one action. Never request payment card details, passwords, or spoken verification codes.",
            ),
        ]
    )
    db.commit()
    return password


if __name__ == "__main__":
    if not settings().demo_mode:
        raise SystemExit("Seeding is only allowed in DEMO_MODE")
    with SessionLocal() as db:
        result = seed(db)
        print(
            "Demo fixtures created. See README for credentials."
            if result
            else "Database already seeded; no changes."
        )
