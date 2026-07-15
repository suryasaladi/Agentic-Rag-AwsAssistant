---
title: Cloud Ops Assistant
emoji: ☁️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# RAGSystemUI

An **agentic Cloud Ops assistant**: a LangGraph agent that queries your live AWS
account, answers from the team's runbooks with **corrective RAG**, remembers the
conversation, and can **diagnose** (fuse live state + runbooks) and **act**
(EC2 start/stop/reboot, confirmation-gated). Angular front end, Python **FastAPI**
backend, **Groq** LLM, **Pinecone** retrieval.

## Architecture

```
Login: user connects their AWS account ──> /api/auth ──> STS validate ──> in-memory boto3 session (per user)

Angular (rag-chat) ──> /api/chat (FastAPI, x-auth-session header)
                          │  LangGraph agent (create_react_agent) + per-thread memory (checkpointer)
                          ├─ AWS read tools (run as the signed-in identity):
                          │     list_aws_resources, list_ec2_instances, get_ec2_health,
                          │     get_cloudwatch_alarms, list_s3_buckets, list_dynamodb_tables
                          ├─ AWS action tools (ALLOW_MUTATIONS, confirmation-gated):
                          │     start_ec2_instance, stop_ec2_instance, reboot_ec2_instance
                          └─ search_runbooks ──> CORRECTIVE RAG:
                                retrieve (Pinecone) → grade relevance → reformulate + retry if weak
                       ──> { answer, citations, sessionId }

Ingestion (once):  S3 bucket (docs) ── ingest.py ──> chunk ──> Pinecone hosted embeddings ──> index
```

| Piece | Implementation |
|---|---|
| Auth | Per-user AWS creds (or assume-role) → validated via `sts:GetCallerIdentity`, held **in server memory** per session |
| Agent | **LangGraph** `create_react_agent` + `MemorySaver` checkpointer (per-user multi-turn memory) ([backend/main.py](backend/main.py)) |
| AWS tools | `boto3`, bound to the caller's session; read tools + confirmation-gated actions ([backend/tools.py](backend/tools.py)) |
| Runbook retrieval | **Corrective RAG**: Pinecone search → LLM relevance grading → query reformulation + retry ([backend/main.py](backend/main.py)) |
| Vector store | **Pinecone** (docs from **S3**, hosted `multilingual-e5-large` embeddings) |
| LLM | **Groq** (free key, Llama 3.x) |

The agent decides which tools to call; for **diagnosis** ("is X healthy / what's
wrong?") it gathers live state (`get_ec2_health`, `get_cloudwatch_alarms`) *and*
consults the runbooks, then correlates symptoms to the documented procedure.

Shared vs. per-user: Pinecone (runbooks) and Groq (LLM) are **app-owned**; the
**AWS credentials are per-user**, so each person sees only their own account.

The widget ([src/app/rag-chat/](src/app/rag-chat/)) posts `{ question, sessionId }`
to `/api/chat` with an `x-auth-session` header; `ng serve` proxies `/api` to
`localhost:3001`. Users sign in on the **Connect AWS** screen ([src/app/auth/](src/app/auth/)).

### IAM permissions the connecting user needs

Read-only (Phase 1): `AmazonEC2ReadOnlyAccess`, `AmazonS3ReadOnlyAccess`,
`AmazonDynamoDBReadOnlyAccess` (and `sts:GetCallerIdentity`, allowed by default).
Missing permissions surface as `AccessDenied` in the chat, not a crash.

**Actions (Phase 2 — EC2 start/stop/reboot):** additionally need
`ec2:StartInstances` / `StopInstances` / `RebootInstances`, and the backend flag
`ALLOW_MUTATIONS=true`. Actions are **confirmation-gated via LangGraph
`interrupt()`**: when the agent calls a mutation tool it describes the exact
instance, then `interrupt()` **pauses the graph** (checkpointed per thread). The
next user message is routed as the decision — `agent.invoke(Command(resume={"confirmed": …}))`
— and the tool executes the AWS call only on an affirmative (`confirm`/`yes`).
Any non-affirmative cancels; an unrelated message cancels then processes normally.
The LLM can never execute a mutation directly. With `ALLOW_MUTATIONS=false`
(default) the mutating tools aren't even registered.

> **Security:** users paste AWS creds into a web form held only in server memory.
> Prefer short-lived STS creds or a role to assume; serve over HTTPS in any real
> deployment; note that AWS resource details are sent to Groq (a third party) as
> LLM context. Keep `ALLOW_MUTATIONS=false` unless you intend to allow instance
> control, and scope the connecting identity's IAM to the minimum needed.

> **Note on Python 3.14:** `S3DirectoryLoader` (needs `unstructured`) and
> `langchain-pinecone` (pins `numpy<2`) have no 3.14 wheels, so `ingest.py` loads
> S3 with `boto3` and talks to Pinecone with the official client directly.
> LangChain still handles chunking, tool-calling, and Groq.

> **Note on Python 3.14:** `S3DirectoryLoader` (needs `unstructured`) and
> `langchain-pinecone` (pins `numpy<2`) have no 3.14 wheels, so the backend loads
> S3 with `boto3` and talks to Pinecone with the official client directly.
> LangChain still handles chunking and Groq. On Python 3.12/3.13 you could use
> `S3DirectoryLoader` + `langchain-pinecone` unchanged.

## Running the full chain

**1. Backend** ([backend/](backend/)):

```bash
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

cp .env.example .env        # fill AWS keys, PINECONE_API_KEY, GROQ_API_KEY
python ingest.py            # S3 -> chunk -> embed -> Pinecone (creates the index)
python -m uvicorn main:app --port 3001 --reload
```

Free keys, no credit card: **Groq** at [console.groq.com](https://console.groq.com),
**Pinecone** at [app.pinecone.io](https://app.pinecone.io). The IAM user needs
`s3:ListBucket` + `s3:GetObject` on the bucket. Re-run `python ingest.py`
whenever the S3 docs change.

**2. Frontend** (repo root):

```bash
npm install
ng serve                    # http://localhost:4200
```

Sanity check the backend: `curl -X POST http://localhost:3001/api/chat -H "content-type: application/json" -d "{\"question\":\"What is the rollback procedure for a failed deploy?\"}"`.

> The earlier Node backend in [server/](server/) (local embeddings + Groq) is
> superseded by [backend/](backend/) and can be deleted.

---

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 21.2.14.

## Development server

To start a local development server, run:

```bash
ng serve
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
