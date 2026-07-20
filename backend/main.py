"""
Cloud Ops agent backend (FastAPI).

- Per-session AWS auth: each user "connects" their AWS account; we validate with
  STS and keep an in-memory boto3 session keyed by an opaque auth-session id.
- Tool-calling agent: ChatGroq (LangChain) with read-only AWS tools bound to the
  caller's session, plus a runbook-search tool over the shared Pinecone index.
- Contract to the widget stays { answer, citations, sessionId }.

Run:  uvicorn main:app --port 3001 --reload
"""
import os
import re
import time
import uuid
import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from pinecone import Pinecone
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from tools import build_tools

# Per-thread conversation memory for the LangGraph agent (keyed by auth session).
_memory = MemorySaver()

load_dotenv()

PINECONE_INDEX = os.environ.get("PINECONE_INDEX", "rag-poc")
EMBED_MODEL = os.environ.get("PINECONE_EMBED_MODEL", "multilingual-e5-large")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
TOP_K = int(os.environ.get("TOP_K", "5"))
SESSION_TTL = int(os.environ.get("SESSION_TTL_SECONDS", str(8 * 60 * 60)))
MAX_TOOL_LOOPS = 6
# Off by default. Set ALLOW_MUTATIONS=true to enable start/stop/reboot (still gated by confirmation).
ALLOW_MUTATIONS = os.environ.get("ALLOW_MUTATIONS", "false").strip().lower() == "true"

_AFFIRM = {"confirm", "confirmed", "yes", "y", "yep", "yeah", "ok", "okay", "proceed", "sure"}
_NEGATE = {"cancel", "no", "n", "nope", "nevermind", "abort", "dont"}


def _classify_confirmation(message: str) -> str:
    m = message.strip().lower()
    tokens = set(re.findall(r"[a-z']+", m))
    # Negation is checked first so contradictory input ("no, cancel") is treated
    # as a cancel — the safe default is to NOT execute.
    if tokens & _NEGATE or "never mind" in m or "don't" in m:
        return "negate"
    if tokens & _AFFIRM or "go ahead" in m or "do it" in m:
        return "affirm"
    return "other"

SYSTEM_PROMPT = (
    "You are a Cloud Ops assistant for the AWS account the user has signed in with.\n"
    "You have tools:\n"
    "- AWS (read-only): list_aws_resources, list_ec2_instances, get_ec2_health, "
    "get_cloudwatch_alarms, list_s3_buckets, list_dynamodb_tables — call these to get "
    "LIVE data about the user's account.\n"
    "- search_runbooks — search the team's runbooks for procedures and policies.\n"
    "For DIAGNOSIS or health questions ('is X ok?', 'what's wrong?', 'what should I do?'), "
    "gather live state (get_ec2_health and/or get_cloudwatch_alarms) AND consult the "
    "runbooks (search_runbooks), then correlate the observed symptoms to the documented "
    "procedure and recommend concrete next steps (citing the runbook).\n"
    "- AWS actions (only if available): start_ec2_instance, stop_ec2_instance, "
    "reboot_ec2_instance — these STAGE an action and require the user to confirm; they "
    "do not execute immediately. Relay the confirmation request and never claim an action "
    "is done until the user has confirmed.\n"
    "Rules: Always use a tool to get real data; never invent resource names, IDs, or "
    "statuses. Keep search_runbooks queries short (a few keywords). In your final answer, "
    "NEVER mention tool names or repeat your tool inputs / search queries — just present the "
    "findings and recommendation concisely. If a tool returns an error (e.g. AccessDenied), "
    "tell the user plainly and suggest checking IAM permissions. If the user just greets you, "
    "reply briefly and say what you can do.\n"
    "About this app: if the user asks who built, developed, created, made, or designed this "
    "assistant/app (or 'who are you', 'who made you', 'who invented you'), answer DIRECTLY "
    "without calling any tool — say it was developed by Surya Saladi, and include both links "
    "as full URLs: GitHub https://github.com/suryasaladi and "
    "LinkedIn https://www.linkedin.com/in/suryasaladia3/ . "
    "(The underlying language model is Meta's Llama served via Groq — mention that only if "
    "the user asks specifically about the AI model.)"
)

# Shared infra (app-owned): Pinecone for runbooks + Groq LLM.
_pc = None
_index = None
_llm = None

# Per-user AWS sessions: auth_session_id -> {"boto", "region", "arn", "last"}
_sessions: dict[str, dict] = {}


def _drop_session(auth_id: str) -> None:
    """Remove a session and its LangGraph conversation thread (frees memory)."""
    _sessions.pop(auth_id, None)
    try:
        _memory.delete_thread(auth_id)
    except Exception:  # noqa: BLE001
        pass


def _sweep_sessions() -> None:
    """Purge sessions (and their threads) idle past the TTL, including users who never return."""
    now = time.time()
    for auth_id in [a for a, s in _sessions.items() if now - s["last"] > SESSION_TTL]:
        _drop_session(auth_id)


