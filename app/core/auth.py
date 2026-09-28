from __future__ import annotations
from datetime import datetime
from fastapi import Request
from sqlalchemy.orm import Session
from app.models import User


def refresh_user_status(user: User, db: Session) -> User:
    now = datetime.utcnow()
    if user.status == "TRIAL" and user.trial_ends_at and user.trial_ends_at < now:
        user.status = "EXPIRED"
        db.commit()
    if user.status == "ACTIVE" and user.subscription_ends_at and user.subscription_ends_at < now:
        user.status = "EXPIRED"
        db.commit()
    return user


def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = db.get(User, int(uid))
    if not user:
        request.session.clear()
        return None
    return refresh_user_status(user, db)


def is_admin(user: User | None) -> bool:
    return bool(user and user.role == "ADMIN")


def can_use_app(user: User) -> bool:
    return user.role == "ADMIN" or user.status in {"TRIAL", "ACTIVE"}


def is_trial(user: User) -> bool:
    return user.role != "ADMIN" and user.status == "TRIAL"
