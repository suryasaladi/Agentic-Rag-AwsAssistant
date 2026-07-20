"""
Optional: standardized RAG evaluation with RAGAS (LLM-as-judge).

This is the "production" evaluation option, kept separate from the app. It reuses
the app's retrieval + generation to build an evaluation dataset, then scores it
with RAGAS metrics (Faithfulness, Context Precision — both LLM-only, no embeddings).

⚠️ Requires Python 3.12 or 3.13 — RAGAS pulls deps (scikit-network) with no 3.14
   wheel. Install into a separate venv:
       python3.12 -m venv .venv-eval
       .venv-eval/Scripts/pip install -r requirements-eval.txt
       .venv-eval/Scripts/python eval_ragas.py
   Needs PINECONE_API_KEY + GROQ_API_KEY in .env.

For a zero-dependency alternative that runs on any Python, see eval.py (the
lightweight LLM-as-judge harness).
"""
import main
from eval import GOLDEN, generate
from langchain_groq import ChatGroq
from ragas import evaluate, EvaluationDataset
from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference
from ragas.llms import LangchainLLMWrapper


def build_dataset() -> EvaluationDataset:
    """Run the app's retrieval + generation over the in-scope golden questions."""
    rows = []
    for item in GOLDEN:
        if not item["in_scope"]:
            continue
        question = item["q"]
        metas = main.corrective_retrieve(question, main.TOP_K)
        rows.append(
            {
                "user_input": question,
                "response": generate(question, metas),
                "retrieved_contexts": [m.get("text", "") for m in metas] or ["(no context)"],
            }
        )
    return EvaluationDataset.from_list(rows)


def run() -> None:
    judge = LangchainLLMWrapper(ChatGroq(model=main.GROQ_MODEL, temperature=0))
    dataset = build_dataset()
    result = evaluate(
        dataset=dataset,
        metrics=[Faithfulness(), LLMContextPrecisionWithoutReference()],
        llm=judge,
    )
    print(result)                    # aggregate scores
    print(result.to_pandas())        # per-question breakdown


if __name__ == "__main__":
    run()
