"""
Lightweight RAG evaluation harness (LLM-as-judge) for the runbook retrieval path.

Metrics (over a small golden set):
  - Retrieval hit-rate : did top-K contain the expected source doc?  (retriever recall)
  - Faithfulness       : is every claim in the answer supported by the context? (LLM judge)
  - Answer relevance   : does the answer address the question? (LLM judge)
  - Correct refusal    : for out-of-scope questions, does it say "I don't know"?

Reuses main.py (Pinecone + Groq). Needs PINECONE_API_KEY + GROQ_API_KEY in .env.
Run from the backend/ dir:  python eval.py
"""
import main
from langchain_core.messages import SystemMessage, HumanMessage

# Golden set: question -> which runbook(s) should answer it (in_scope=False → should refuse).
GOLDEN = [
    {"q": "What is the rollback procedure for a failed deploy?", "sources": ["deploy-and-rollback.md"], "in_scope": True},
    {"q": "What error rate is considered unhealthy during a deploy?", "sources": ["deploy-and-rollback.md", "monitoring-and-alerts.md"], "in_scope": True},
    {"q": "Who do I contact for a SEV1 incident and how fast must it be acknowledged?", "sources": ["incident-response.md"], "in_scope": True},
    {"q": "How do I restore the orders database to a specific point in time?", "sources": ["database-operations.md"], "in_scope": True},
    {"q": "What are the autoscaling minimum and maximum replicas?", "sources": ["scaling-and-capacity.md"], "in_scope": True},
    {"q": "How often are database credentials rotated?", "sources": ["access-and-secrets.md"], "in_scope": True},
    {"q": "What TLS certificate expiry threshold triggers an alert?", "sources": ["monitoring-and-alerts.md"], "in_scope": True},
    {"q": "What Kubernetes ingress controller do we use?", "sources": [], "in_scope": False},
    {"q": "What is our AWS account root password?", "sources": [], "in_scope": False},
]

GROUNDING_SYSTEM = (
    "You are a Cloud Ops assistant. Answer the question using ONLY the numbered context "
    "passages. If the answer is not contained in them, say you don't know. Cite like [1], [2]."
)


def generate(question: str, metas: list) -> str:
    context = "\n\n".join(
        f"[{i + 1}] ({m.get('source')})\n{m.get('text', '')}" for i, m in enumerate(metas)
    )
    msg = main._groq().invoke(
        [SystemMessage(content=GROUNDING_SYSTEM),
         HumanMessage(content=f"Context:\n{context or '(no context)'}\n\nQuestion: {question}")]
    )
    return (msg.content or "").strip()


def _judge_yes(system: str, human: str) -> bool:
    r = main._groq().invoke([SystemMessage(content=system), HumanMessage(content=human)])
    return (r.content or "").strip().upper().startswith("YES")


def faithful(context: str, answer: str) -> bool:
    return _judge_yes(
        "Grader. Reply ONLY 'YES' or 'NO'. Is every factual claim in the ANSWER supported by the CONTEXT?",
        f"CONTEXT:\n{context}\n\nANSWER:\n{answer}",
    )


def relevant(question: str, answer: str) -> bool:
    return _judge_yes(
        "Grader. Reply ONLY 'YES' or 'NO'. Does the ANSWER directly address the QUESTION?",
        f"QUESTION: {question}\n\nANSWER: {answer}",
    )


def is_refusal(answer: str) -> bool:
    a = answer.lower()
    return any(
        p in a for p in
        ["don't know", "dont know", "do not know", "not contained", "not in the",
         "no relevant", "couldn't find", "could not find", "not available", "not covered", "unable to"]
    )


def main_eval() -> None:
    k = main.TOP_K
    hit, faith, rel, refuse = [], [], [], []
    print(f"Evaluating {len(GOLDEN)} questions (top_k={k}, model={main.GROQ_MODEL})\n")

    for item in GOLDEN:
        q = item["q"]
        retrieved = main.pinecone_retrieve(q, k)          # raw retriever recall
        got_sources = {m.get("source") for m in retrieved}
        answer = generate(q, main.corrective_retrieve(q, k))  # answer from the corrective path
        context = "\n\n".join(m.get("text", "") for m in retrieved)

        if item["in_scope"]:
            h = any(s in got_sources for s in item["sources"])
            f = faithful(context, answer)
            r = relevant(q, answer)
            hit.append(h); faith.append(f); rel.append(r)
            print(f"[in]  hit={'Y' if h else 'N'} faith={'Y' if f else 'N'} rel={'Y' if r else 'N'} | {q}")
        else:
            ok = is_refusal(answer)
            refuse.append(ok)
            print(f"[out] refused={'Y' if ok else 'N'} | {q}\n      -> {answer[:90]}")

    def pct(xs):
        return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "n/a"

    print("\n=== RESULTS ===")
    print(f"Retrieval hit-rate : {pct(hit)}")
    print(f"Faithfulness       : {pct(faith)}")
    print(f"Answer relevance   : {pct(rel)}")
    print(f"Correct refusal    : {pct(refuse)}")


if __name__ == "__main__":
    main_eval()
