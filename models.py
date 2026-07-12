"""SplitMate 資料模型（SQLAlchemy）。

命名說明（給人類看的）：
- SplitMate     = 整個產品名稱
- ExpenseGroup  = 「一個記帳群組」在資料庫裡的那一筆（對應一個 LINE 群）
- GroupMember   = 群組裡的一個人
- Bill          = 一筆支出
- BillParticipant = 這筆支出裡「誰欠多少」
"""
from __future__ import annotations

import enum
import hashlib
import logging
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    Enum as SQLAEnum,
)
from sqlalchemy.orm import Session, declarative_base, joinedload, relationship, sessionmaker
from sqlalchemy.sql import func

from splitmate.config import Config

logger = logging.getLogger(__name__)

engine = None
SessionLocal = None
Base = declarative_base()

# 資料表前綴 sm_ = SplitMate
TABLE_PREFIX = "sm_"


class SplitType(enum.Enum):
    EQUAL = "equal"
    UNEQUAL = "unequal"


class ExpenseGroup(Base):
    """一個使用 SplitMate 的記帳群組（通常對應一個 LINE 群）。"""

    __tablename__ = f"{TABLE_PREFIX}groups"

    id = Column(Integer, primary_key=True, index=True)
    line_group_id = Column(String, unique=True, nullable=True, index=True)
    name = Column(String, nullable=False, default="未命名群組")
    public_token = Column(String(64), unique=True, nullable=False, index=True)
    edit_pin = Column(String(16), nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GroupMember(Base):
    """群組成員。優先用 line_user_id 辨識同一個人；name 是顯示名稱。"""

    __tablename__ = f"{TABLE_PREFIX}group_members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    group_id = Column(String, nullable=False, index=True)
    line_user_id = Column(String, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    paid_bills = relationship(
        "Bill",
        back_populates="payer_member_profile",
        foreign_keys="[Bill.payer_member_id]",
    )
    bill_participations = relationship(
        "BillParticipant",
        back_populates="debtor_member_profile",
        foreign_keys="[BillParticipant.debtor_member_id]",
    )

    __table_args__ = (
        UniqueConstraint("name", "group_id", name="sm_member_name_group_uc"),
        UniqueConstraint("line_user_id", "group_id", name="sm_line_user_group_uc"),
        Index("ix_sm_members_group_line_user", "group_id", "line_user_id"),
        Index("ix_sm_members_group_name", "group_id", "name"),
    )


class Bill(Base):
    __tablename__ = f"{TABLE_PREFIX}bills"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=False)
    total_bill_amount = Column(Numeric(10, 2), nullable=False)
    payer_member_id = Column(
        Integer, ForeignKey(f"{TABLE_PREFIX}group_members.id", ondelete="CASCADE"), nullable=False
    )
    payer_member_profile = relationship(
        "GroupMember", back_populates="paid_bills", foreign_keys=[payer_member_id]
    )
    split_type = Column(SQLAEnum(SplitType, name="sm_split_type_enum"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_archived = Column(Boolean, default=False, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    participants = relationship(
        "BillParticipant", back_populates="bill", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_sm_bills_group_archived", "group_id", "is_archived"),
        Index("ix_sm_bills_group_created", "group_id", "created_at"),
        UniqueConstraint("group_id", "content_hash", name="sm_bill_content_unique"),
    )


class BillParticipant(Base):
    __tablename__ = f"{TABLE_PREFIX}bill_participants"

    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(
        Integer, ForeignKey(f"{TABLE_PREFIX}bills.id", ondelete="CASCADE"), nullable=False
    )
    bill = relationship("Bill", back_populates="participants")
    debtor_member_id = Column(
        Integer, ForeignKey(f"{TABLE_PREFIX}group_members.id", ondelete="CASCADE"), nullable=False
    )
    debtor_member_profile = relationship(
        "GroupMember",
        back_populates="bill_participations",
        foreign_keys=[debtor_member_id],
    )
    amount_owed = Column(Numeric(10, 2), nullable=False)
    is_paid = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("bill_id", "debtor_member_id", name="sm_bill_debtor_uc"),
        Index("ix_sm_participants_bill_paid", "bill_id", "is_paid"),
        Index("ix_sm_participants_debtor_paid", "debtor_member_id", "is_paid"),
    )


class DuplicatePreventionLog(Base):
    __tablename__ = f"{TABLE_PREFIX}duplicate_prevention_log"

    id = Column(Integer, primary_key=True, index=True)
    operation_hash = Column(String(64), nullable=False, index=True)
    group_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    operation_type = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_sm_dup_prev_hash_group_user", "operation_hash", "group_id", "user_id"),
    )


def init_engine(database_url: Optional[str] = None):
    global engine, SessionLocal
    url = database_url or Config.DATABASE_URL
    kwargs = {"pool_pre_ping": True, "pool_recycle": 3600}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


def ensure_engine():
    if engine is None or SessionLocal is None:
        init_engine()


@contextmanager
def get_db():
    ensure_engine()
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    ensure_engine()
    logger.info("初始化 SplitMate 資料表…")
    Base.metadata.create_all(bind=engine)
    logger.info("SplitMate 資料表就緒。")


def new_public_token() -> str:
    return secrets.token_urlsafe(18)


def new_edit_pin() -> str:
    return f"{secrets.randbelow(10000):04d}"


def generate_operation_hash(user_id: str, operation: str, content: str) -> str:
    return hashlib.sha256(f"{user_id}:{operation}:{content}".encode("utf-8")).hexdigest()


def is_duplicate_operation(
    db: Session,
    operation_hash: str,
    group_id: str,
    user_id: str,
    time_window_minutes: float = 2,
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)
    return (
        db.query(DuplicatePreventionLog)
        .filter(
            DuplicatePreventionLog.operation_hash == operation_hash,
            DuplicatePreventionLog.group_id == group_id,
            DuplicatePreventionLog.user_id == user_id,
            DuplicatePreventionLog.created_at > cutoff,
        )
        .first()
        is not None
    )


def log_operation(
    db: Session, operation_hash: str, group_id: str, user_id: str, operation_type: str
):
    db.add(
        DuplicatePreventionLog(
            operation_hash=operation_hash,
            group_id=group_id,
            user_id=user_id,
            operation_type=operation_type,
        )
    )
    db.flush()


def cleanup_old_duplicate_logs(db: Session, days_to_keep: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    return (
        db.query(DuplicatePreventionLog)
        .filter(DuplicatePreventionLog.created_at < cutoff)
        .delete()
    )


def generate_content_hash(
    payer_id: int, description: str, amount: str, participants_str: str, group_id: str
) -> str:
    import re

    normalized_description = " ".join(description.strip().lower().split())
    normalized_amount = str(Decimal(amount).quantize(Decimal("0.01")))
    mentions = re.findall(r"@(\S+)(?:\s+([\d\.]+))?", participants_str)
    sorted_mentions = sorted(mentions, key=lambda x: x[0].lower())
    parts = []
    for name, amount_str in sorted_mentions:
        if amount_str:
            parts.append(f"@{name.lower()}:{Decimal(amount_str).quantize(Decimal('0.01'))}")
        else:
            parts.append(f"@{name.lower()}")
    content = f"{group_id}:{payer_id}:{normalized_description}:{normalized_amount}:{'|'.join(parts)}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_or_create_member_by_line_id(
    db: Session, line_user_id: str, group_id: str, display_name: str
) -> GroupMember:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            member = (
                db.query(GroupMember)
                .filter(
                    GroupMember.line_user_id == line_user_id,
                    GroupMember.group_id == group_id,
                )
                .first()
            )
            if member:
                if member.name != display_name:
                    member.name = display_name
                    member.updated_at = datetime.now(timezone.utc)
                return member

            existing = (
                db.query(GroupMember)
                .filter(
                    GroupMember.name == display_name,
                    GroupMember.group_id == group_id,
                    GroupMember.line_user_id.is_(None),
                )
                .first()
            )
            if existing:
                existing.line_user_id = line_user_id
                existing.updated_at = datetime.now(timezone.utc)
                db.flush()
                return existing

            member = GroupMember(
                name=display_name, group_id=group_id, line_user_id=line_user_id
            )
            db.add(member)
            db.flush()
            return member
        except Exception as e:
            if "unique constraint" in str(e).lower() and attempt < max_retries - 1:
                db.rollback()
                time.sleep(0.01 * (attempt + 1))
                continue
            if attempt == max_retries - 1:
                raise
            db.rollback()
            time.sleep(0.01 * (attempt + 1))
    raise RuntimeError(f"無法取得成員 line={line_user_id} group={group_id}")


def get_or_create_member_by_name(
    db: Session,
    name: str,
    group_id: str,
    line_user_id: Optional[str] = None,
) -> GroupMember:
    """用顯示名稱找人；若有 LINE userId 會一併綁定。"""
    if line_user_id:
        return get_or_create_member_by_line_id(
            db, line_user_id=line_user_id, group_id=group_id, display_name=name
        )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            member = (
                db.query(GroupMember)
                .filter(GroupMember.name == name, GroupMember.group_id == group_id)
                .first()
            )
            if member:
                return member
            member = GroupMember(name=name, group_id=group_id, line_user_id=None)
            db.add(member)
            db.flush()
            return member
        except Exception as e:
            if "unique constraint" in str(e).lower() and attempt < max_retries - 1:
                db.rollback()
                time.sleep(0.01 * (attempt + 1))
                continue
            if attempt == max_retries - 1:
                raise
            db.rollback()
            time.sleep(0.01 * (attempt + 1))
    raise RuntimeError(f"無法取得成員 name={name} group={group_id}")


def get_bill_by_id(db: Session, bill_id: int, group_id: str) -> Optional[Bill]:
    return (
        db.query(Bill)
        .options(
            joinedload(Bill.payer_member_profile),
            joinedload(Bill.participants).joinedload(BillParticipant.debtor_member_profile),
        )
        .filter(Bill.id == bill_id, Bill.group_id == group_id)
        .first()
    )


def list_group_members(db: Session, group_id: str) -> List[GroupMember]:
    return (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id)
        .order_by(GroupMember.name.asc())
        .all()
    )


def atomic_create_bill(
    db: Session, bill_data: dict, participants_data: List[dict]
) -> Tuple[Optional[Bill], str]:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            existing = (
                db.query(Bill)
                .filter(
                    Bill.group_id == bill_data["group_id"],
                    Bill.content_hash == bill_data["content_hash"],
                )
                .first()
            )
            if existing:
                return get_bill_by_id(db, existing.id, existing.group_id), "duplicate_found"

            new_bill = Bill(**bill_data)
            db.add(new_bill)
            db.flush()
            for pdata in participants_data:
                row = pdata.copy()
                row["bill_id"] = new_bill.id
                db.add(BillParticipant(**row))
            db.commit()
            return get_bill_by_id(db, new_bill.id, new_bill.group_id), "success"
        except Exception as e:
            db.rollback()
            msg = str(e).lower()
            if ("unique constraint" in msg or "duplicate" in msg) and "content_hash" in msg:
                existing = (
                    db.query(Bill)
                    .options(
                        joinedload(Bill.payer_member_profile),
                        joinedload(Bill.participants).joinedload(
                            BillParticipant.debtor_member_profile
                        ),
                    )
                    .filter(
                        Bill.group_id == bill_data["group_id"],
                        Bill.content_hash == bill_data["content_hash"],
                    )
                    .first()
                )
                if existing:
                    return existing, "duplicate_constraint"
                return None, "constraint_error"
            if attempt < max_retries - 1:
                time.sleep(0.01 * (attempt + 1))
                continue
            logger.exception("atomic_create_bill failed: %s", e)
            return None, "unexpected_error"
    return None, "max_retries_exceeded"
