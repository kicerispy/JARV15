"""First-class integration with the upstream sdaqo/anipy-cli project.

The upstream packages are installed unchanged at an exact matching version.
This module is an adapter only: native CLI execution is passed through to the
real anipy-cli entry point, while structured helpers expose the same upstream
anipy-api provider/search/stream/downloader objects to JARVIS.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from logger import logger


ANIPY_VERSION = "3.10.1"


def _parse_json_object(argument: str) -> dict[str, Any]:
    raw = str(argument or "").strip()
    if not raw:
        return {}

    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            "anipy structured arguments must be valid JSON."
        ) from exc

    if not isinstance(value, dict):
        raise ValueError("anipy structured arguments must be a JSON object.")

    return value


def _jsonable(value: Any) -> Any:
    """Convert upstream dataclasses/enums/paths into bounded JSON data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]

    if hasattr(value, "__dict__"):
        return {
            str(key): _jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }

    return str(value)


def _quality(value: Any) -> str | int | None:
    """Match anipy-cli argparse behavior for best/worst/numeric quality."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def _language(language: str | None):
    from anipy_api.provider import LanguageTypeEnum

    requested = str(language or "").strip().lower()

    if not requested:
        try:
            from anipy_cli.config import Config

            requested = str(Config().preferred_type or "").strip().lower()
        except Exception:
            requested = ""

    if requested not in {"sub", "dub"}:
        requested = "sub"

    return LanguageTypeEnum[requested.upper()]


def _provider_instances(
    *,
    mode: str = "default",
    provider_name: str | None = None,
    all_providers: bool = False,
):
    """Return upstream BaseProvider instances using upstream config defaults."""
    from anipy_api.provider import get_provider, list_providers

    if provider_name:
        try:
            from anipy_cli.config import Config

            override = Config().provider_urls.get(provider_name)
        except Exception:
            override = None

        provider = get_provider(
            provider_name,
            base_url_override=override,
        )
        if provider is None:
            raise ValueError(
                f"Unknown anipy provider: {provider_name}"
            )
        return [provider]

    if all_providers:
        providers = []
        try:
            from anipy_cli.config import Config

            overrides = Config().provider_urls
        except Exception:
            overrides = {}

        for provider_cls in list_providers():
            try:
                providers.append(
                    provider_cls(
                        overrides.get(provider_cls.NAME)
                    )
                )
            except Exception as exc:
                logger.warning(
                    "JARVIS: anipy provider %s failed to initialize: %s",
                    getattr(provider_cls, "NAME", provider_cls),
                    exc,
                )
        return providers

    try:
        from anipy_cli.config import Config

        config = Config()
        names = list(config.providers.get(mode, []))
        overrides = config.provider_urls
    except Exception:
        names = []
        overrides = {}

    if not names:
        names = [provider_cls.NAME for provider_cls in list_providers()]

    providers = []
    for name in names:
        provider = get_provider(
            name,
            base_url_override=overrides.get(name),
        )
        if provider is not None:
            providers.append(provider)

    return providers


def _search(
    query: str,
    *,
    provider_name: str | None = None,
    all_providers: bool = False,
    mode: str = "default",
) -> list[tuple[Any, Any]]:
    if not query.strip():
        raise ValueError("Anime search query is required.")

    matches: list[tuple[Any, Any]] = []
    errors: list[str] = []

    for provider in _provider_instances(
        mode=mode,
        provider_name=provider_name,
        all_providers=all_providers,
    ):
        try:
            results = provider.get_search(query)
        except Exception as exc:
            errors.append(f"{provider.NAME}: {exc}")
            continue

        for result in results:
            matches.append((provider, result))

    if not matches and errors:
        raise RuntimeError(
            "No anime results were returned. Provider errors: "
            + "; ".join(errors)
        )

    return matches


def _resolve_anime(payload: dict[str, Any], *, mode: str = "default"):
    from anipy_api.anime import Anime

    provider_name = str(payload.get("provider") or "").strip() or None
    identifier = str(payload.get("identifier") or "").strip()

    if identifier:
        providers = _provider_instances(
            mode=mode,
            provider_name=provider_name,
        )
        if not providers:
            raise RuntimeError("No anipy providers are configured.")

        provider = providers[0]
        return Anime(
            provider,
            str(payload.get("name") or identifier),
            identifier,
            set(),
        )

    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError(
            "Anime selector requires either query or identifier."
        )

    matches = _search(
        query,
        provider_name=provider_name,
        all_providers=bool(payload.get("all_providers", False)),
        mode=mode,
    )
    if not matches:
        raise RuntimeError(f"No anime found for query: {query}")

    index = payload.get("index", 1)
    try:
        index = max(1, int(index))
    except (TypeError, ValueError):
        index = 1

    if index > len(matches):
        raise ValueError(
            f"Anime result index {index} is out of range; "
            f"only {len(matches)} result(s) were returned."
        )

    provider, result = matches[index - 1]
    return Anime.from_search_result(provider, result)


def _native_cli_args(argument: str) -> list[str]:
    raw = str(argument or "").strip()

    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        payload = None

    if isinstance(payload, dict) and "args" in payload:
        args = payload.get("args")
        if not isinstance(args, list):
            raise ValueError("anipy_cli JSON 'args' must be a list.")
        return [str(item) for item in args]

    # JSON list is also accepted for exact programmatic passthrough.
    if isinstance(payload, list):
        return [str(item) for item in payload]

    return shlex.split(raw)


def _run_native_cli(argument: str) -> dict[str, Any]:
    """Invoke the unmodified upstream anipy-cli module exactly as installed."""
    args = _native_cli_args(argument)
    command = [sys.executable, "-m", "anipy_cli.cli", *args]

    logger.info(
        "JARVIS: Launching native anipy-cli: %s",
        " ".join(shlex.quote(part) for part in command),
    )

    completed = subprocess.run(
        command,
        check=False,
        stdin=None,
        stdout=None,
        stderr=None,
    )

    return {
        "success": completed.returncode == 0,
        "verified": completed.returncode == 0,
        "tool": "anipy_cli",
        "version": ANIPY_VERSION,
        "returncode": completed.returncode,
        "args": args,
        "command": command,
        "message": (
            "Native anipy-cli exited successfully."
            if completed.returncode == 0
            else f"Native anipy-cli exited with code {completed.returncode}."
        ),
    }


def _run_providers() -> dict[str, Any]:
    from anipy_api.provider import list_providers

    providers = []
    for provider_cls in list_providers():
        providers.append(
            {
                "name": provider_cls.NAME,
                "base_url": getattr(provider_cls, "BASE_URL", ""),
                "filter_capabilities": _jsonable(
                    getattr(provider_cls, "FILTER_CAPS", None)
                ),
            }
        )

    return {
        "success": True,
        "verified": True,
        "tool": "anipy_providers",
        "version": ANIPY_VERSION,
        "providers": providers,
    }


def _run_search(argument: str) -> dict[str, Any]:
    payload = _parse_json_object(argument)
    query = str(payload.get("query") or "").strip()

    matches = _search(
        query,
        provider_name=str(payload.get("provider") or "").strip() or None,
        all_providers=bool(payload.get("all_providers", False)),
        mode=str(payload.get("mode") or "default"),
    )

    results = []
    for index, (provider, result) in enumerate(matches, start=1):
        result_data = _jsonable(result)
        if isinstance(result_data, dict):
            result_data = dict(result_data)
            result_data["provider"] = provider.NAME
            result_data["index"] = index
        results.append(result_data)

    return {
        "success": True,
        "verified": True,
        "tool": "anipy_search",
        "version": ANIPY_VERSION,
        "query": query,
        "count": len(results),
        "results": results,
    }


def _run_info(argument: str) -> dict[str, Any]:
    payload = _parse_json_object(argument)
    anime = _resolve_anime(payload, mode=str(payload.get("mode") or "default"))
    info = anime.get_info()

    return {
        "success": True,
        "verified": True,
        "tool": "anipy_info",
        "version": ANIPY_VERSION,
        "anime": {
            "name": anime.name,
            "identifier": anime.identifier,
            "provider": anime.provider.NAME,
            "languages": _jsonable(anime.languages),
        },
        "info": _jsonable(info),
    }


def _run_episodes(argument: str) -> dict[str, Any]:
    payload = _parse_json_object(argument)
    anime = _resolve_anime(payload, mode=str(payload.get("mode") or "default"))
    lang = _language(payload.get("language"))
    episodes = anime.get_episodes(lang)

    return {
        "success": True,
        "verified": True,
        "tool": "anipy_episodes",
        "version": ANIPY_VERSION,
        "anime": {
            "name": anime.name,
            "identifier": anime.identifier,
            "provider": anime.provider.NAME,
            "languages": _jsonable(anime.languages),
        },
        "language": lang.value,
        "episodes": _jsonable(episodes),
        "count": len(episodes),
    }


def _stream_data(anime: Any, stream: Any) -> dict[str, Any]:
    return {
        "anime": anime.name,
        "identifier": anime.identifier,
        "provider": anime.provider.NAME,
        "stream": _jsonable(stream),
    }


def _run_get_video(argument: str) -> dict[str, Any]:
    payload = _parse_json_object(argument)
    anime = _resolve_anime(payload, mode=str(payload.get("mode") or "default"))
    lang = _language(payload.get("language"))

    if "episode" not in payload:
        raise ValueError("anipy_get_video requires an episode.")

    episode = payload["episode"]
    if isinstance(episode, str):
        try:
            episode = float(episode) if "." in episode else int(episode)
        except ValueError as exc:
            raise ValueError("Episode must be numeric.") from exc

    stream = anime.get_video(
        episode,
        lang,
        preferred_quality=_quality(payload.get("quality")),
    )

    if stream is None:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "tool": "anipy_get_video",
            "version": ANIPY_VERSION,
            "error": (
                f"No stream was found for {anime.name} episode {episode} "
                f"({lang.value})."
            ),
        }

    return {
        "success": True,
        "verified": True,
        "tool": "anipy_get_video",
        "version": ANIPY_VERSION,
        **_stream_data(anime, stream),
    }


class _NoopSpinner:
    """Satisfy upstream post-download hook callbacks without replacing them."""

    def hide(self):
        return None

    def show(self):
        return None

    def set_text(self, *args, **kwargs):
        return None

    def write(self, *args, **kwargs):
        return None


def _coerce_episode_values(anime: Any, lang: Any, payload: dict[str, Any]) -> list[Any]:
    raw = payload.get("episodes", payload.get("episode"))
    if raw is None:
        raise ValueError(
            "anipy_download requires episode or episodes."
        )

    available = anime.get_episodes(lang)

    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, (int, float)):
        values = [raw]
    else:
        text = str(raw).strip()
        if not text:
            raise ValueError("Episode range cannot be empty.")

        try:
            from anipy_cli.util import parse_episode_ranges

            values = parse_episode_ranges(text, available)
        except Exception:
            values = []

        if not values:
            if re_full_numeric(text):
                values = [
                    float(text) if "." in text else int(text)
                ]
            else:
                raise ValueError(
                    f"Could not resolve episode range '{text}' "
                    f"from available episodes."
                )

    normalized = []
    for value in values:
        try:
            normalized.append(
                float(value) if isinstance(value, str) and "." in value
                else int(value) if isinstance(value, str)
                else value
            )
        except (TypeError, ValueError):
            raise ValueError(f"Invalid episode value: {value!r}")

    return normalized


def re_full_numeric(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d+(?:\.\d+)?", value))


def _run_download(argument: str) -> dict[str, Any]:
    payload = _parse_json_object(argument)

    from anipy_api.download import Downloader
    from anipy_cli.config import Config
    from anipy_cli.util import get_download_path, get_post_download_scripts_hook

    anime = _resolve_anime(payload, mode="download")
    lang = _language(payload.get("language"))
    config = Config()
    episodes = _coerce_episode_values(anime, lang, payload)

    requested_location = str(payload.get("location") or "").strip()
    download_root = (
        Path(requested_location).expanduser()
        if requested_location
        else config.download_folder_path
    )

    container = payload.get("container")
    if container in ("", None):
        container = config.remux_to

    ffmpeg = (
        bool(payload["ffmpeg"])
        if "ffmpeg" in payload
        else bool(config.ffmpeg_hls)
    )

    try:
        max_retry = max(1, int(payload.get("max_retry", 3)))
    except (TypeError, ValueError):
        max_retry = 3

    progress_state = {"last": -5.0}

    def progress_callback(percentage: float):
        percentage = float(percentage)
        if percentage >= 100 or percentage - progress_state["last"] >= 5:
            progress_state["last"] = percentage
            logger.info(
                "JARVIS: anipy download %.1f%% - %s",
                percentage,
                anime.name,
            )

    def info_callback(message: str, exc_info: BaseException | None = None):
        if exc_info is None:
            logger.info("JARVIS: anipy: %s", message)
        else:
            logger.warning("JARVIS: anipy: %s", message, exc_info=exc_info)

    def soft_error_callback(message: str, exc_info: BaseException | None = None):
        if exc_info is None:
            logger.warning("JARVIS: anipy: %s", message)
        else:
            logger.warning("JARVIS: anipy: %s", message, exc_info=exc_info)

    downloader = Downloader(
        progress_callback=progress_callback,
        info_callback=info_callback,
        soft_error_callback=soft_error_callback,
    )

    post_dl_cb = get_post_download_scripts_hook(
        "download",
        anime,
        _NoopSpinner(),
    )

    results = []
    for episode in episodes:
        try:
            stream = anime.get_video(
                episode,
                lang,
                preferred_quality=_quality(payload.get("quality")),
            )
            if stream is None:
                raise RuntimeError(
                    f"No stream found for episode {episode} ({lang.value})."
                )

            destination = get_download_path(
                anime,
                stream,
                parent_directory=download_root,
            )

            if bool(payload.get("sub_only", False)):
                downloader.download_sub(
                    stream,
                    destination,
                )
                final_path = destination
            else:
                final_path = downloader.download(
                    stream,
                    destination,
                    container=container,
                    ffmpeg=ffmpeg,
                    max_retry=max_retry,
                    post_dl_cb=post_dl_cb,
                )

            results.append(
                {
                    "episode": episode,
                    "success": True,
                    "path": str(final_path),
                    "resolution": stream.resolution,
                    "language": lang.value,
                    "provider": anime.provider.NAME,
                }
            )
        except Exception as exc:
            logger.exception(
                "JARVIS: anipy download failed for %s episode %s",
                anime.name,
                episode,
            )
            results.append(
                {
                    "episode": episode,
                    "success": False,
                    "error": str(exc),
                }
            )

    success = bool(results) and all(item["success"] for item in results)

    return {
        "success": success,
        "verified": success,
        "retryable": not success,
        "tool": "anipy_download",
        "version": ANIPY_VERSION,
        "anime": anime.name,
        "provider": anime.provider.NAME,
        "language": lang.value,
        "episodes": results,
        "download_root": str(download_root),
    }


def run_anipy_tool(tool_name: str, argument: str = "") -> dict[str, Any]:
    """Dispatch JARVIS anipy operations while keeping upstream behavior intact."""
    try:
        if tool_name == "anipy_cli":
            return _run_native_cli(argument)
        if tool_name == "anipy_providers":
            return _run_providers()
        if tool_name == "anipy_search":
            return _run_search(argument)
        if tool_name == "anipy_info":
            return _run_info(argument)
        if tool_name == "anipy_episodes":
            return _run_episodes(argument)
        if tool_name == "anipy_get_video":
            return _run_get_video(argument)
        if tool_name == "anipy_download":
            return _run_download(argument)

        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "terminal": True,
            "tool": tool_name,
            "error": f"Unknown anipy tool: {tool_name}",
        }
    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "terminal": False,
            "tool": tool_name,
            "version": ANIPY_VERSION,
            "error": str(exc),
        }
