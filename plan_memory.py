"""Local memory of successful JARVIS execution strategies."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import config

_DB_DIR = Path(getattr(config, "BASE_DIR", Path("."))) / ".jarvis_autonomy"
_DB_PATH = _DB_DIR / "plan_memory.sqlite3"
_MAX_STRATEGIES = 750
_MAX_EVENTS_PER_STRATEGY = 100
_LOCK = threading.RLock()
_SCHEMA_READY = False


_STOPWORDS = {
    "a", "an", "and", "are", "can", "could", "for", "from", "how", "i",
    "in", "is", "it", "me", "my", "of", "on", "please", "the", "this",
    "to", "what", "when", "where", "with", "you", "your",
}


def _tokens(text: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_'-]+", str(text or "").lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def normalize_request(text: Any) -> str:
    tokens = sorted(_tokens(text))
    return " ".join(tokens[:48])


def detect_domain(request: str, context: dict[str, Any] | None = None) -> str:
    context = context if isinstance(context, dict) else {}
    site = str(context.get("site", "") or "").strip().lower()
    if site:
        return site[:64]

    lowered = str(request or "").lower()
    if any(term in lowered for term in ("browser", "chrome", "google", "youtube", "website")):
        return "browser"
    if any(term in lowered for term in ("roblox", "luau", "studio", "playtest")):
        return "roblox"
    if any(term in lowered for term in ("code", "python", "repository", "git", "pytest", "repair")):
        return "code"
    if "n8n" in lowered or "workflow" in lowered:
        return "n8n"
    return "general"


def _safe_argument(argument: Any) -> str:
    text = str(argument or "").strip()
    text = re.sub(
        r"(?i)(authorization|api[_ -]?key|token|password|secret)\\s*[=:]\\s*\\S+",
        r"\\1=<redacted>",
        text,
    )
    return text[:1600]


def _argument_shape(argument: Any) -> str:
    text = str(argument or "").strip()
    text = re.sub(r"https?://\S+", "<url>", text)
    text = re.sub(r"[A-Za-z]:\\[^\s|]+", "<path>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:300]


def plan_signature(request: str, plan: dict[str, Any] | None) -> str:
    steps = plan.get("steps", []) if isinstance(plan, dict) else []
    normalized_steps = []
    for step in steps[:32]:
        if not isinstance(step, dict):
            continue
        normalized_steps.append(
            (
                str(step.get("tool", "") or "").strip(),
                _argument_shape(step.get("argument", "")),
            )
        )

    material = json.dumps(
        {
            "request": normalize_request(request),
            "steps": normalized_steps,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _connect() -> sqlite3.Connection:
    global _SCHEMA_READY
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    connection.row_factory = sqlite3.Row
    if not _SCHEMA_READY:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategies (
                fingerprint TEXT PRIMARY KEY,
                request_key TEXT NOT NULL,
                request_text TEXT NOT NULL,
                domain TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                verified_successes INTEGER NOT NULL DEFAULT 0,
                total_attempts INTEGER NOT NULL DEFAULT 0,
                total_duration REAL NOT NULL DEFAULT 0,
                total_replans INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                last_success REAL NOT NULL DEFAULT 0,
                last_failure REAL NOT NULL DEFAULT 0,
                quarantined_until REAL NOT NULL DEFAULT 0,
                quarantine_reason TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS strategy_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                timestamp REAL NOT NULL,
                success INTEGER NOT NULL,
                verified INTEGER NOT NULL,
                duration REAL NOT NULL DEFAULT 0,
                replans INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_strategy_events_fp
                ON strategy_events(fingerprint, timestamp DESC);
            """
        )
        connection.commit()
        _SCHEMA_READY = True
    return connection


def _trim(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM strategies"
    ).fetchone()
    count = int(row["count"] or 0) if row else 0
    excess = count - _MAX_STRATEGIES
    if excess > 0:
        connection.execute(
            """
            DELETE FROM strategies
            WHERE fingerprint IN (
                SELECT fingerprint FROM strategies
                ORDER BY last_seen ASC
                LIMIT ?
            )
            """,
            (excess,),
        )


