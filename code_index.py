"""Incremental local SQLite FTS5 source index for fast JARVIS code discovery."""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import config
from project_fs import iter_project_files


INDEX_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
INDEX_PATH = INDEX_DIR / "code_index.sqlite3"
MAX_FILES = 5000
MAX_FILE_BYTES = 2_000_000
SOURCE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".lua",
    ".json", ".yaml", ".yml", ".toml", ".md", ".bat", ".ps1", ".xml",
}


def _connect() -> sqlite3.Connection:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INDEX_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS files "
        "(path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5("
        "path UNINDEXED, content, tokenize='porter unicode61')"
    )
    conn.commit()
    return conn


def _candidate_files(base: Path) -> list[Path]:
    out: list[Path] = []
    for path in iter_project_files(base):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(path)
        if len(out) >= MAX_FILES:
            break
    return out


def rebuild() -> dict[str, Any]:
    base = Path(getattr(config, "BASE_DIR", Path.cwd())).resolve()
    started = time.perf_counter()
    try:
        conn = _connect()
        try:
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM files_fts")
            indexed = 0
            skipped = 0
            for path in _candidate_files(base):
                rel = str(path.relative_to(base)).replace("\\", "/")
                try:
                    stat = path.stat()
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT INTO files(path, mtime_ns, size) VALUES (?, ?, ?)",
                    (rel, int(stat.st_mtime_ns), int(stat.st_size)),
                )
                conn.execute(
                    "INSERT INTO files_fts(path, content) VALUES (?, ?)",
                    (rel, text[:MAX_FILE_BYTES]),
                )
                indexed += 1
            conn.commit()
        finally:
            conn.close()
        return {
            "success": True,
            "verified": True,
            "indexed": indexed,
            "skipped": skipped,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "path": str(INDEX_PATH),
        }
    except (OSError, sqlite3.Error) as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": f"Code index rebuild failed: {exc}",
            "path": str(INDEX_PATH),
        }


def _sync(base: Path, conn: sqlite3.Connection) -> None:
    current = {
        str(p.relative_to(base)).replace("\\", "/"): p
        for p in _candidate_files(base)
    }
    rows = conn.execute("SELECT path, mtime_ns, size FROM files").fetchall()
    indexed = {
        str(row["path"]): (int(row["mtime_ns"]), int(row["size"]))
        for row in rows
    }

    for rel, path in current.items():
        try:
            stat = path.stat()
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            continue
        if indexed.get(rel) == signature:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        conn.execute("DELETE FROM files WHERE path = ?", (rel,))
        conn.execute("DELETE FROM files_fts WHERE path = ?", (rel,))
        conn.execute(
            "INSERT INTO files(path, mtime_ns, size) VALUES (?, ?, ?)",
            (rel, signature[0], signature[1]),
        )
        conn.execute(
            "INSERT INTO files_fts(path, content) VALUES (?, ?)",
            (rel, text[:MAX_FILE_BYTES]),
        )

    for rel in set(indexed) - set(current):
        conn.execute("DELETE FROM files WHERE path = ?", (rel,))
        conn.execute("DELETE FROM files_fts WHERE path = ?", (rel,))
    conn.commit()


def search(query: str, limit: int = 50) -> dict[str, Any]:
    query = str(query or "").strip()
    limit = max(1, min(int(limit or 50), 100))
    if not query:
        return {"success": False, "verified": False, "message": "Code search query cannot be empty."}

    tokens = [t for t in re.findall(r"[A-Za-z0-9_]+", query) if len(t) >= 2]
    if not tokens:
        return {
            "success": False,
            "verified": False,
            "message": "Code search query did not contain searchable terms.",
        }

    base = Path(getattr(config, "BASE_DIR", Path.cwd())).resolve()
    try:
        conn = _connect()
        try:
            _sync(base, conn)
            match_query = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
            rows = conn.execute(
                "SELECT path, bm25(files_fts) AS rank "
                "FROM files_fts WHERE files_fts MATCH ? "
                "ORDER BY bm25(files_fts) LIMIT ?",
                (match_query, limit),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": f"Code index unavailable: {exc}",
        }

    matches: list[str] = []
    lowered = query.lower()
    for row in rows:
        rel = str(row["path"])
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if lowered in line.lower():
                matches.append(f"{rel}:{line_no}: {line.strip()}")
                if len(matches) >= limit:
                    break
        if len(matches) >= limit:
            break

    return {
        "success": True,
        "verified": True,
        "query": query,
        "matches": matches,
        "count": len(matches),
        "indexed_candidates": len(rows),
        "index": str(INDEX_PATH),
    }


def status() -> dict[str, Any]:
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS count FROM files").fetchone()
        finally:
            conn.close()
        return {
            "success": True,
            "verified": True,
            "indexed_files": int(row["count"] or 0),
            "path": str(INDEX_PATH),
            "fts5": True,
        }
    except (OSError, sqlite3.Error) as exc:
        return {
            "success": False,
            "verified": False,
            "fts5": False,
            "message": str(exc)[:500],
            "path": str(INDEX_PATH),
        }


__all__ = ["rebuild", "search", "status"]
