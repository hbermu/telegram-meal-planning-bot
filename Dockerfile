FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY meal_planning_bot/ /app/meal_planning_bot/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The database lives on a mounted volume owned by this user. It must be local
# storage: SQLite locking is unreliable over NFS and SMB.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin bot \
    && mkdir -p /data && chown 1000:1000 /data
USER 1000

VOLUME ["/data"]
ENTRYPOINT ["python3", "-m", "meal_planning_bot"]
