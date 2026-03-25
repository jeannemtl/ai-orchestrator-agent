#!/usr/bin/env python3
"""
ingest.py — Claude Code session indexer for Jeanne's Mac mini
Watches ~/cc-history/ for new sessions, summarizes with Qwen,
embeds with nomic-embed-text, stores in ChromaDB + SQLite FTS5.
"""

import os
import json
import sqlite3
import hashlib
import requests
import chromadb
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
CC_HISTORY = Path.home() / "cc-history"
CHROMADB_PATH = Path.home() / "chromadb"
SQLITE_PATH = Path.home() / "cc-indexer" / "cc.db"
CURSOR_PATH = Path.home() / "cc-indexer" / "cursor.json"
OLLAMA_URL = "http://localhost:11434"
QWEN_MODEL = "qwen2.5:14b"
EMBED_MODEL = "nomic-embed-text"

# ── Setup ─────────────────────────────────────────────────────────────────────
def setup():
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # SQLite with FTS5
    conn = sqlite3.connect(SQLITE_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cc_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            project TEXT NOT NULL,
            timestamp TEXT,
            role TEXT,
            content TEXT,
            tool_name TEXT,
            tool_args TEXT,
            file_hash TEXT UNIQUE
        );
        
        CREATE TABLE IF NOT EXISTS cc_sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT,
            date TEXT,
            summary TEXT,
            indexed_at TEXT
        );
        
        CREATE VIRTUAL TABLE IF NOT EXISTS cc_search
        USING fts5(session_id, project, content, tool_name, summary);
    """)
    conn.commit()
    conn.close()
    
    # ChromaDB
    chroma = chromadb.PersistentClient(path=str(CHROMADB_PATH))
    collection = chroma.get_or_create_collection("research")
    return collection

# ── Cursor (tracks what's been processed) ─────────────────────────────────────
def load_cursor():
    if CURSOR_PATH.exists():
        return json.loads(CURSOR_PATH.read_text())
    return {}

def save_cursor(cursor):
    CURSOR_PATH.write_text(json.dumps(cursor, indent=2))

# ── Ollama helpers ─────────────────────────────────────────────────────────────
def summarize(text):
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": QWEN_MODEL,
            "prompt": f"""You are a research assistant. Summarize this Claude Code session for a researcher's knowledge base.
Extract: (1) what problem was being solved, (2) approach taken, (3) what worked, (4) decisions made, (5) open questions.
Keep it under 200 words. Be specific and technical.

SESSION:
{text[:6000]}

SUMMARY:""",
            "stream": False
        }, timeout=120)
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"  ⚠ Summarization failed: {e}")
        return text[:500]

def embed(text):
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/embeddings", json={
            "model": EMBED_MODEL,
            "prompt": text
        }, timeout=30)
        return resp.json().get("embedding", [])
    except Exception as e:
        print(f"  ⚠ Embedding failed: {e}")
        return []

# ── Parse JSONL session ───────────────────────────────────────────────────────
def parse_session(jsonl_path):
    events = []
    try:
        with open(jsonl_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    events.append(obj)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  ⚠ Could not read {jsonl_path}: {e}")
    return events

def extract_text(events):
    """Pull readable content from session events."""
    parts = []
    for e in events:
        msg = e.get("message", {})
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if isinstance(content, str) and content.strip():
            parts.append(f"[{role}] {content.strip()}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(f"[{role}] {block.get('text','').strip()}")
                    elif block.get("type") == "tool_use":
                        tool = block.get("name", "")
                        inp = json.dumps(block.get("input", {}))[:200]
                        parts.append(f"[tool:{tool}] {inp}")
                    elif block.get("type") == "tool_result":
                        result = str(block.get("content", ""))[:200]
                        parts.append(f"[tool_result] {result}")
    return "\n".join(parts)

# ── Index a single session file ───────────────────────────────────────────────
def index_session(jsonl_path, project, collection, cursor):
    session_id = jsonl_path.stem
    file_key = str(jsonl_path)
    
    # Check if already indexed
    stat = jsonl_path.stat()
    file_sig = f"{stat.st_size}:{stat.st_mtime}"
    if cursor.get(file_key) == file_sig:
        return False  # unchanged
    
    print(f"  📄 Indexing: {project}/{session_id}")
    
    events = parse_session(jsonl_path)
    if not events:
        return False
    
    # Extract text content
    text = extract_text(events)
    if not text.strip():
        return False
    
    # Insert raw events into SQLite
    conn = sqlite3.connect(SQLITE_PATH)
    for i, e in enumerate(events):
        msg = e.get("message", {})
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content)
        content_str = str(content)[:2000]
        
        file_hash = hashlib.md5(f"{session_id}:{i}".encode()).hexdigest()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO cc_events 
                (session_id, project, timestamp, role, content, file_hash)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, project, e.get("timestamp", ""), role, content_str, file_hash))
        except Exception:
            pass
    conn.commit()
    
    # Summarize with Qwen
    print(f"    🧠 Summarizing with Qwen...")
    summary = summarize(text)
    
    # Store session summary in SQLite
    date = datetime.now().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO cc_sessions (session_id, project, date, summary, indexed_at)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, project, date, summary, date))
    
    # Update FTS5 search index
    conn.execute("""
        INSERT INTO cc_search (session_id, project, content, tool_name, summary)
        VALUES (?, ?, ?, ?, ?)
    """, (session_id, project, text[:5000], "", summary))
    
    conn.commit()
    conn.close()
    
    # Embed and store in ChromaDB
    print(f"    🔢 Embedding...")
    embedding = embed(summary)
    if embedding:
        doc_id = f"cc_{session_id}"
        try:
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{
                    "type": "claude_code_session",
                    "project": project,
                    "session_id": session_id,
                    "date": date
                }]
            )
        except Exception as e:
            print(f"    ⚠ ChromaDB upsert failed: {e}")
    
    # Update cursor
    cursor[file_key] = file_sig
    print(f"    ✅ Done: {session_id[:20]}...")
    return True

# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    print(f"🔍 Ingest started at {datetime.now().strftime('%H:%M:%S')}")
    
    if not CC_HISTORY.exists():
        print(f"  ℹ No cc-history directory yet at {CC_HISTORY}")
        return
    
    collection = setup()
    cursor = load_cursor()
    indexed = 0
    
    # Walk all project directories
    for project_dir in CC_HISTORY.iterdir():
        if not project_dir.is_dir():
            continue
        project = project_dir.name
        
        # Find all JSONL session files
        for jsonl_path in sorted(project_dir.glob("*.jsonl")):
            try:
                if index_session(jsonl_path, project, collection, cursor):
                    indexed += 1
                    save_cursor(cursor)
            except Exception as e:
                print(f"  ⚠ Failed to index {jsonl_path}: {e}")
    
    if indexed:
        print(f"\n✅ Indexed {indexed} new/updated sessions")
    else:
        print(f"  ℹ Nothing new to index")
    
    save_cursor(cursor)

if __name__ == "__main__":
    main()
