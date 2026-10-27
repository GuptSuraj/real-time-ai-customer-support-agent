"""Shared, enforced demo policy values; retrieval never grants business authority."""

RETURN_WINDOW_DAYS = 30
STANDARD_SHIPPING_DAYS = (3, 5)
ACTION_TTL_SECONDS = 300
CHALLENGE_TTL_SECONDS = 120
HANDOFF_TIMEOUT_SECONDS = 60


def policy_contract():
    return {
        "return_window_days": RETURN_WINDOW_DAYS,
        "standard_shipping_business_days": list(STANDARD_SHIPPING_DAYS),
        "return_scope": "whole_order",
        "return_prerequisites": [
            "delivered",
            "within_window",
            "all_products_returnable",
            "no_existing_return",
        ],
        "refund_requires_received_return": True,
        "refund_requires_human_approval": True,
        "payments": "simulated",
        "action_confirmation": "authenticated_portal_with_one_use_verification",
        "action_ttl_seconds": ACTION_TTL_SECONDS,
        "challenge_ttl_seconds": CHALLENGE_TTL_SECONDS,
        "handoff_timeout_seconds": HANDOFF_TIMEOUT_SECONDS,
        "unsupported_tools": [
            "exchange",
            "partial_return",
            "cancel_order",
            "change_address",
            "express_shipping",
            "stock_lookup",
        ],
    }
