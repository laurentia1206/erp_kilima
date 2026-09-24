# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Éviter l'écriture de fichiers .pyc et forcer l'affichage immédiat des logs Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Installation des dépendances système nécessaires pour PostgreSQL et l'exécution
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Copie et installation des dépendances Python (pour exploiter le cache Docker)
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements-production.txt /app/backend/requirements-production.txt

RUN pip install --upgrade pip \
    && pip install -r requirements-production.txt

# Création du groupe et de l'utilisateur non-privilégié 'kilima'
RUN groupadd --gid 10001 kilima \
    && useradd --uid 10001 --gid kilima --create-home kilima

# Copie des fichiers source du projet
COPY backend/ /app/backend/
COPY frontend/legacy/ /app/frontend/legacy/

# Création et configuration du dossier des médias/uploads
RUN mkdir -p /app/backend/uploads /app/backend/staticfiles \
    && chown -R kilima:kilima /app

USER kilima

EXPOSE 8000

ENTRYPOINT ["python", "/app/backend/deployment/entrypoint.py"]
CMD ["gunicorn", "kilima.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]