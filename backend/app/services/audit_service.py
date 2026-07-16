"""F15 — append-only audit log for reads/writes of sensitive health data
(clinical notes, patient notes; F24 medical history will log through here
too once it exists). Rows are never updated or deleted by application code.
"""

import uuid

from sqlmodel import Session

from app.models.audit_log import AuditLog


def log(session: Session, *, actor_user_id: uuid.UUID, action: str, resource_type: str, resource_id: uuid.UUID) -> None:
    session.add(
        AuditLog(actor_user_id=actor_user_id, action=action, resource_type=resource_type, resource_id=resource_id)
    )
    session.commit()