def _pinecone():
    global _pc, _index
    if _index is None:
        _pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _index = _pc.Index(PINECONE_INDEX)
    return _pc, _index


def _groq():
    global _llm
    if _llm is None:
        _llm = ChatGroq(model=GROQ_MODEL, temperature=0.2, max_tokens=1024)
    return _llm


# Optional open-source observability (Langfuse). Tracing activates only when the
# LANGFUSE_* keys are set, so it never affects local/dev runs that don't use it.
_lf_handler = None
_lf_checked = False


def _langfuse_callbacks():
    global _lf_handler, _lf_checked
    if not _lf_checked:
        _lf_checked = True
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import get_client
                from langfuse.langchain import CallbackHandler
                ok = get_client().auth_check()  # verifies keys+host against Langfuse
                _lf_handler = CallbackHandler()
                print(f"[observability] Langfuse tracing enabled (auth_check={ok}, "
                      f"host={os.environ.get('LANGFUSE_HOST', 'default-eu')})")
            except Exception as e:  # noqa: BLE001
                print(f"[observability] Langfuse disabled: {e}")
    return [_lf_handler] if _lf_handler else []


def pinecone_retrieve(query: str, k: int):
    pc, index = _pinecone()
    emb = pc.inference.embed(model=EMBED_MODEL, inputs=[query], parameters={"input_type": "query"})
    result = index.query(vector=emb.data[0]["values"], top_k=k, include_metadata=True)
    return [(m.get("metadata") or {}) for m in result.get("matches", [])]


def _grade_chunks(query: str, metas: list) -> list:
    """Corrective RAG: keep only chunks the LLM judges relevant to the query."""
    if not metas:
        return []
    numbered = "\n\n".join(f"[{i + 1}] {md.get('text', '')}" for i, md in enumerate(metas))
    grader = _groq().invoke(
        [
            SystemMessage(
                content=(
                    "You are a strict relevance grader for a retrieval system. Given a question and "
                    "numbered passages, reply with ONLY the numbers of passages that directly help "
                    'answer it, comma-separated (e.g. "1,3"). If none are relevant, reply exactly "NONE". '
                    "No other text."
                )
            ),
            HumanMessage(content=f"Question: {query}\n\nPassages:\n{numbered}"),
        ]
    )
    text = (grader.content or "").strip()
    # Parse passage numbers first: a valid number anywhere wins over a stray "none"
    # elsewhere in a verbose reply (e.g. "none of the others, just 1 and 3").
    keep = {int(n) for n in re.findall(r"\d+", text) if 1 <= int(n) <= len(metas)}
    if keep:
        return [metas[i - 1] for i in sorted(keep)]
    if text.upper().startswith("NONE"):
        return []
    return metas  # unparseable reply → keep all rather than silently dropping everything


def _reformulate(query: str) -> str:
    """Rewrite the user's question into a focused runbook search query."""
    res = _groq().invoke(
        [
            SystemMessage(
                content=(
                    "Rewrite the user's question into a concise keyword search query for an internal "
                    "ops runbook knowledge base. Reply with ONLY the query text."
                )
            ),
            HumanMessage(content=query),
        ]
    )
    return (res.content or query).strip() or query


def corrective_retrieve(query: str, k: int):
    """Retrieve → grade; if nothing relevant, reformulate and retry once. Returns relevant chunk metas."""
    relevant = _grade_chunks(query, pinecone_retrieve(query, k))
    if relevant:
        return relevant
    return _grade_chunks(query, pinecone_retrieve(_reformulate(query), k))


