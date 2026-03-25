---
name: cc-search
description: Search your Claude Code session history by keyword or semantic meaning. Use when asked about past Claude Code sessions, what was worked on, past experiments, decisions made, or any research history.
---

# Claude Code Session Search

Use this skill when asked about past Claude Code sessions, research history, what was worked on, past experiments, or anything that might be in the session archive.

## When to use
- "what did I work on yesterday/last week/recently?"
- "find sessions about [topic]"
- "what did I decide about [X]?"
- "have I worked on [topic] before?"
- "show me my recent Claude Code sessions"
- "what experiments have I run?"
- "find everything about [topic]"

## Two search modes

### 1. Keyword search (fast, use for dates/specific terms)
Use the terminal tool to query SQLite:

```bash
sqlite3 ~/cc-indexer/cc.db "
SELECT s.session_id, s.project, s.date, s.summary
FROM cc_sessions s
ORDER BY s.date DESC
LIMIT 10;
"
```

For keyword search across content:
```bash
sqlite3 ~/cc-indexer/cc.db "
SELECT s.session_id, s.project, s.date, s.summary
FROM cc_sessions s
JOIN cc_search cs ON s.session_id = cs.session_id
WHERE cc_search MATCH 'YOUR_SEARCH_TERM'
ORDER BY rank
LIMIT 5;
"
```

For recent sessions (e.g. last 7 days):
```bash
sqlite3 ~/cc-indexer/cc.db "
SELECT session_id, project, date, summary
FROM cc_sessions
WHERE date >= datetime('now', '-7 days')
ORDER BY date DESC;
"
```

### 2. Semantic search (for meaning-based queries)
Use the terminal tool to run a Python semantic search:

```bash
python3 -c "
import chromadb, requests
from pathlib import Path

# Embed the query
resp = requests.post('http://localhost:11434/api/embeddings',
    json={'model': 'nomic-embed-text', 'prompt': 'YOUR_QUERY_HERE'})
embedding = resp.json()['embedding']

# Search ChromaDB
client = chromadb.PersistentClient(path=str(Path.home() / 'chromadb'))
collection = client.get_collection('research')
results = collection.query(query_embeddings=[embedding], n_results=5)

for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'--- Result {i+1} ---')
    print(f'Project: {meta[\"project\"]}')
    print(f'Date: {meta[\"date\"]}')
    print(f'Summary: {doc}')
    print()
"
```

## After retrieving results

1. Read the summaries returned
2. Synthesize a clear answer to the question
3. Mention which projects/dates the relevant sessions came from
4. If more detail is needed on a specific session, query cc_events for raw content:

```bash
sqlite3 ~/cc-indexer/cc.db "
SELECT role, content FROM cc_events
WHERE session_id = 'SESSION_ID_HERE'
ORDER BY id LIMIT 20;
"
```

## Check index status
```bash
sqlite3 ~/cc-indexer/cc.db "
SELECT COUNT(*) as sessions FROM cc_sessions;
SELECT COUNT(*) as events FROM cc_events;
"
```

## Notes
- Sessions sync from MacBook every 5 minutes via rsync
- Indexing runs every 60 seconds
- If nothing found, Claude Code may not have been used on MacBook yet
- ChromaDB collection is named 'research'
- SQLite database is at ~/cc-indexer/cc.db
