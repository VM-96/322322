"""
database.py — слой доступа к данным (SQLAlchemy 2.x).

Модели:
- User — учётные записи администраторов;
- Emergency — типы/сценарии ЧС (пожар, землетрясение и т.д.);
- EvacuationPlan — план этажа/зоны: изображение + JSON с интерактивными зонами и маршрутом;
- VideoInstruction — ссылки на rutube id или локальные видеофайлы.

SQLite используется по умолчанию; для PostgreSQL задайте переменную окружения DATABASE_URL.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Iterator, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


# --- URL БД: при отсутствии переменной — SQLite-файл в корне проекта ---
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./emergency_mvp.db",
)

# SQLite требует специального флага для многопоточности в dev-режиме
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Базовый класс моделей SQLAlchemy 2.x."""

    pass


class User(Base):
    """
    Пользователь системы. Для MVP достаточно роли администратора.
    Обычные посетители приложения не регистрируются — только просмотр контента.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"


class Emergency(Base):
    """Карточка чрезвычайной ситуации: заголовок, краткое описание, рекомендации."""

    __tablename__ = "emergencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Короткий код для UI (fire, earthquake, terror...)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    short_description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    # Подробные рекомендации (можно HTML из админки — на проде лучше санитизировать)
    recommendations: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    evacuation_plans: Mapped[list["EvacuationPlan"]] = relationship(
        "EvacuationPlan", back_populates="emergency", cascade="all, delete-orphan"
    )
    videos: Mapped[list["VideoInstruction"]] = relationship(
        "VideoInstruction", back_populates="emergency", cascade="all, delete-orphan"
    )


class EvacuationPlan(Base):
    """
    План эвакуации для конкретной ЧС (например, этаж здания).
    image_path — путь относительно /static (например uploads/plan_1.png).
    hotspots_json — JSON-массив зон клика и опционально линия маршрута (см. README в коде фронта).
    """

    __tablename__ = "evacuation_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    emergency_id: Mapped[int] = mapped_column(Integer, ForeignKey("emergencies.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # JSON: { "zones": [...], "route": { "points": [[x%, y%], ...] } }
    hotspots_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    emergency: Mapped["Emergency"] = relationship("Emergency", back_populates="evacuation_plans")


class VideoInstruction(Base):
    """
    Видеоинструкция.
    Приоритет источника на клиенте: Rutube (устар.) → локальный файл.
    author_name — подпись автора/подразделения, предоставившего материал (несколько записей на одну ЧС).
    """

    __tablename__ = "video_instructions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    emergency_id: Mapped[int] = mapped_column(Integer, ForeignKey("emergencies.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    rutube_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    author_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    emergency: Mapped["Emergency"] = relationship("Emergency", back_populates="videos")


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    Base.metadata.create_all(bind=engine)


def migrate_video_instruction_columns() -> None:
    """
    Добавляет столбцы rutube_id и author_name в существующую БД (SQLite/PostgreSQL),
    если таблица уже создана без них — без полного сброса файла БД.
    """
    insp = inspect(engine)
    if not insp.has_table("video_instructions"):
        return
    existing = {c["name"] for c in insp.get_columns("video_instructions")}
    stmts: list[str] = []
    if "rutube_id" not in existing:
        stmts.append("ALTER TABLE video_instructions ADD COLUMN rutube_id VARCHAR(128)")
    if "author_name" not in existing:
        stmts.append("ALTER TABLE video_instructions ADD COLUMN author_name VARCHAR(200)")
    if not stmts:
        return
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))


def get_db() -> Generator:
    """
    Зависимость FastAPI: выдаёт сессию БД и гарантирует закрытие после запроса.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator:
    """Контекстный менеджер для скриптов инициализации (вне FastAPI)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def parse_hotspots(hotspots_json: str) -> dict[str, Any]:
    """Безопасный разбор JSON плана; при ошибке возвращает пустую структуру."""
    try:
        data = json.loads(hotspots_json or "{}")
        if not isinstance(data, dict):
            return {"zones": [], "route": None}
        if "zones" not in data:
            data["zones"] = []
        return data
    except json.JSONDecodeError:
        return {"zones": [], "route": None}


def table_exists(table_name: str) -> bool:
    """Проверка наличия таблицы (удобно для идемпотентного сида)."""
    return inspect(engine).has_table(table_name)
