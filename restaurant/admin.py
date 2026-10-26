"""The restaurant uses its role-checked Billing screens, not Django admin actions.

Models are deliberately not registered here. This avoids an alternate UI that
could bypass worker-only status changes or the cash ledger services.
"""
