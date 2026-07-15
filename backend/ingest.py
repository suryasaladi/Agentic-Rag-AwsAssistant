"""
Ingestion: load docs from an S3 prefix, chunk them, embed via Pinecone's hosted
inference, and upsert into a Pinecone index.

Run once (and again whenever the S3 docs change):  python ingest.py

Notes on the stack (Python 3.14 constraints):
- We load from S3 with boto3 rather than LangChain's S3DirectoryLoader, which
  needs `unstructured` (no 3.14 wheel; pulls an un-buildable old NumPy).
- We use the official `pinecone` client rather than `langchain-pinecone`, which
  hard-pins numpy<2 (also no 3.14 wheel).
- Chunking still uses LangChain's RecursiveCharacterTextSplitter.
"""
import os
import time
import boto3
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]
S3_PREFIX = os.environ.get("S3_PREFIX", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
PINECONE_INDEX = os.environ.get("PINECONE_INDEX", "rag-poc")
EMBED_MODEL = os.environ.get("PINECONE_EMBED_MODEL", "multilingual-e5-large")
EMBED_DIMS = {"multilingual-e5-large": 1024, "llama-text-embed-v2": 1024}

TEXT_EXTENSIONS = (".md", ".markdown", ".txt")
EMBED_BATCH = 90  # Pinecone inference input cap per call


def load_s3_documents():
    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )
    docs = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or not key.lower().endswith(TEXT_EXTENSIONS):
                continue
            text = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read().decode("utf-8", "ignore")
            docs.append({"text": text, "source": key.split("/")[-1], "s3_key": key})
    return docs


def main() -> None:
    docs = load_s3_documents()
    print(f"Loaded {len(docs)} document(s) from s3://{S3_BUCKET}/{S3_PREFIX}")
    if not docs:
        print("No .md/.txt objects found under that prefix — check S3_BUCKET/S3_PREFIX/creds.")
        return

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = []
    for doc in docs:
        for i, piece in enumerate(splitter.split_text(doc["text"])):
            chunks.append({"id": f"{doc['s3_key']}#{i}", "text": piece, "source": doc["source"]})
    print(f"Split into {len(chunks)} chunk(s)")

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])

    if PINECONE_INDEX not in [ix["name"] for ix in pc.list_indexes()]:
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=EMBED_DIMS.get(EMBED_MODEL, 1024),
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print(f"Created Pinecone index '{PINECONE_INDEX}' — waiting for it to be ready...")
        while not pc.describe_index(PINECONE_INDEX)["status"]["ready"]:
            time.sleep(1)

    index = pc.Index(PINECONE_INDEX)

    vectors = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        embeddings = pc.inference.embed(
            model=EMBED_MODEL,
            inputs=[c["text"] for c in batch],
            parameters={"input_type": "passage", "truncate": "END"},
        )
        for chunk, emb in zip(batch, embeddings.data):
            vectors.append(
                {
                    "id": chunk["id"],
                    "values": emb["values"],
                    "metadata": {"text": chunk["text"], "source": chunk["source"]},
                }
            )

    index.upsert(vectors=vectors)
    print(f"Upserted {len(vectors)} vector(s) into '{PINECONE_INDEX}'. Done.")


if __name__ == "__main__":
    main()
