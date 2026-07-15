# Deploy to Hugging Face Spaces (Docker)

The whole app ships as **one Docker Space**: FastAPI serves the API *and* the
built Angular UI on port 7860. Files that make this work:

- [Dockerfile](Dockerfile) — builds Angular, then runs FastAPI serving `./static`
- [.dockerignore](.dockerignore) — keeps `node_modules` / `.venv` / `dist` out of the build context
- [README.md](README.md) — YAML front matter with `sdk: docker`, `app_port: 7860`
- `backend/main.py` — serves the built Angular app when `./static` exists

## Prerequisites
- A free [huggingface.co](https://huggingface.co) account.
- Pinecone index already populated (`python backend/ingest.py`, done once) — the
  Space only *queries* Pinecone; it does not ingest.

## Steps

**1. Create the Space**
huggingface.co → **New Space** → SDK: **Docker** → Blank → name it → Create.

**2. Set secrets & variables** (Space → **Settings → Variables and secrets**)

Secrets (hidden):
- `GROQ_API_KEY`
- `PINECONE_API_KEY`

Variables (plain):
- `PINECONE_INDEX` = `rag-poc`
- `PINECONE_EMBED_MODEL` = `multilingual-e5-large`
- `GROQ_MODEL` = `llama-3.3-70b-versatile`
- `TOP_K` = `5`
- `ALLOW_MUTATIONS` = `false`  *(keep false on a public demo; true lets signed-in users stop their own EC2)*

> Not needed on the Space: AWS keys / `S3_*` — those are only for local ingestion.
> Each end user supplies their own AWS credentials at the login screen.

**3. Push the repo to the Space**
```bash
git remote add space https://huggingface.co/spaces/<your-username>/<space-name>
git push space HEAD:main
```
Auth: username = your HF username, password = an HF **access token**
(huggingface.co → Settings → Access Tokens, "write" scope).

**4. Build & run**
HF builds the Docker image and starts it. Watch the **Logs** tab. When healthy,
the app is at `https://<your-username>-<space-name>.hf.space`.

## Alternative: Render (also free, same Dockerfile)

If HF's create page gates you behind paid hardware, deploy the same container to
[Render](https://render.com) instead — the repo includes [render.yaml](render.yaml).

1. Push the repo to GitHub (Render deploys from a Git repo).
2. Render dashboard → **New → Blueprint** → connect the repo → it reads
   `render.yaml` and creates a free Docker web service.
   (Or **New → Web Service** → pick the repo → Render auto-detects the Dockerfile → Instance type **Free**.)
3. Add the two secrets when prompted: `GROQ_API_KEY`, `PINECONE_API_KEY`
   (the rest come from `render.yaml`).
4. Deploy → app at `https://<name>.onrender.com`.

Render binds the service to its injected `$PORT`; the Dockerfile already honors it.
Free instances spin down after ~15 min idle (cold start on next hit) and have
512 MB RAM — fine for this backend (no local ML model).

## Notes
- **HTTPS is automatic** (required — users type AWS credentials).
- **Free CPU Spaces sleep** after inactivity and restart cold; in-memory sessions
  (per-user AWS creds + conversation memory) reset, so users just re-login.
- **Single instance only** — the session store is in-memory; don't scale to
  multiple replicas without a shared store (e.g. Redis).
- Re-run `python backend/ingest.py` locally whenever the S3 runbooks change; the
  Space picks up the new vectors from Pinecone automatically.
