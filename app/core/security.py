"""Access policy: Google Workspace domain & admin (DESIGN_GROUP_A.md §6.8)."""
from __future__ import annotations

from typing import Any

from app.core.config import Secrets, secrets
from app.core.errors import PermissionDenied

# Personal Gmail mode (testing/portfolio): ALLOWED_GOOGLE_DOMAIN=gmail.com.
# Checking the email suffix is safe here because only Google can create @gmail.com addresses.
GMAIL_DOMAIN = "gmail.com"


def verify_google_identity(userinfo: dict[str, Any], policy: Secrets = secrets) -> None:
    """Reject sign-ins from outside the allowed domain.

    - Company domain: uses the `hd` claim (present only on Google Workspace
      accounts with a verified domain), NOT the email suffix — a suffix can come
      from a personal account.
    - ``gmail.com``: any verified personal Gmail account (no `hd` claim).
    """
    if userinfo.get("email_verified") is not True:
        raise PermissionDenied("Your Google email is not verified.", code="EMAIL_NOT_VERIFIED")

    hosted_domain = str(userinfo.get("hd") or "").strip().lower()
    if policy.allowed_domain == GMAIL_DOMAIN:
        email = str(userinfo.get("email") or "").strip().lower()
        if hosted_domain or not email.endswith("@" + GMAIL_DOMAIN):
            raise PermissionDenied("Sign in with a Gmail account.", code="DOMAIN_NOT_ALLOWED")
        return

    if not hosted_domain or hosted_domain != policy.allowed_domain:
        raise PermissionDenied(
            "Sign in with your company Google account.", code="DOMAIN_NOT_ALLOWED"
        )


def is_admin(email: str, policy: Secrets = secrets) -> bool:
    return bool(policy.admin_email) and email.strip().lower() == policy.admin_email
