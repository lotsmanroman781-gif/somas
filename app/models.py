"""SQLAlchemy 2.x models. Composite keys constrain every child to its owner."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_salt: Mapped[bytes] = mapped_column(LargeBinary)
    password_hash: Mapped[bytes] = mapped_column(LargeBinary)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("email = lower(trim(email))", name="normalized_email"),
    )


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    csrf: Mapped[str] = mapped_column(String(100))
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    manager_agent_id: Mapped[str] = mapped_column(String(80), default="root_manager")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    business: Mapped[dict[str, Any]] = mapped_column(JSONB)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        ForeignKeyConstraint(
            ["user_id", "manager_agent_id"],
            ["agents.user_id", "agents.id"],
            name="organization_manager_owner",
            use_alter=True,
        ),
        Index("organizations_owner_created", "user_id", "created_at", "id"),
    )


class Membership(Base):
    __tablename__ = "memberships"
    org_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "org_id"],
            ["organizations.user_id", "organizations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("role IN ('owner','editor','viewer')", name="membership_role"),
        Index("memberships_owner_org", "owner_id", "org_id"),
    )


class Department(Base):
    __tablename__ = "departments"
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "org_id"],
            ["organizations.user_id", "organizations.id"],
            ondelete="CASCADE",
        ),
    )


class Agent(Base):
    __tablename__ = "agents"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(String(80))
    department_id: Mapped[str | None] = mapped_column(String(80))
    capability: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", "id"),
        ForeignKeyConstraint(
            ["user_id", "org_id"],
            ["organizations.user_id", "organizations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "org_id", "department_id"],
            ["departments.user_id", "departments.org_id", "departments.id"],
        ),
        Index("agents_owner_org", "user_id", "org_id", "created_at"),
    )


class Policy(Base):
    __tablename__ = "policies"
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "policy_id"],
            ["agents.user_id", "agents.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("version >= 0", name="policy_version_nonnegative"),
    )


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "policy_id"],
            ["policies.user_id", "policies.policy_id"],
            ondelete="CASCADE",
        ),
    )


class OrgChild:
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80))
    org_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def org_constraints(prefix):
    return (
        ForeignKeyConstraint(
            ["user_id", "org_id"],
            ["organizations.user_id", "organizations.id"],
            ondelete="CASCADE",
        ),
        Index(prefix + "_owner_org", "user_id", "org_id", "created_at", "id"),
    )


class Run(OrgChild, Base):
    __tablename__ = "runs"
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(40))
    outputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (
        *org_constraints("runs"),
        UniqueConstraint("user_id", "org_id", "id"),
    )


class Feedback(OrgChild, Base):
    __tablename__ = "feedback"
    agent_id: Mapped[str | None] = mapped_column(String(80))
    score: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    verified: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[int] = mapped_column(Integer)
    corrected_strategy: Mapped[str | None] = mapped_column(String(20))
    __table_args__ = (
        *org_constraints("feedback"),
        ForeignKeyConstraint(
            ["user_id", "org_id", "agent_id"],
            ["agents.user_id", "agents.org_id", "agents.id"],
        ),
        CheckConstraint(
            "score IS NULL OR score BETWEEN 1 AND 5", name="feedback_score"
        ),
    )


class Relationship(OrgChild, Base):
    __tablename__ = "relationships"
    source: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        *org_constraints("relationships"),
        ForeignKeyConstraint(["user_id", "source"], ["agents.user_id", "agents.id"]),
        ForeignKeyConstraint(["user_id", "target"], ["agents.user_id", "agents.id"]),
    )


class Conversation(OrgChild, Base):
    __tablename__ = "conversations"
    run_id: Mapped[str] = mapped_column(String(80))
    sender_id: Mapped[str] = mapped_column(String(80))
    receiver_id: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        *org_constraints("conversations"),
        ForeignKeyConstraint(
            ["user_id", "org_id", "run_id"],
            ["runs.user_id", "runs.org_id", "runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["user_id", "sender_id"], ["agents.user_id", "agents.id"]),
        ForeignKeyConstraint(
            ["user_id", "receiver_id"], ["agents.user_id", "agents.id"]
        ),
    )


class Decision(OrgChild, Base):
    __tablename__ = "decisions"
    agent_id: Mapped[str] = mapped_column(String(80))
    run_id: Mapped[str | None] = mapped_column(String(80))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (
        *org_constraints("decisions"),
        ForeignKeyConstraint(["user_id", "agent_id"], ["agents.user_id", "agents.id"]),
        ForeignKeyConstraint(
            ["user_id", "org_id", "run_id"],
            ["runs.user_id", "runs.org_id", "runs.id"],
            ondelete="CASCADE",
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(80))
    ref_id: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    __table_args__ = (Index("audit_owner_created", "user_id", "created_at", "id"),)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
