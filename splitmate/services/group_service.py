from models import ExpenseGroup, new_edit_pin, new_public_token
from sqlalchemy.orm import Session


def get_group_by_token(db: Session, token: str) -> ExpenseGroup | None:
    return db.query(ExpenseGroup).filter(ExpenseGroup.public_token == token).first()


def get_group_by_line_id(db: Session, line_group_id: str) -> ExpenseGroup | None:
    return db.query(ExpenseGroup).filter(ExpenseGroup.line_group_id == line_group_id).first()


def get_or_create_group_for_line(
    db: Session, line_group_id: str, name: str | None = None
) -> ExpenseGroup:
    group = get_group_by_line_id(db, line_group_id)
    if group:
        if name and group.name != name and group.name in ("未命名群組", line_group_id):
            group.name = name
        return group

    group = ExpenseGroup(
        line_group_id=line_group_id,
        name=name or "LINE 群組",
        public_token=new_public_token(),
        edit_pin=new_edit_pin(),
        is_demo=False,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def verify_edit_pin(group: ExpenseGroup, pin: str | None) -> bool:
    if not pin:
        return False
    return str(pin).strip() == str(group.edit_pin).strip()
