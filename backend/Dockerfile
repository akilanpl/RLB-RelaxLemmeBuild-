FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend /app/backend
COPY schema /app/schema
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "backend.serve"]
