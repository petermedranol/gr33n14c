# Greeniac — Backend

API REST para el control de casa e invernadero, corriendo en una Raspberry Pi 4.

## Stack

- Python 3.13 · FastAPI · SQLAlchemy 2.0 async (asyncpg) · Alembic · PostgreSQL
- JWT en cookie httpOnly + doble-submit CSRF
- Autenticación con `passlib[bcrypt]` + `PyJWT`

---

## Puesta en marcha (en la Raspberry Pi)

### 1. Crear entorno virtual e instalar dependencias

```bash
cd ~/Gr33n14c/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
nano .env   # editar DATABASE_URL y JWT_SECRET
```

Generar una clave JWT segura:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Crear la base de datos PostgreSQL

```sql
CREATE USER greeniac WITH PASSWORD 'TU_CLAVE';
CREATE DATABASE greeniac OWNER greeniac;
```

### 4. Generar y aplicar la migración inicial

```bash
# Generar migración a partir de los modelos
alembic revision --autogenerate -m "initial schema"

# Aplicar la migración
alembic upgrade head
```

### 5. Sembrar datos iniciales

```bash
python seed.py
```

Crea los tipos de usuario, el árbol de menú y el usuario administrador:
- **Email:** `admin@greeniac.local`
- **Contraseña:** `Admin2026!`

### 6. Lanzar el servidor

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

La API queda disponible en `http://192.168.1.250:8000`.
Documentación interactiva: `http://192.168.1.250:8000/docs`

---

## Flujo de autenticación

1. `POST /api/login` → el servidor establece las cookies `access_token` (httpOnly) y `XSRF-TOKEN`.
2. El SPA Angular lee `XSRF-TOKEN` y lo envía como header `X-XSRF-TOKEN` en cada petición mutante.
3. `GET /api/user` → refresca la cookie CSRF y devuelve el usuario + menú al cargar la app.
4. `POST /api/logout` → elimina ambas cookies.

---

## Estructura del proyecto

```
backend/
  app/
    main.py          ← Instancia FastAPI, CORS, routers, SPA estático
    deps.py          ← Dependencias: get_current_user, verify_csrf, require_menu_access
    core/
      config.py      ← Settings (pydantic-settings), constantes de cookies
      database.py    ← Motor async, sessionmaker, Base, get_db
      security.py    ← hash/verify password, JWT, CSRF token
    models/          ← SQLAlchemy ORM (todos importados en __init__.py)
    schemas/         ← Pydantic v2
    routers/         ← auth, menu, camara
    services/        ← login_security, menu_service
  alembic/           ← Migraciones (versions/ se llena en la Pi)
  alembic.ini
  seed.py
  requirements.txt
  .env.example
```
