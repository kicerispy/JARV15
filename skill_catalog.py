"""External Agent Skills catalog for JARVIS.

The catalog treats upstream skill repositories as read-mostly knowledge packs.
They are synchronized only on explicit request and are never executed
automatically. Scripts inside a security skill remain inert unless another
explicitly gated JARVIS tool later chooses to run them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config import (
    AGENT_SKILLS_DIR,
    AGENT_SKILL_SOURCES_FILE,
    AGENT_SKILL_SYNC_DEPTH,
)

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _read_frontmatter(text: str) -> Dict[str, str]:
    match = _FRONTMATTER.match(text or "")
    if not match:
        return {}
    result: Dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _load_sources() -> List[Dict[str, Any]]:
    path = Path(AGENT_SKILL_SOURCES_FILE)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _source_slug(source: Dict[str, Any]) -> str:
    return str(source.get("slug") or source.get("repo", "").split("/")[-1]).strip()


def _source_dir(source: Dict[str, Any]) -> Path:
    return Path(AGENT_SKILLS_DIR) / _source_slug(source)


def _run_git(args: List[str], cwd: Optional[Path] = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def sync_sources() -> Dict[str, Any]:
    """Clone/update configured skill repositories on explicit user request."""
    root = Path(AGENT_SKILLS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    results = []

    for source in _load_sources():
        repo = str(source.get("repo") or "").strip()
        branch = str(source.get("branch") or "main").strip()
        slug = _source_slug(source)
        if not repo:
            continue

        target = root / slug
        if target.exists() and (target / ".git").exists():
            pull = _run_git(["fetch", "--depth", str(AGENT_SKILL_SYNC_DEPTH), "origin", branch], cwd=target)
            if pull.returncode == 0:
                reset = _run_git(["reset", "--hard", f"origin/{branch}"], cwd=target)
                ok = reset.returncode == 0
                output = (reset.stderr or reset.stdout or "").strip()
            else:
                ok = False
                output = (pull.stderr or pull.stdout or "").strip()
        else:
            if target.exists():
                shutil.rmtree(target)
            clone = _run_git(
                ["clone", "--depth", str(AGENT_SKILL_SYNC_DEPTH), "--branch", branch, repo, str(target)],
            )
            ok = clone.returncode == 0
            output = (clone.stderr or clone.stdout or "").strip()

        sha = ""
        if ok:
            head = _run_git(["rev-parse", "HEAD"], cwd=target)
            if head.returncode == 0:
                sha = head.stdout.strip()

        results.append({
            "slug": slug,
            "repo": repo,
            "branch": branch,
            "path": str(target),
            "success": ok,
            "commit": sha,
            "message": output[-1000:],
        })

    return {"success": all(item["success"] for item in results) if results else True, "sources": results}


def _candidate_skill_files(root: Path) -> Iterable[Path]:
    # Explicit index files are much cheaper than walking large cybersecurity repos.
    for index_name in ("index.json",):
        index = root / index_name
        if index.exists():
            yield index

    yield from root.rglob("SKILL.md")


def _skill_record(path: Path, source_slug: str, root: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if path.name == "index.json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
            return None
        return {
            "kind": "index",
            "source": source_slug,
            "name": data.get("domain") or source_slug,
            "description": f"{len(data.get('skills', []))} indexed skills",
            "path": str(path),
            "skill_count": len(data.get("skills", [])),
            "skills": data.get("skills", []),
        }

    front = _read_frontmatter(text)
    rel = path.relative_to(root).as_posix()
    name = front.get("name") or path.parent.name
    description = front.get("description") or ""
    return {
        "kind": "skill",
        "source": source_slug,
        "name": name,
        "description": description,
        "path": str(path),
        "relative_path": rel,
    }


def list_skills(source: str = "") -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in _load_sources():
        slug = _source_slug(item)
        if source and slug != source:
            continue
        root = _source_dir(item)
        if not root.exists():
            continue
        for candidate in _candidate_skill_files(root):
            record = _skill_record(candidate, slug, root)
            if record:
                records.append(record)
    return records


def search_skills(query: str, limit: int = 12) -> Dict[str, Any]:
    q = " ".join(str(query or "").lower().split())
    terms = [term for term in q.split() if len(term) > 2]
    limit = max(1, min(int(limit), 50))

    # Search the compact cybersecurity index first because the repository
    # contains hundreds of skill directories.
    matches: List[Dict[str, Any]] = []
    for item in _load_sources():
        slug = _source_slug(item)
        root = _source_dir(item)
        index_path = root / "index.json"
        if index_path.exists():
            try:
                index_data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                index_data = {}
            for skill in index_data.get("skills", []) if isinstance(index_data, dict) else []:
                haystack = f"{skill.get('name','')} {skill.get('description','')}".lower()
                score = sum(1 for term in terms if term in haystack)
                if score:
                    matches.append({
                        "source": slug,
                        "name": skill.get("name"),
                        "description": skill.get("description"),
                        "path": str(root / skill.get("path", "")),
                        "score": score,
                    })

    # Read only SKILL.md metadata for the remaining repositories.
    for record in list_skills():
        if record.get("kind") != "skill":
            continue
        haystack = f"{record.get('name','')} {record.get('description','')} {record.get('relative_path','')}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            matches.append({
                **record,
                "score": score,
            })

    matches.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("name", ""))))
    return {"success": True, "results": matches[:limit]}


def read_skill(path: str, max_chars: int = 30000) -> Dict[str, Any]:
    candidate = Path(path).resolve()
    root = Path(AGENT_SKILLS_DIR).resolve()
    if root not in candidate.parents and candidate != root:
        return {"success": False, "message": "Skill path is outside the configured JARVIS skill directory."}
    if not candidate.exists() or candidate.is_dir():
        return {"success": False, "message": "Skill file was not found."}
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {
        "success": True,
        "path": str(candidate),
        "content": text[:max_chars],
        "truncated": len(text) > max_chars,
    }


def status() -> Dict[str, Any]:
    sources = []
    for source in _load_sources():
        root = _source_dir(source)
        sources.append({
            "slug": _source_slug(source),
            "repo": source.get("repo"),
            "branch": source.get("branch", "main"),
            "installed": root.exists(),
            "path": str(root),
        })
    return {
        "success": True,
        "root": str(Path(AGENT_SKILLS_DIR)),
        "sources": sources,
    }


def run_skill_tool(tool_name: str, argument: Any = "") -> Any:
    name = str(tool_name or "").strip()
    if name == "skills_status":
        return status()
    if name == "skills_sync":
        return sync_sources()
    if name == "skills_search":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            payload = {"query": str(argument or "")}
        return search_skills(str(payload.get("query") or ""), int(payload.get("limit") or 12))
    if name == "skills_read":
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "message": "skills_read expects JSON {path,max_chars}."}
        return read_skill(str(payload.get("path") or ""), int(payload.get("max_chars") or 30000))
    return {"success": False, "message": f"Unknown skill tool: {name}"}
