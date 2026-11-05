FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api APP_ENV=production
COPY apps/api/requirements.txt apps/api/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY apps/api/interviewer ./apps/api/interviewer
COPY apps/api/migrations ./apps/api/migrations
RUN useradd --uid 10001 --create-home interviewer
USER interviewer
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready',timeout=2)"
CMD ["python", "-m", "uvicorn", "interviewer.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
