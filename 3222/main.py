"""
py -m pip install -r requirements.txt
py -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
http://127.0.0.1:8000/
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import bcrypt
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from database import (
    Emergency,
    EvacuationPlan,
    SessionLocal,
    User,
    VideoInstruction,
    get_db,
    init_db,
    migrate_video_instruction_columns,
    parse_hotspots,
    session_scope,
)

# --- Пути проекта ---
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOAD_DIR = STATIC_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Секрет для подписи cookie сессии (в продакшене задать через переменную окружения)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me-in-production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Жизненный цикл приложения (FastAPI 0.109+): инициализация БД при старте.
    """
    init_db()
    migrate_video_instruction_columns()
    seed_demo_data()
    yield


app = FastAPI(
    title="Информирование при ЧС",
    description="API и веб-интерфейс для планов эвакуации и видеоинструкций",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ============ Pydantic-схемы API ============


class EmergencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    short_description: str
    sort_order: int


class EmergencyDetailOut(EmergencyOut):
    recommendations: str


class EvacuationPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    emergency_id: int
    title: str
    description: str
    image_url: str
    hotspots: dict[str, Any]
    sort_order: int


class VideoInstructionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    emergency_id: int
    title: str
    description: str
    rutube_id: Optional[str] = None
    local_url: Optional[str] = None
    author_name: Optional[str] = None
    sort_order: int


class LoginBody(BaseModel):
    username: str
    password: str


def verify_password(plain: str, hashed: str) -> bool:
    """Проверка пароля против bcrypt-хэша."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def hash_password(plain: str) -> str:
    """Хэширование пароля администратора (bcrypt)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def plan_to_out(p: EvacuationPlan) -> EvacuationPlanOut:
    return EvacuationPlanOut(
        id=p.id,
        emergency_id=p.emergency_id,
        title=p.title,
        description=p.description,
        image_url=f"/static/{p.image_path.lstrip('/')}",
        hotspots=parse_hotspots(p.hotspots_json),
        sort_order=p.sort_order,
    )


def video_to_out(v: VideoInstruction) -> VideoInstructionOut:
    local_url = None
    if v.local_path:
        local_url = f"/static/{v.local_path.lstrip('/')}"
    return VideoInstructionOut(
        id=v.id,
        emergency_id=v.emergency_id,
        title=v.title,
        description=v.description,
        rutube_id=v.rutube_id,
        local_url=local_url,
        author_name=v.author_name,
        sort_order=v.sort_order,
    )


# ============ Зависимости: админ-сессия ============


def get_current_admin_id(request: Request) -> Optional[int]:
    return request.session.get("admin_user_id")


def require_admin(request: Request) -> int:
    uid = get_current_admin_id(request)
    if uid is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход администратора")
    return int(uid)


AdminId = Annotated[int, Depends(require_admin)]
DbSession = Annotated[Session, Depends(get_db)]


# ============ Стартовая инициализация БД ============


def seed_demo_data() -> None:
    """
    Создаёт демо-администратора и примеры ЧС, если таблицы пусты.
    Логин по умолчанию: admin / admin123
    """
    with session_scope() as db:
        if db.execute(select(User).limit(1)).scalar_one_or_none() is not None:
            return

        admin = User(
            username="admin",
            hashed_password=hash_password("admin123"),
            is_admin=True,
        )
        db.add(admin)
        db.flush()

        # Демо-план: зоны клика в процентах от размера изображения + маршрут эвакуации
        demo_hotspots = {
            "zones": [
                {
                    "id": "z-auditorium",
                    "label": "Актовый зал",
                    "x": 10,
                    "y": 15,
                    "w": 35,
                    "h": 40,
                    "hint": "Двигайтесь к ближайшему выходу, не пользуйтесь лифтом.",
                },
                {
                    "id": "z-corridor",
                    "label": "Коридор",
                    "x": 48,
                    "y": 20,
                    "w": 42,
                    "h": 30,
                    "hint": "Следуйте по указателям «Выход».",
                },
                {
                    "id": "z-exit",
                    "label": "Выход",
                    "x": 70,
                    "y": 55,
                    "w": 25,
                    "h": 35,
                    "hint": "Сбор у назначенной площадки.",
                },
            ],
            "route": {
                "label": "Рекомендуемый путь эвакуации",
                "points": [[22, 35], [55, 35], [82, 72]],
            },
        }

        emergencies_data = [
            {
                "code": "fire",
                "title": "Пожар",
                "short_description": "Дым, огонь, срабатывание пожарной сигнализации.",
                "recommendations": (
                    "<ul>"
                    "<li>Немедленно покиньте помещение по эвакуационным выходам.</li>"
                    "<li>Не пользуйтесь лифтом.</li>"
                    "<li>Если проход задымлён — двигайтесь ползком у стены.</li>"
                    "<li>Сообщите о пожаре по телефону 101 или 112.</li>"
                    "</ul>"
                ),
                "sort_order": 10,
                "plans": [
                    {
                        "title": "1 этаж — схема эвакуации",
                        "description": "Кликните по зонам для подсказок. Красная линия — ориентировочный маршрут.",
                        "image_path": "img/demo_floor_plan.svg",
                        "hotspots_json": json.dumps(demo_hotspots),
                        "sort_order": 10,
                    }
                ],
                "videos": [
                    {
                        "title": "Что делать при пожаре",
                        "description": "Официальный обучающий ролик на Rutube (правила поведения, дым, эвакуация).",
                        "rutube_id": "70935a155afff67cbd19758d7726c446",
                        "author_name": "МЧС России (Rutube)",
                        "sort_order": 10,
                    }
                ],
            },
            {
                "code": "drone",
                "title": "Атака БПЛА",
                "short_description": "Угроза с воздуха, характерный звук, опасность падения обломков.",
                "recommendations": (
                    "<ul>"
                    "<li><strong>При обнаружении дрона в воздухе:</strong> немедленно покиньте открытое пространство, зайдите в здание.</li>"
                    "<li><strong>На улице:</strong> укройтесь за капитальными стенами, в подземном переходе или складках местности.</li>"
                    "<li><strong>В здании:</strong> отойдите от окон, займите место у несущей стены или в помещении без окон (коридор, санузел, кладовая).</li>"
                    "<li><strong>В транспорте:</strong> остановитесь, покиньте транспортное средство, отойдите на безопасное расстояние и найдите укрытие.</li>"
                    "<li><strong>Категорически запрещается:</strong> приближаться к упавшим БПЛА или их обломкам.</li>"
                    "<li>Сообщите об обнаружении по номеру <strong>112</strong>.</li>"
                    "</ul>"
                ),
                "sort_order": 15,
                "plans": [],
                "videos": [
                    {
                        "title": "Действия при атаке беспилотных летательных аппаратов",
                        "description": "Официальные рекомендации МЧС России: порядок действий при обнаружении БПЛА, правила укрытия и информирования экстренных служб.",
                        "rutube_id": "",
                        "author_name": "МЧС России (Rutube)",
                        "sort_order": 10,
                    }
                ],
            },
            {
                "code": "earthquake",
                "title": "Землетрясение",
                "short_description": "Толчки, раскачивание здания, падающие предметы.",
                "recommendations": (
                    "<ul>"
                    "<li>Укройтесь под прочным столом или у несущей стены.</li>"
                    "<li>Держитесь подальше от окон и тяжёлых предметов.</li>"
                    "<li>После окончания толчков эвакуируйтесь по лестницам.</li>"
                    "</ul>"
                ),
                "sort_order": 20,
                "plans": [],
                "videos": [
                    {
                        "title": "Землетрясение и другие ЧС природного характера",
                        "description": "Фрагмент курса «Безопасность для всех»: действия населения (в т.ч. при толчках). Rutube.",
                        "rutube_id": "ed485fd5b100595aa133968eeaeb23fc",
                        "author_name": "«Безопасность для всех» (Rutube)",
                        "sort_order": 10,
                    }
                ],
            },
            {
                "code": "terror",
                "title": "Угроза террористического акта",
                "short_description": "Подозрительные предметы, угрозы, эвакуация по команде.",
                "recommendations": (
                    "<ul>"
                    "<li>Соблюдайте указания ответственных лиц и служб безопасности.</li>"
                    "<li>Не трогайте подозрительные предметы.</li>"
                    "<li>Двигайтесь спокойно к безопасной зоне.</li>"
                    "</ul>"
                ),
                "sort_order": 30,
                "plans": [],
                "videos": [
                    {
                        "title": "Противодействие терроризму и вербовке",
                        "description": "Социальный ролик МВД России на Rutube: бдительность граждан, риски манипуляций.",
                        "rutube_id": "ae778ebaf11bd3aa04099483450b1873",
                        "author_name": "МВД России (Rutube)",
                        "sort_order": 10,
                    }
                ],
            },
        ]

        for ed in emergencies_data:
            plans = ed.pop("plans")
            videos = ed.pop("videos")
            em = Emergency(**ed)
            db.add(em)
            db.flush()
            for pd in plans:
                db.add(EvacuationPlan(emergency_id=em.id, **pd))
            for vd in videos:
                db.add(VideoInstruction(emergency_id=em.id, **vd))


# ============ Страницы ============


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request) -> Any:
    """Главная страница с картой и списком ЧС."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {"is_admin": get_current_admin_id(request) is not None},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> Any:
    """Панель администратора."""
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"is_admin": get_current_admin_id(request) is not None},
    )


# ============ Публичное API ============


@app.get("/api/emergencies", response_model=list[EmergencyOut])
def api_list_emergencies(db: DbSession) -> Any:
    rows = db.execute(select(Emergency).order_by(Emergency.sort_order, Emergency.id)).scalars().all()
    return rows


@app.get("/api/emergencies/{emergency_id}", response_model=EmergencyDetailOut)
def api_emergency_detail(emergency_id: int, db: DbSession) -> Any:
    em = db.get(Emergency, emergency_id)
    if not em:
        raise HTTPException(status_code=404, detail="ЧС не найдена")
    return em


@app.get("/api/evacuation-plans", response_model=list[EvacuationPlanOut])
def api_list_plans(emergency_id: int, db: DbSession) -> Any:
    q = select(EvacuationPlan).where(EvacuationPlan.emergency_id == emergency_id)
    q = q.order_by(EvacuationPlan.sort_order, EvacuationPlan.id)
    rows = db.execute(q).scalars().all()
    return [plan_to_out(p) for p in rows]


@app.get("/api/evacuation-plans/{plan_id}", response_model=EvacuationPlanOut)
def api_plan_detail(plan_id: int, db: DbSession) -> Any:
    p = db.get(EvacuationPlan, plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="План не найден")
    return plan_to_out(p)


@app.get("/api/video-instructions", response_model=list[VideoInstructionOut])
def api_list_videos(emergency_id: int, db: DbSession) -> Any:
    q = select(VideoInstruction).where(VideoInstruction.emergency_id == emergency_id)
    q = q.order_by(VideoInstruction.sort_order, VideoInstruction.id)
    rows = db.execute(q).scalars().all()
    return [video_to_out(v) for v in rows]


# ============ Админ: сессия ============


@app.post("/api/admin/login")
def api_admin_login(request: Request, body: LoginBody, db: DbSession) -> Any:
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    request.session["admin_user_id"] = user.id
    request.session["admin_username"] = user.username
    return {"ok": True, "username": user.username}


@app.post("/api/admin/logout")
def api_admin_logout(request: Request) -> Any:
    request.session.clear()
    return {"ok": True}


@app.get("/api/admin/me")
def api_admin_me(request: Request, db: DbSession) -> Any:
    uid = get_current_admin_id(request)
    if not uid:
        return {"authenticated": False}
    user = db.get(User, uid)
    if not user:
        request.session.clear()
        return {"authenticated": False}
    return {"authenticated": True, "username": user.username}


# ============ Админ: CRUD ЧС ============


@app.post("/api/admin/emergencies")
def admin_create_emergency(
    db: DbSession,
    code: str = Form(...),
    title: str = Form(...),
    short_description: str = Form(""),
    recommendations: str = Form(""),
    sort_order: int = Form(0),
    _: int = Depends(require_admin),
) -> Any:
    if db.execute(select(Emergency).where(Emergency.code == code)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Код ЧС уже занят")
    em = Emergency(
        code=code.strip(),
        title=title.strip(),
        short_description=short_description,
        recommendations=recommendations,
        sort_order=sort_order,
    )
    db.add(em)
    db.commit()
    db.refresh(em)
    return {"id": em.id}


@app.put("/api/admin/emergencies/{emergency_id}")
def admin_update_emergency(
    emergency_id: int,
    db: DbSession,
    title: Optional[str] = Form(None),
    short_description: Optional[str] = Form(None),
    recommendations: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    _: int = Depends(require_admin),
) -> Any:
    em = db.get(Emergency, emergency_id)
    if not em:
        raise HTTPException(status_code=404, detail="Не найдено")
    if title is not None:
        em.title = title
    if short_description is not None:
        em.short_description = short_description
    if recommendations is not None:
        em.recommendations = recommendations
    if sort_order is not None:
        em.sort_order = sort_order
    db.commit()
    return {"ok": True}


@app.delete("/api/admin/emergencies/{emergency_id}")
def admin_delete_emergency(emergency_id: int, db: DbSession, _: int = Depends(require_admin)) -> Any:
    em = db.get(Emergency, emergency_id)
    if not em:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(em)
    db.commit()
    return {"ok": True}


def save_upload(file: UploadFile, subfolder: str, allowed: set[str]) -> str:
    """Сохраняет файл в static/uploads/{subfolder}/..., возвращает путь для БД (uploads/...)."""
    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Недопустимое расширение файла: {suffix}")
    folder = UPLOAD_DIR / subfolder
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    dest = folder / name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    rel = f"uploads/{subfolder}/{name}".replace("\\", "/")
    return rel


# ============ Админ: планы эвакуации ============


@app.post("/api/admin/evacuation-plans")
async def admin_create_plan(
    db: DbSession,
    emergency_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    hotspots_json: str = Form("{}"),
    image: UploadFile = File(...),
    _: int = Depends(require_admin),
) -> Any:
    em = db.get(Emergency, emergency_id)
    if not em:
        raise HTTPException(status_code=404, detail="ЧС не найдена")
    try:
        json.loads(hotspots_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="hotspots_json должен быть валидным JSON")
    ext_ok = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    image_path = save_upload(image, "plans", ext_ok)
    plan = EvacuationPlan(
        emergency_id=emergency_id,
        title=title.strip(),
        description=description,
        image_path=image_path,
        hotspots_json=hotspots_json,
        sort_order=sort_order,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id}


@app.put("/api/admin/evacuation-plans/{plan_id}")
async def admin_update_plan(
    plan_id: int,
    db: DbSession,
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    hotspots_json: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    _: int = Depends(require_admin),
) -> Any:
    plan = db.get(EvacuationPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    if title is not None:
        plan.title = title
    if description is not None:
        plan.description = description
    if sort_order is not None:
        plan.sort_order = sort_order
    if hotspots_json is not None:
        try:
            json.loads(hotspots_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="hotspots_json должен быть валидным JSON")
        plan.hotspots_json = hotspots_json
    if image is not None and image.filename:
        ext_ok = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
        plan.image_path = save_upload(image, "plans", ext_ok)
    db.commit()
    return {"ok": True}


@app.delete("/api/admin/evacuation-plans/{plan_id}")
def admin_delete_plan(plan_id: int, db: DbSession, _: int = Depends(require_admin)) -> Any:
    plan = db.get(EvacuationPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    db.delete(plan)
    db.commit()
    return {"ok": True}


# ============ Админ: видео ============


@app.post("/api/admin/video-instructions")
def admin_create_video(
    db: DbSession,
    emergency_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    author_name: str = Form(""),
    rutube_id: str = Form(""),
    sort_order: int = Form(0),
    video_file: Optional[UploadFile] = File(None),
    _: int = Depends(require_admin),
) -> Any:
    em = db.get(Emergency, emergency_id)
    if not em:
        raise HTTPException(status_code=404, detail="ЧС не найдена")

    # Обработка Rutube ID
    rid = rutube_id.strip() if rutube_id and rutube_id.strip() else None

    # Обработка автора
    auth = author_name.strip() if author_name and author_name.strip() else None

    # Обработка загруженного файла
    local_path = None
    if video_file is not None and video_file.filename:
        ext_ok = {".mp4", ".webm", ".ogg", ".mov", ".avi"}
        local_path = save_upload(video_file, "videos", ext_ok)
        rid = None  # Если загружен файл, Rutube ID не нужен

    # Проверка: должно быть или Rutube ID, или файл
    if not rid and not local_path:
        raise HTTPException(
            status_code=400,
            detail="Укажите ID ролика Rutube ИЛИ загрузите видеофайл"
        )

    v = VideoInstruction(
        emergency_id=emergency_id,
        title=title.strip(),
        description=description,
        rutube_id=rid,
        local_path=local_path,
        author_name=auth,
        sort_order=sort_order,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id}


@app.put("/api/admin/video-instructions/{video_id}")
async def admin_update_video(
    video_id: int,
    db: DbSession,
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    author_name: Optional[str] = Form(None),
    rutube_id: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    video_file: Optional[UploadFile] = File(None),
    _: int = Depends(require_admin),
) -> Any:
    v = db.get(VideoInstruction, video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Видео не найдено")

    if title is not None:
        v.title = title.strip()
    if description is not None:
        v.description = description
    if sort_order is not None:
        v.sort_order = sort_order
    if author_name is not None:
        v.author_name = author_name.strip() if author_name else None
    if rutube_id is not None:
        v.rutube_id = rutube_id.strip() if rutube_id else None

    # Если загружен новый файл
    if video_file is not None and video_file.filename:
        ext_ok = {".mp4", ".webm", ".ogg", ".mov", ".avi"}
        v.local_path = save_upload(video_file, "videos", ext_ok)
        v.rutube_id = None  # Rutube ID больше не нужен

    db.commit()
    return {"ok": True}


@app.delete("/api/admin/video-instructions/{video_id}")
def admin_delete_video(video_id: int, db: DbSession, _: int = Depends(require_admin)) -> Any:
    v = db.get(VideoInstruction, video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    db.delete(v)
    db.commit()
    return {"ok": True}