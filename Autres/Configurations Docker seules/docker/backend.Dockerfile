# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend
COPY backend/requirements.txt /app/backend/requirements.txt
COPY docker/requirements.txt /app/deployment/requirements.txt
RUN pip install -r requirements.txt -r /app/deployment/requirements.txt \
    && groupadd --gid 10001 kilima \
    && useradd --uid 10001 --gid kilima --create-home kilima
COPY backend/ /app/backend/
COPY frontend/legacy/ /app/frontend/legacy/
COPY docker/entrypoint.py docker/healthcheck.py docker/bootstrap_admin.py /app/deployment/
RUN mkdir -p /app/backend/uploads && chown -R kilima:kilima /app/backend/uploads
USER kilima
EXPOSE 8000
ENTRYPOINT ["python", "/app/deployment/entrypoint.py"]
CMD ["gunicorn", "kilima.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
