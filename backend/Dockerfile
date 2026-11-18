FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system hwcatalog && adduser --system --ingroup hwcatalog hwcatalog
RUN mkdir -p /var/lib/hw-catalog/MEDIA/images /var/lib/hw-catalog/MEDIA/thumbnails && chown -R hwcatalog:hwcatalog /var/lib/hw-catalog

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

USER hwcatalog
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
