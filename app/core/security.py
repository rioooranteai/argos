"""Kebijakan akses: domain Google Workspace & admin (DESIGN_GROUP_A.md §6.8)."""
from __future__ import annotations

from typing import Any

from app.core.config import Secrets, secrets
from app.core.errors import PermissionDenied

# Mode Gmail pribadi (testing/portofolio): ALLOWED_GOOGLE_DOMAIN=gmail.com.
# Aman memakai akhiran email karena hanya Google yang bisa membuat alamat @gmail.com.
GMAIL_DOMAIN = "gmail.com"


def verify_google_identity(userinfo: dict[str, Any], policy: Secrets = secrets) -> None:
    """Tolak login dari luar domain yang diizinkan.

    - Domain perusahaan: memakai klaim `hd` (hanya ada pada akun Google Workspace
      yang domainnya terverifikasi), BUKAN akhiran email — akhiran email bisa dari
      akun pribadi.
    - ``gmail.com``: semua akun Gmail pribadi yang terverifikasi (tanpa klaim `hd`).
    """
    if userinfo.get("email_verified") is not True:
        raise PermissionDenied("Email Google belum terverifikasi.", code="EMAIL_NOT_VERIFIED")

    hosted_domain = str(userinfo.get("hd") or "").strip().lower()
    if policy.allowed_domain == GMAIL_DOMAIN:
        email = str(userinfo.get("email") or "").strip().lower()
        if hosted_domain or not email.endswith("@" + GMAIL_DOMAIN):
            raise PermissionDenied("Gunakan akun Gmail untuk masuk.", code="DOMAIN_NOT_ALLOWED")
        return

    if not hosted_domain or hosted_domain != policy.allowed_domain:
        raise PermissionDenied(
            "Gunakan akun Google perusahaan untuk masuk.", code="DOMAIN_NOT_ALLOWED"
        )


def is_admin(email: str, policy: Secrets = secrets) -> bool:
    return bool(policy.admin_email) and email.strip().lower() == policy.admin_email
