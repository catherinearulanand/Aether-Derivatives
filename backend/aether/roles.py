"""Roles and what each may do — the server-side copy.

Separation of duties is a claim this product makes, so it cannot live only in the
browser. The frontend holds the same table in ``frontend/src/lib/roles.ts`` to decide
what to render; this one decides what the API will actually answer. A test asserts the
two agree, because a permission model that drifts between the two halves of an
application is worse than none: it looks enforced and is not.

This is **prototype access control, not authentication.** There is no password, no
token and no identity provider. What is demonstrated is that the same person must not
interpret the contract, compute the margin and sign off the transfer.
"""

from __future__ import annotations

__all__ = ["ROLES", "ROLE_PERMISSIONS", "can", "permissions_of"]

#: Every permission in the system, and what it grants.
PERMISSION_LABELS: dict[str, str] = {
    "view:desk": "View exposure, margin, optimisation and the decision",
    "view:contract": "View the CSA extraction, citations and confidence",
    "act:review-contract": "Confirm a flagged clause and freeze the agreement",
    "act:approve": "Sign off a margin decision",
    "act:reconcile": "Upload ledgers and run a reconciliation",
    "view:audit": "Read the audit trail",
    "act:export-audit": "Export the audit trail",
    "view:admin": "View the workflow status board and system state",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "RISK": frozenset(
        {
            "view:desk",
            "view:contract",
            "act:approve",
            "act:reconcile",
            "view:audit",
            "act:export-audit",
        }
    ),
    "LEGAL": frozenset({"view:desk", "view:contract", "act:review-contract", "view:audit"}),
    "ADMIN": frozenset(
        {
            "view:desk",
            "view:contract",
            "act:approve",
            "act:reconcile",
            "view:audit",
            "act:export-audit",
            "view:admin",
        }
    ),
    "AUDITOR": frozenset({"view:desk", "view:contract", "view:audit", "act:export-audit"}),
}

ROLES: tuple[str, ...] = ("RISK", "LEGAL", "ADMIN", "AUDITOR")

#: What each role is accountable for, and the thing it deliberately may not do. The
#: assistant quotes these when it has to refuse, so a refusal names the person who
#: *can* act rather than simply stopping.
ROLE_MANDATES: dict[str, tuple[str, str]] = {
    "RISK": (
        "Runs the margin calculation, reviews the allocation and signs off the transfer.",
        "Cannot alter the extracted CSA terms — that is Legal's decision.",
    ),
    "LEGAL": (
        "Reviews what the Legal-Clause Agent extracted and freezes the agreement.",
        "Cannot approve a margin transfer.",
    ),
    "ADMIN": (
        "Watches the workflow across the desk and holds system state.",
        "Cannot edit an audit record. The chain is append-only.",
    ),
    "AUDITOR": (
        "Reads the decision history and verifies the hash chain.",
        "Cannot approve, reconcile or alter a term. Read-only by construction.",
    ),
}


def permissions_of(role: str | None) -> frozenset[str]:
    """Everything this role may do. An unknown or absent role holds nothing."""
    if role is None:
        return frozenset()
    return ROLE_PERMISSIONS.get(role.upper(), frozenset())


def can(role: str | None, permission: str) -> bool:
    """Whether this role holds this permission."""
    return permission in permissions_of(role)


def roles_holding(permission: str) -> tuple[str, ...]:
    """Which roles hold this permission. Used to say who *can* when refusing."""
    return tuple(role for role in ROLES if permission in ROLE_PERMISSIONS[role])