def record_strategy(
    request: str,
    plan: dict[str, Any],
    *,
    success: bool,
    verified: bool,
    duration_seconds: float = 0.0,
    replans: int = 0,
    error: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an execution outcome and update strategy aggregates."""
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        return {"recorded": False, "reason": "invalid plan"}

    context = context if isinstance(context, dict) else {}
    request_text = str(request or "").strip()[:1000]
    request_key = normalize_request(request_text)
    domain = detect_domain(request_text, context)
    fingerprint = plan_signature(request_text, plan)
    timestamp = time.time()

    steps = []
    for step in plan.get("steps", [])[:32]:
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "tool": str(step.get("tool", "") or "").strip()[:120],
                "argument": _safe_argument(step.get("argument", "")),
            }
        )

    safe_error = re.sub(
        r"(?i)(authorization|api[_ -]?key|token|password|secret)\s*[=:]\s*\S+",
        r"\1=<redacted>",
        str(error or "").strip(),
    )[:900]

    with _LOCK:
        with _connect() as connection:
            existing = connection.execute(
                "SELECT fingerprint FROM strategies WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()

            if existing:
                connection.execute(
                    """
                    UPDATE strategies
                    SET request_text=?,
                        request_key=?,
                        domain=?,
                        steps_json=?,
                        successes=successes + ?,
                        failures=failures + ?,
                        verified_successes=verified_successes + ?,
                        total_attempts=total_attempts + 1,
                        total_duration=total_duration + ?,
                        total_replans=total_replans + ?,
                        last_seen=?,
                        last_success=CASE WHEN ? THEN ? ELSE last_success END,
                        last_failure=CASE WHEN ? THEN ? ELSE last_failure END
                    WHERE fingerprint=?
                    """,
                    (
                        request_text,
                        request_key,
                        domain,
                        json.dumps(steps, ensure_ascii=False),
                        1 if success else 0,
                        0 if success else 1,
                        1 if success and verified else 0,
                        max(0.0, float(duration_seconds or 0.0)),
                        max(0, int(replans or 0)),
                        timestamp,
                        1 if success else 0,
                        timestamp,
                        0 if success else 1,
                        timestamp,
                        fingerprint,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO strategies(
                        fingerprint, request_key, request_text, domain,
                        steps_json, successes, failures, verified_successes,
                        total_attempts, total_duration, total_replans,
                        first_seen, last_seen, last_success, last_failure
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fingerprint,
                        request_key,
                        request_text,
                        domain,
                        json.dumps(steps, ensure_ascii=False),
                        1 if success else 0,
                        0 if success else 1,
                        1 if success and verified else 0,
                        1,
                        max(0.0, float(duration_seconds or 0.0)),
                        max(0, int(replans or 0)),
                        timestamp,
                        timestamp,
                        timestamp if success else 0.0,
                        0.0 if success else timestamp,
                    ),
                )

            connection.execute(
                """
                INSERT INTO strategy_events(
                    fingerprint, timestamp, success, verified,
                    duration, replans, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    timestamp,
                    1 if success else 0,
                    1 if verified else 0,
                    max(0.0, float(duration_seconds or 0.0)),
                    max(0, int(replans or 0)),
                    safe_error,
                ),
            )

            connection.execute(
                """
                DELETE FROM strategy_events
                WHERE fingerprint=?
                  AND id NOT IN (
                    SELECT id FROM strategy_events
                    WHERE fingerprint=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                  )
                """,
                (
                    fingerprint,
                    fingerprint,
                    _MAX_EVENTS_PER_STRATEGY,
                ),
            )
            _trim(connection)
            connection.commit()

    return {
        "recorded": True,
        "fingerprint": fingerprint,
        "request_key": request_key,
        "domain": domain,
    }


def _row_to_strategy(row: sqlite3.Row) -> dict[str, Any]:
    total = int(row["total_attempts"] or 0)
    successes = int(row["successes"] or 0)
    verified = int(row["verified_successes"] or 0)
    avg_duration = (
        float(row["total_duration"] or 0.0) / total
        if total
        else 0.0
    )
    avg_replans = (
        float(row["total_replans"] or 0.0) / total
        if total
        else 0.0
    )
    return {
        "fingerprint": row["fingerprint"],
        "request": row["request_text"],
        "request_key": row["request_key"],
        "domain": row["domain"],
        "steps": json.loads(row["steps_json"] or "[]"),
        "success_rate": round(successes / total, 4) if total else 0.0,
        "verified_rate": round(verified / total, 4) if total else 0.0,
        "successes": successes,
        "failures": int(row["failures"] or 0),
        "total_attempts": total,
        "avg_duration_seconds": round(avg_duration, 3),
        "avg_replans": round(avg_replans, 3),
        "last_seen": float(row["last_seen"] or 0.0),
        "last_success": float(row["last_success"] or 0.0),
        "last_failure": float(row["last_failure"] or 0.0),
        "quarantined_until": float(row["quarantined_until"] or 0.0),
        "quarantine_reason": row["quarantine_reason"] or "",
        "trusted": (
            total >= 3
            and successes >= 3
            and successes / total >= 0.75
            and verified / total >= 0.66
        ),
    }


def _similarity(query_key: str, domain: str, candidate: dict[str, Any]) -> float:
    query = set(_tokens(query_key))
    candidate_tokens = set(_tokens(candidate.get("request_key", "")))
    if not query or not candidate_tokens:
        return 0.0
    overlap = len(query & candidate_tokens)
    union = len(query | candidate_tokens)
    score = overlap / max(1, union)
    if domain and str(candidate.get("domain", "")) == domain:
        score += 0.15
    return min(1.0, score)


