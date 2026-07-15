import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readFileSync, existsSync } from 'node:fs';
import dotenv from 'dotenv';
import cors from 'cors';
import express from 'express';
import Groq from 'groq-sdk';
import { pipeline } from '@huggingface/transformers';

const __dirname = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(__dirname, '.env') });

const {
  PORT = 3001,
  GROQ_API_KEY,
  // Groq model id — check https://console.groq.com/docs/models for current names.
  GROQ_MODEL = 'llama-3.3-70b-versatile',
  EMBED_MODEL = 'Xenova/all-MiniLM-L6-v2',
  TOP_K = 5
} = process.env;

const INDEX_PATH = join(__dirname, 'index.json');

// Load the prebuilt vector index (chunks + embeddings) produced by ingest.js.
let index = { model: EMBED_MODEL, chunks: [] };
if (existsSync(INDEX_PATH)) {
  index = JSON.parse(readFileSync(INDEX_PATH, 'utf8'));
} else {
  console.warn('No index.json found — run `npm run ingest` first.');
}

const groq = GROQ_API_KEY ? new Groq({ apiKey: GROQ_API_KEY }) : null;

// The embedder is loaded lazily on the first query (model init takes a moment).
let embedderPromise = null;
function getEmbedder() {
  if (!embedderPromise) {
    embedderPromise = pipeline('feature-extraction', index.model || EMBED_MODEL);
  }
  return embedderPromise;
}

async function embed(text) {
  const extractor = await getEmbedder();
  const out = await extractor(text, { pooling: 'mean', normalize: true });
  return Array.from(out.data);
}

// Embeddings are L2-normalized, so a dot product IS the cosine similarity.
function dot(a, b) {
  let sum = 0;
  for (let i = 0; i < a.length; i++) sum += a[i] * b[i];
  return sum;
}

async function retrieve(question, k) {
  const q = await embed(question);
  const scored = index.chunks.map((c) => ({ ...c, score: dot(q, c.embedding) }));
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, k);
}

async function answer(question) {
  const top = await retrieve(question, Number(TOP_K));
  const citations = top.map((c) => ({ text: c.text, source: c.source, uri: null }));

  const context = top.map((c, i) => `[${i + 1}] (${c.source})\n${c.text}`).join('\n\n');

  const completion = await groq.chat.completions.create({
    model: GROQ_MODEL,
    temperature: 0.2,
    max_tokens: 1024,
    messages: [
      {
        role: 'system',
        content:
          'You are a Cloud Ops assistant that answers questions about the team\'s runbooks ' +
          '(deployments, incidents, databases, scaling, monitoring, access).\n' +
          '- If the user greets you or makes small talk (e.g. "hi", "thanks"), reply briefly ' +
          'and warmly and invite them to ask about those topics.\n' +
          '- For a genuine question, answer using ONLY the numbered context passages below. ' +
          "If the answer is not contained in them, say you don't know rather than guessing. " +
          'Cite passages inline like [1], [2].\n' +
          'Never mention the words "context passages" to the user — just answer naturally.'
      },
      {
        role: 'user',
        content: `Context passages:\n${context}\n\nQuestion: ${question}`
      }
    ]
  });

  const text = completion.choices?.[0]?.message?.content?.trim() ?? '';
  // sessionId kept for the frontend contract; retrieval here is stateless.
  return { answer: text, citations, sessionId: null };
}

const app = express();
app.use(cors());
app.use(express.json());

app.get('/api/health', (_req, res) => {
  res.json({
    ok: true,
    provider: 'groq',
    model: GROQ_MODEL,
    embedModel: index.model || EMBED_MODEL,
    chunks: index.chunks.length,
    configured: Boolean(GROQ_API_KEY)
  });
});

app.post('/api/chat', async (req, res) => {
  const question = (req.body?.question ?? '').toString().trim();
  if (!question) {
    res.status(400).json({ error: 'A non-empty "question" is required.' });
    return;
  }
  if (!groq) {
    res.status(500).json({ error: 'GROQ_API_KEY is not set in server/.env.' });
    return;
  }
  if (!index.chunks.length) {
    res.status(500).json({ error: 'Knowledge base is empty. Run `npm run ingest`.' });
    return;
  }

  try {
    res.json(await answer(question));
  } catch (err) {
    console.error('[chat] error:', err);
    res.status(502).json({ error: err?.message ?? 'Generation failed.' });
  }
});

app.listen(PORT, () => {
  console.log(
    `RAG backend on http://localhost:${PORT} (groq=${GROQ_MODEL}, chunks=${index.chunks.length})`
  );
});
