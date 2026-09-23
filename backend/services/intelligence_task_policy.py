"""Pure routing and review policies for generated intelligence tasks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_OWNER_ROLES = {
    "contracts": ["legal_counsel", "account_manager", "procurement_lead"],
    "compliance": ["compliance_officer", "security_lead", "risk_manager"],
    "meetings": ["project_manager", "team_lead"],
    "triage": ["manager", "operations_manager"],
    "manager_triage": ["manager", "operations_manager"],
}
_REVIEWER_ROLES = {
    "contracts": ["legal_reviewer", "finance_controller"],
    "compliance": ["compliance_reviewer", "security_reviewer"],
    "meetings": ["project_reviewer", "operations_reviewer"],
    "triage": ["manager_reviewer"],
    "manager_triage": ["operations_director"],
}
_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)


def suggested_owner_roles(*, queue_name: str, task_type: str) -> list[str]:
    if "compliance" in task_type:
        return list(_OWNER_ROLES["compliance"])
    if "contract" in task_type:
        return list(_OWNER_ROLES["contracts"])
    return list(_OWNER_ROLES.get(queue_name, ["manager"]))


def suggested_reviewer_roles(*, queue_name: str, task_type: str) -> list[str]:
    if "compliance" in task_type:
        return list(_REVIEWER_ROLES["compliance"])
    if "contract" in task_type:
        return list(_REVIEWER_ROLES["contracts"])
    return list(_REVIEWER_ROLES.get(queue_name, ["manager_reviewer"]))


def acceptance_criteria(
    *, task_type: str, review_status: str
) -> list[dict[str, object]]:
    return [
        {
            "key": "source_verified",
            "label": "Verify source excerpt and citation context",
            "required": True,
            "completed": False,
        },
        {
            "key": "owner_assigned",
            "label": "Assign owner",
            "required": True,
            "completed": False,
        },
        {
            "key": "reviewer_assigned",
            "label": "Assign reviewer",
            "required": review_status != "suggested",
            "completed": False,
        },
        {
            "key": "due_date_confirmed",
            "label": "Confirm due date or explicitly mark none",
            "required": "deadline" in task_type or "action" in task_type,
            "completed": False,
        },
    ]


def task_title_from_excerpt(excerpt: str, *, prefix: str) -> str:
    cleaned = " ".join(excerpt.split()).strip(" .")
    if len(cleaned) <= 90:
        return f"{prefix}: {cleaned}"
    return f"{prefix}: {cleaned[:87].rstrip()}..."


def parse_task_date(raw_value: str) -> datetime | None:
    value = raw_value.strip()
    if not value:
        return None
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def priority_for_due_at(due_at: datetime | None) -> str:
    if due_at is None:
        return "normal"
    if due_at <= datetime.now(UTC) + timedelta(days=14):
        return "high"
    return "normal"
