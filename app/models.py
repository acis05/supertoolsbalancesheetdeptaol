from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="USER")  # USER / ADMIN
    status: Mapped[str] = mapped_column(String(20), default="TRIAL")  # TRIAL/ACTIVE/SUSPENDED/EXPIRED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subscription_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subscription_ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    oauth: Mapped["OAuthCredential | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    databases: Mapped[list["AccurateDatabase"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str] = mapped_column(Text, default="")
    token_type: Mapped[str] = mapped_column(String(30), default="bearer")
    scope: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    aol_user_email: Mapped[str] = mapped_column(String(255), default="")
    aol_user_name: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="oauth")


class AccurateDatabase(Base):
    __tablename__ = "accurate_databases"
    __table_args__ = (UniqueConstraint("user_id", "accurate_db_id", name="uq_user_accurate_db"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    accurate_db_id: Mapped[int] = mapped_column(Integer)
    alias: Mapped[str] = mapped_column(String(255))
    host: Mapped[str] = mapped_column(String(255), default="")
    session_enc: Mapped[str] = mapped_column(Text, default="")
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="databases")


class GLAccount(Base):
    __tablename__ = "gl_accounts"
    __table_args__ = (UniqueConstraint("database_id", "account_no", name="uq_db_account_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    database_id: Mapped[int] = mapped_column(ForeignKey("accurate_databases.id", ondelete="CASCADE"), index=True)
    accurate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_no: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    account_type: Mapped[str] = mapped_column(String(60), default="")
    parent_no: Mapped[str] = mapped_column(String(100), default="")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("database_id", "accurate_id", name="uq_db_department_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    database_id: Mapped[int] = mapped_column(ForeignKey("accurate_databases.id", ondelete="CASCADE"), index=True)
    accurate_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("database_id", "project_no", name="uq_db_project_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    database_id: Mapped[int] = mapped_column(ForeignKey("accurate_databases.id", ondelete="CASCADE"), index=True)
    accurate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_no: Mapped[str] = mapped_column(String(100), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)


class JournalHeader(Base):
    __tablename__ = "journal_headers"
    __table_args__ = (UniqueConstraint("database_id", "accurate_id", name="uq_db_journal_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    database_id: Mapped[int] = mapped_column(ForeignKey("accurate_databases.id", ondelete="CASCADE"), index=True)
    accurate_id: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(120), default="")
    trans_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    branch_name: Mapped[str] = mapped_column(String(255), default="")
    last_update: Mapped[str] = mapped_column(String(60), default="")


class JournalLine(Base):
    __tablename__ = "journal_lines"
    __table_args__ = (UniqueConstraint("database_id", "journal_accurate_id", "line_accurate_id", name="uq_db_journal_line"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    database_id: Mapped[int] = mapped_column(ForeignKey("accurate_databases.id", ondelete="CASCADE"), index=True)
    journal_accurate_id: Mapped[int] = mapped_column(Integer, index=True)
    line_accurate_id: Mapped[int] = mapped_column(Integer)
    account_no: Mapped[str] = mapped_column(String(100), index=True)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    amount_type: Mapped[str] = mapped_column(String(20), default="")
    debit: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    credit: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    department_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    project_no: Mapped[str] = mapped_column(String(100), default="", index=True)
    memo: Mapped[str] = mapped_column(Text, default="")


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    database_id: Mapped[int] = mapped_column(ForeignKey("accurate_databases.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
