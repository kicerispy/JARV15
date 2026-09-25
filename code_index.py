"""Incremental local FTS5 index for JARVIS source discovery.

The index is disposable cache state under .jarvis_autonomy. Source files remain
the authority; when FTS5 is unavailable, callers can fall back to direct scans.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from project_fs import iter_project_files
from healing_kernel import redact_sensitive
import config


INDEX_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
INDEX_PATH = INDEX_DIR / "code_index.sqlite3"

MAX_FILES = 5000
MAX_FILE_BYTES = 2_000_000
SOURCE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".lua", ".json", ".yaml", ".yml", ".toml", ".md",
    ".bat", ".ps1", ".xml", ".ini", ".cfg",
}


def _connect() -> sqlite3.Connection:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INDEX_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            path UNINDEXED,
            content,
            tokenize='porter unicode61'
        )
        """
    )
    conn.commit()
    return conn


def _candidate_files(base: Path) -> list[Path]:
    items = []
    for path in iter_project_files(base):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        items.append(path)
        if len(items) >= MAX_FILES:
            break
    return items


def rebuild() -> dict[str, Any]:
    """Rebuild the entire source index from the current project."""
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
                relative = str(path.relative_to(base)).replace("\\", "/")
                try:
                    stat = path.stat()
                    text = path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                except OSError:
                    skipped += 1
                    continue

                conn.execute(
                    "INSERT OR REPLACE INTO files(path, mtime_ns, size) VALUES (?, ?, ?)",
                    (relative, int(stat.st_mtime_ns), int(stat.st_size)),
                )
                conn.execute(
                    "INSERT INTO files_fts(path, content) VALUES (?, ?)",
                    (relative, text[:MAX_FILE_BYTES]),
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
            "message": f"Code index rebuild failed: {redact_sensitive(exc, 500)}",
            "path": str(INDEX_PATH),
        }


def _sync_if_needed(base: Path, conn: sqlite3.Connection) -> None:
    current = _candidate_files(base)
    current_map = {
        str(path.relative_to(base)).replace("\\", "/"): path
        for path in current
    }

    rows = conn.execute(
        "SELECT path, mtime_ns, size FROM files"
    ).fetchall()

    indexed_map = {
        str(row["path"]): (int(row["mtime_ns"]), int(row["size"]))
        for row in rows
    }

    for relative, path in current_map.items():
        try:
            stat = path.stat()
        except OSError:
            continue

        signature = (int(stat.st_mtime_ns), int(stat.st_size))
        if indexed_map.get(relative) == signature:
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        conn.execute("DELETE FROM files WHERE path = ?", (relative,))
        conn.execute("DELETE FROM files_fts WHERE path = ?", (relative,))
        conn.execute(
            "INSERT INTO files(path, mtime_ns, size) VALUES (?, ?, ?)",
            (relative, signature[0], signature[1]),
        )
        conn.execute(
            "INSERT INTO files_fts(path, content) VALUES (?, ?)",
            (relative, text[:MAX_FILE_BYTES]),
        )

    for relative in set(indexed_map) - set(current_map):
        conn.execute("DELETE FROM files WHERE path = ?", (relative,))
        conn.execute("DELETE FROM files_fts WHERE path = ?", (relative,))

    conn.commit()


def search(query: str, limit: int = 50) -> dict[str, Any]:
    """Search source using FTS5 and return line-oriented snippets."""
    query = str(query or "").strip()
    limit = max(1, min(int(limit or 50), 100))
    if not query:
        return {
            "success": False,
            "verified": False,
            "message": "Code search query cannot be empty.",
        }

    base = Path(getattr(config, "BASE_DIR", Path.cwd())).resolve()
    try:
        conn = _connect()
        try:
            if not INDEX_PATH.exists():
                raise sqlite3.OperationalError("index file missing")
            _sync_if_needed(base, conn)

            tokens = [
                token
                for token in __import__("re").findall(
                    r"[A-Za-z0-9_]+",
                    query,
                )
                if len(token) >= 2
            ]
            if not tokens:
                return {
                    "success": False,
                    "verified": False,
                    "message": "Code search query did not contain searchable terms.",
                }

            match_query = " OR ".join(
                '"' + token.replace('"', '""') + '"'
                for token in tokens
            )
            rows = conn.execute(
                """
                SELECT path, bm25(files_fts) AS rank
                FROM files_fts
                WHERE files_fts MATCH ?
                ORDER BY bm25(files_fts)
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": "Code index unavailable; caller should use direct scan.",
        }

    matches = []
    for row in rows:
        relative = str(row["path"])
        path = (base / relative).resolve()
        try:
            path.relative_to(base)
            text = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, ValueError):
            continue

        lowered = query.lower()
        for line_number, line in enumerate(text.splitlines(), 1):
            if lowered in line.lower():
                matches.append(
                    f"{relative}:{line_number}: {line.strip()}"
                )
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