def make_boto_session(region, access_key_id, secret_access_key, session_token=None, role_arn=None, external_id=None):
    base = boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token or None,
        region_name=region,
    )
    if role_arn:
        params = {"RoleArn": role_arn, "RoleSessionName": "cloud-ops-ui"}
        if external_id:
            params["ExternalId"] = external_id
        creds = base.client("sts").assume_role(**params)["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
    return base


def resolve_session(auth_id):
    _sweep_sessions()
    if not auth_id or auth_id not in _sessions:
        return None
    sess = _sessions[auth_id]
    if time.time() - sess["last"] > SESSION_TTL:
        _drop_session(auth_id)
        return None
    sess["last"] = time.time()
    return sess


class AuthIn(BaseModel):
    region: str = "us-east-1"
    accessKeyId: str
    secretAccessKey: str
    sessionToken: str | None = None
    roleArn: str | None = None
    externalId: str | None = None


class ChatIn(BaseModel):
    question: str
    sessionId: str | None = None


app = FastAPI(title="Cloud Ops agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "provider": "pinecone+groq+aws-tools",
        "model": GROQ_MODEL,
        "index": PINECONE_INDEX,
        "sessions": len(_sessions),
        "configured": bool(os.environ.get("GROQ_API_KEY") and os.environ.get("PINECONE_API_KEY")),
        "tracing": {
            # env vars present in THIS container? (proves Render passed them in)
            "configured": bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")),
            "host": os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com (default)"),
            # handler built yet? (happens on first chat once configured)
            "active": _lf_handler is not None,
        },
    }


@app.post("/api/auth")
def auth(body: AuthIn):
    if not body.accessKeyId or not body.secretAccessKey:
        return JSONResponse(status_code=400, content={"error": "accessKeyId and secretAccessKey are required."})
    try:
        boto_session = make_boto_session(
            body.region, body.accessKeyId, body.secretAccessKey,
            body.sessionToken, body.roleArn, body.externalId,
        )
        arn = boto_session.client("sts").get_caller_identity()["Arn"]
    except Exception as err:  # noqa: BLE001
        return JSONResponse(status_code=401, content={"error": str(err)})

    auth_id = uuid.uuid4().hex
    _sessions[auth_id] = {"boto": boto_session, "region": body.region, "arn": arn, "last": time.time()}
    return {"authSessionId": auth_id, "identityArn": arn, "region": body.region}


@app.post("/api/logout")
def logout(x_auth_session: str | None = Header(default=None)):
    if x_auth_session:
        _drop_session(x_auth_session)
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatIn, x_auth_session: str | None = Header(default=None)):
    session = resolve_session(x_auth_session)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "Not signed in. Connect your AWS account first."})

    question = (body.question or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"error": 'A non-empty "question" is required.'})

    captured = {"citations": []}

    def search_runbooks_fn(query: str) -> str:
        # Corrective RAG: retrieve, grade for relevance, reformulate + retry if weak.
        try:
            metas = corrective_retrieve(query, TOP_K)
        except Exception as e:  # noqa: BLE001 - a retrieval blip shouldn't 502 the whole chat
            print(f"[search_runbooks] error: {e}")
            return "The runbook knowledge base is temporarily unavailable — answer from AWS data, or tell the user you couldn't reach the runbooks."
        # Accumulate citations across multiple searches in a turn (dedupe by source+text).
        for md in metas:
            cite = {"text": md.get("text", ""), "source": md.get("source"), "uri": None}
            if cite not in captured["citations"]:
                captured["citations"].append(cite)
        if not metas:
            return "No relevant runbook content found."
        return "\n\n".join(f"[{i + 1}] ({md.get('source')})\n{md.get('text', '')}" for i, md in enumerate(metas))

    try:
        tools = build_tools(session["boto"], session["region"], search_runbooks_fn, allow_mutations=ALLOW_MUTATIONS)
        agent = create_react_agent(_groq(), tools, prompt=SYSTEM_PROMPT, checkpointer=_memory)
        # thread_id = the user's auth session → the agent remembers prior turns.
        # callbacks → Langfuse tracing when configured (each tool call + LLM call is traced).
        config = {
            "configurable": {"thread_id": x_auth_session},
            "recursion_limit": 2 * MAX_TOOL_LOOPS,
            "callbacks": _langfuse_callbacks(),
        }

        # Only resume if the graph is genuinely paused awaiting an action confirmation
        # (a confirm_action interrupt) — NOT merely a thread left pending by a prior
        # crash/recursion-limit, which must not swallow the user's next message.
        interrupts = getattr(agent.get_state(config), "interrupts", ()) or ()
        awaiting_confirm = any(
            isinstance(i.value, dict) and i.value.get("type") == "confirm_action" for i in interrupts
        )
        if awaiting_confirm:
            verdict = _classify_confirmation(question)
            if verdict == "other":
                # User moved on: cancel the pending action, then process the new message.
                agent.invoke(Command(resume={"confirmed": False}), config=config)
                result = agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)
            else:
                result = agent.invoke(Command(resume={"confirmed": verdict == "affirm"}), config=config)
        else:
            result = agent.invoke({"messages": [HumanMessage(content=question)]}, config=config)

        # A pending interrupt means the agent staged an action and needs confirmation.
        pending = result.get("__interrupt__")
        if pending:
            value = pending[0].value
            answer = value.get("prompt") if isinstance(value, dict) else str(value)
        else:
            answer = result["messages"][-1].content

        return {"answer": answer, "citations": captured["citations"], "sessionId": None}
    except Exception as err:  # noqa: BLE001
        print(f"[chat] error: {err}")
        return JSONResponse(status_code=502, content={"error": str(err)})


# --- Serve the built Angular app (populated into ./static by the Docker build) ---
# Guarded so local dev (where ./static doesn't exist) still uses `ng serve`.
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(_STATIC_DIR):

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # API routes are matched before this catch-all; anything else is the SPA.
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "Not found."})
        candidate = os.path.join(_STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))  # SPA deep-link fallback
