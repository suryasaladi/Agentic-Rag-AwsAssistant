# ---- Stage 1: build the Angular app ----
FROM node:22-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Stage 2: Python backend that also serves the built app ----
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# Built Angular files land in ./static, which main.py serves.
COPY --from=frontend /app/dist/RAG-System-UI/browser ./static

# HF Spaces expects 7860; Render (and others) inject their own $PORT at runtime.
# Shell form so ${PORT} expands; falls back to 7860 when unset.
ENV PORT=7860
EXPOSE 7860
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}