def find_strategies(
    request: str,
    *,
    domain: str = "",
    limit: int = 5,
    include_quarantined: bool = False,
) -> list[dict[str, Any]]:
    query_key = normalize_request(request)
    domain = domain or detect_domain(request)
    limit = max(1, min(int(limit), 20))
    now = time.time()

    try:
        with _LOCK:
            with _connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM strategies ORDER BY last_seen DESC LIMIT 250"
                ).fetchall()
        candidates = []
        for row in rows:
            item = _row_to_strategy(row)
            if (
                not include_quarantined
                and item["quarantined_until"] > now
            ):
                continue
            similarity = _similarity(query_key, domain, item)
            if similarity < 0.25:
                continue
            item["similarity"] = round(similarity, 4)
            candidates.append(item)

        candidates.sort(
            key=lambda item: (
                item["similarity"],
                1.0 if item["trusted"] else 0.0,
                item["success_rate"],
                item["verified_rate"],
                item["last_success"],
            ),
            reverse=True,
        )
        return candidates[:limit]
    except (OSError, sqlite3.Error, ValueError):
        return []


def get_strategy(fingerprint: str) -> dict[str, Any] | None:
    try:
        with _LOCK:
            with _connect() as connection:
                row = connection.execute(
                    "SELECT * FROM strategies WHERE fingerprint=?",
                    (str(fingerprint or ""),),
                ).fetchone()
        return _row_to_strategy(row) if row else None
    except (OSError, sqlite3.Error, ValueError):
        return None


def quarantine_strategy(
    fingerprint: str,
    *,
    seconds: float = 3600.0,
    reason: str = "",
) -> bool:
    until = time.time() + max(60.0, float(seconds))
    try:
        with _LOCK:
            with _connect() as connection:
                result = connection.execute(
                    """
                    UPDATE strategies
                    SET quarantined_until=?, quarantine_reason=?
                    WHERE fingerprint=?
                    """,
                    (
                        until,
                        str(reason or "").strip()[:500],
                        str(fingerprint or ""),
                    ),
                )
                connection.commit()
        return result.rowcount > 0
    except (OSError, sqlite3.Error, ValueError):
        return False


def clear_quarantine(fingerprint: str) -> bool:
    try:
        with _LOCK:
            with _connect() as connection:
                result = connection.execute(
                    """
                    UPDATE strategies
                    SET quarantined_until=0, quarantine_reason=''
                    WHERE fingerprint=?
                    """,
                    (str(fingerprint or ""),),
                )
                connection.commit()
        return result.rowcount > 0
    except (OSError, sqlite3.Error, ValueError):
        return False


def recent_events(fingerprint: str, limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 50))
    try:
        with _LOCK:
            with _connect() as connection:
                rows = connection.execute(
                    """
                    SELECT timestamp, success, verified, duration,
                           replans, error
                    FROM strategy_events
                    WHERE fingerprint=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (str(fingerprint or ""), limit),
                ).fetchall()
        return [
            {
                "timestamp": float(row["timestamp"] or 0.0),
                "success": bool(row["success"]),
                "verified": bool(row["verified"]),
                "duration_seconds": float(row["duration"] or 0.0),
                "replans": int(row["replans"] or 0),
                "error": str(row["error"] or ""),
            }
            for row in rows
        ]
    except (OSError, sqlite3.Error, ValueError):
        return []


def strategy_status() -> dict[str, Any]:
    try:
        with _LOCK:
            with _connect() as connection:
                row = connection.execute(
                    """
                    SELECT
                        COUNT(*) AS strategies,
                        SUM(total_attempts) AS attempts,
                        SUM(successes) AS successes,
                        SUM(failures) AS failures
                    FROM strategies
                    """
                ).fetchone()
        strategies = int(row["strategies"] or 0) if row else 0
        attempts = int(row["attempts"] or 0) if row else 0
        successes = int(row["successes"] or 0) if row else 0
        failures = int(row["failures"] or 0) if row else 0
        return {
            "enabled": True,
            "path": str(_DB_PATH),
            "strategies": strategies,
            "attempts": attempts,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / attempts, 4) if attempts else 0.0,
            "max_strategies": _MAX_STRATEGIES,
        }
    except Exception as exc:
        return {
            "enabled": False,
            "path": str(_DB_PATH),
            "error": str(exc)[:300],
        }


__all__ = [
    "clear_quarantine",
    "detect_domain",
    "find_strategies",
    "get_strategy",
    "normalize_request",
    "plan_signature",
    "quarantine_strategy",
    "recent_events",
    "record_strategy",
    "strategy_status",
]