# ingest.py — Claude Code Session Indexer

Part of the AI Research Machine setup guide.

Watches `~/cc-history/` for new Claude Code sessions, summarizes each one 
with Qwen2.5-14B via Ollama, embeds the summary with nomic-embed-text, 
and stores everything in SQLite (keyword search) and ChromaDB (semantic search).

## What it does

- Parses Claude Code JSONL session files as they arrive
- Inserts raw events into SQLite with FTS5 full-text search
- Summarizes each completed session with Qwen2.5-14B (local, free, private)
- Converts summaries to vectors with nomic-embed-text
- Stores vectors in ChromaDB for semantic/meaning-based search
- Tracks a cursor so it never re-processes sessions it has already indexed

## Requirements

- Mac mini M4 (or any Apple Silicon Mac)
- Ollama running with `qwen2.5:14b` and `nomic-embed-text` pulled
- ChromaDB installed: `pip3 install chromadb`
- Python 3.9+

## Setup

Follow the full setup guide (available at quaintance4.gumroad.com/l/ai-research-machine).

Quick start:
```bash
