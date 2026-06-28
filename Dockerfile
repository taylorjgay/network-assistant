# Stage 1: build React dashboard
FROM node:20-slim AS dashboard-builder
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY --from=dashboard-builder /app/dashboard/dist ./dashboard/dist/
EXPOSE 8000
CMD ["python", "-m", "src.server"]
