import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import dotenv from 'dotenv';
import { pipeline } from '@huggingface/transformers';

const __dirname = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(__dirname, '.env') });

const DOCS_DIR = join(__dirname, '..', 'sample-docs');
const OUT_PATH = join(__dirname, 'index.json');
const EMBED_MODEL = process.env.EMBED_MODEL || 'Xenova/all-MiniLM-L6-v2';
const MAX_CHARS = 1000; // target chunk size

/**
 * Split markdown into ~MAX_CHARS chunks on paragraph boundaries. Keeps whole
 * paragraphs together so citations read as coherent passages.
 */
function chunkText(text, source) {
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);

  const chunks = [];
  let buffer = '';
  for (const p of paragraphs) {
    if (buffer && (buffer + '\n\n' + p).length > MAX_CHARS) {
      chunks.push(buffer.trim());
      buffer = p;
    } else {
      buffer = buffer ? buffer + '\n\n' + p : p;
    }
  }
  if (buffer.trim()) chunks.push(buffer.trim());

  return chunks.map((chunkText) => ({ text: chunkText, source }));
}

const files = readdirSync(DOCS_DIR).filter(
  (f) => f.endsWith('.md') && f.toLowerCase() !== 'readme.md'
);

const docs = [];
for (const file of files) {
  const text = readFileSync(join(DOCS_DIR, file), 'utf8');
  docs.push(...chunkText(text, file));
}

console.log(`Embedding ${docs.length} chunks from ${files.length} file(s) with ${EMBED_MODEL}...`);
const extractor = await pipeline('feature-extraction', EMBED_MODEL);

let done = 0;
for (const doc of docs) {
  const out = await extractor(doc.text, { pooling: 'mean', normalize: true });
  doc.embedding = Array.from(out.data);
  done += 1;
  if (done % 10 === 0 || done === docs.length) {
    console.log(`  ${done}/${docs.length}`);
  }
}

writeFileSync(OUT_PATH, JSON.stringify({ model: EMBED_MODEL, chunks: docs }));
console.log(`Wrote ${OUT_PATH} — ${docs.length} chunks indexed.`);
