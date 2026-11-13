FROM python:3.11-slim
WORKDIR /app
# APP_ENV defaults to development; production overlays must set it explicitly.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/api APP_ENV=development
COPY apps/api/requirements.txt apps/api/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY apps/api/interviewer ./apps/api/interviewer
COPY apps/api/migrations ./apps/api/migrations
COPY apps/api/docker-entrypoint.sh /docker-entrypoint.sh
RUN useradd --uid 10001 --create-home interviewer \
    && chmod 755 /docker-entrypoint.sh \
    && chown -R interviewer:interviewer /app
USER interviewer
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=40s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready',timeout=2)"
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["api"]
