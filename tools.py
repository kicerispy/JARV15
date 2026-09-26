import ast
import json
import os
import re
import ssl
import subprocess
import time
import webbrowser

from datetime import datetime
from typing import Any, Dict, Union
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi
import psutil

from tool_result import ToolResult
from tool_registry import (
    ADAPTIVE_RUNTIME_TOOLS,
    AGENT_SKILL_TOOLS,
    ANIPY_TOOLS,
    BROWSER_TOOLS,
    CONTEXT_MEMORY_TOOLS,
    GODS_EYE_TOOLS,
    JARVIS_PLATFORM_TOOLS,
    N8N_TOOLS,
    ROBLOX_MCP_TOOLS,
    SCREEN_MEMORY_TOOLS,
    SYSTEM_HEALTH_TOOLS,
    UNREAL_MCP_TOOLS,
)
from project_fs import iter_project_files

import barehands_tools
import file_tools
import jarvis_status
import screen_vision
import web_summary
import web_tools
import runtime_health
import startup_manager
import task_memory

from config import (
    DEFAULT_WEATHER_LOCATION,
    WEATHER_GEOCODING_URL,
    WEATHER_URL,
)


# ============================================================
# WEATHER
# ============================================================

WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _http_get_json(url, params):
    """
    Perform an HTTPS GET request and decode a JSON response.

    Uses certifi's CA bundle explicitly so JARVIS does not
    depend on a stale Python/OpenSSL certificate store.
    """

    query = urlencode(params)

    full_url = (
        f"{url}?{query}"
    )

    request = Request(
        full_url,
        headers={
            "User-Agent": "JARVIS/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    with urlopen(
        request,
        timeout=15,
        context=ssl_context,
    ) as response:

        raw = response.read()

        if not raw:
            raise RuntimeError(
                "Weather service returned an empty response."
            )

        text = raw.decode(
            "utf-8",
            errors="replace",
        )

        return json.loads(text)


def _extract_weather_location(request):
    """
    Extract a location from requests such as:

        weather
        weather in Belvidere, IL
        weather for Belvidere, IL
        weather in Belvidere, IL today
        weather in Belvidere, IL tomorrow
    """

    request = (
        str(request or "")
        .strip()
    )

    if not request:
        return DEFAULT_WEATHER_LOCATION

    match = re.search(
        r"\bin\s+(.+?)(?:\s+tomorrow|\s+today|\s+right now|\s+now)?$",
        request,
        re.IGNORECASE,
    )

    if match:

        location = (
            match.group(1)
            .strip()
        )

        location = re.sub(
            r"\b(today|tomorrow|right now|now)$",
            "",
            location,
            flags=re.IGNORECASE,
        ).strip()

        if location:
            return location

    match = re.search(
        r"\bfor\s+(.+?)(?:\s+tomorrow|\s+today|\s+right now|\s+now)?$",
        request,
        re.IGNORECASE,
    )

    if match:

        location = (
            match.group(1)
            .strip()
        )

        location = re.sub(
            r"\b(today|tomorrow|right now|now)$",
            "",
            location,
            flags=re.IGNORECASE,
        ).strip()

        if location:
            return location

    return DEFAULT_WEATHER_LOCATION


def _is_tomorrow_request(request):
    return (
        "tomorrow"
        in str(request or "").lower()
    )


def _geocode_location(location):

    data = _http_get_json(
        WEATHER_GEOCODING_URL,
        {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        },
    )

    results = data.get(
        "results",
        [],
    )

    if not results:
        return None

    result = results[0]

    return {
        "name": result.get(
            "name",
            location,
        ),
        "admin1": result.get(
            "admin1",
            "",
        ),
        "country": result.get(
            "country",
            "",
        ),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "timezone": result.get(
            "timezone",
            "auto",
        ),
    }


def weather(request=""):
    """
    Get current or tomorrow's weather.

    With no location specified, uses
    DEFAULT_WEATHER_LOCATION from config.py.
    """

    try:

        location_query = (
            _extract_weather_location(
                request
            )
        )

        location = (
            _geocode_location(
                location_query
            )
        )

        if location is None:

            return (
                f"I couldn't find weather data for "
                f"{location_query}."
            )

        data = _http_get_json(
            WEATHER_URL,
            {
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": (
                    "temperature_2m,"
                    "apparent_temperature,"
                    "relative_humidity_2m,"
                    "precipitation,"
                    "rain,"
                    "showers,"
                    "snowfall,"
                    "weather_code,"
                    "wind_speed_10m"
                ),
                "daily": (
                    "weather_code,"
                    "temperature_2m_max,"
                    "temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": location["timezone"],
                "forecast_days": 2,
            },
        )

        current = data.get(
            "current",
            {},
        )

        daily = data.get(
            "daily",
            {},
        )

        if not current:

            return (
                "I couldn't retrieve current "
                "weather conditions."
            )

        temperature = current.get(
            "temperature_2m"
        )

        apparent = current.get(
            "apparent_temperature"
        )

        humidity = current.get(
            "relative_humidity_2m"
        )

        wind = current.get(
            "wind_speed_10m"
        )

        weather_code = current.get(
            "weather_code"
        )

        description = WEATHER_CODES.get(
            weather_code,
            "unknown conditions",
        )

        location_name = location["name"]

        if location.get("admin1"):

            location_name += (
                f", {location['admin1']}"
            )

        # --------------------------------------------------------
        # TOMORROW
        # --------------------------------------------------------

        if _is_tomorrow_request(request):

            dates = daily.get(
                "time",
                [],
            )

            if len(dates) >= 2:

                tomorrow_max = daily[
                    "temperature_2m_max"
                ][1]

                tomorrow_min = daily[
                    "temperature_2m_min"
                ][1]

                tomorrow_code = daily[
                    "weather_code"
                ][1]

                tomorrow_precip = daily[
                    "precipitation_probability_max"
                ][1]

                tomorrow_description = (
                    WEATHER_CODES.get(
                        tomorrow_code,
                        "unknown conditions",
                    )
                )

                return (
                    f"Tomorrow in {location_name}, "
                    f"expect {tomorrow_description}, "
                    f"with a high of "
                    f"{tomorrow_max:.0f} degrees "
                    f"and a low of "
                    f"{tomorrow_min:.0f}. "
                    f"The maximum precipitation "
                    f"probability is "
                    f"{tomorrow_precip:.0f} percent."
                )

        # --------------------------------------------------------
        # TODAY
        # --------------------------------------------------------

        today_high = None
        today_low = None
        today_precip = None

        if daily.get("time"):

            high_values = daily.get(
                "temperature_2m_max",
                [],
            )

            low_values = daily.get(
                "temperature_2m_min",
                [],
            )

            precip_values = daily.get(
                "precipitation_probability_max",
                [],
            )

            if high_values:
                today_high = high_values[0]

            if low_values:
                today_low = low_values[0]

            if precip_values:
                today_precip = precip_values[0]

        # --------------------------------------------------------
        # RESPONSE
        # --------------------------------------------------------

        if temperature is None:

            response = (
                f"In {location_name}, "
                f"current conditions are "
                f"{description}."
            )

        else:

            response = (
                f"In {location_name}, it's currently "
                f"{temperature:.0f} degrees and "
                f"{description}. "
            )

        if apparent is not None:

            response += (
                f"It feels like "
                f"{apparent:.0f}. "
            )

        if humidity is not None:

            response += (
                f"Humidity is "
                f"{humidity:.0f} percent. "
            )

        if wind is not None:

            response += (
                f"Wind is "
                f"{wind:.0f} miles per hour. "
            )

        if (
            today_high is not None
            and today_low is not None
        ):

            response += (
                f"Today's high is "
                f"{today_high:.0f}, "
                f"with a low of "
                f"{today_low:.0f}. "
            )

        if today_precip is not None:

            response += (
                f"The precipitation probability "
                f"reaches {today_precip:.0f} percent."
            )

        return response

    except HTTPError as e:

        print(
            f"Weather HTTP error: {e.code}"
        )

        return (
            "The weather service returned "
            f"HTTP error {e.code}."
        )

    except URLError as e:

        print(
            f"Weather URL error: {e}"
        )

        return (
            "I couldn't reach the weather service."
        )

    except TimeoutError as e:

        print(
            f"Weather timeout: {e}"
        )

        return (
            "The weather service took too long "
            "to respond."
        )

    except Exception as e:

        print(
            "Weather error:",
            repr(e),
        )

        return (
            "I encountered an error while "
            "retrieving the weather."
        )


# ============================================================
# TIME
# ============================================================

TIMEZONE_ALIASES = {

    "belvidere":
        "America/Chicago",

    "chicago":
        "America/Chicago",

    "illinois":
        "America/Chicago",

    "new york":
        "America/New_York",

    "new york city":
        "America/New_York",

    "los angeles":
        "America/Los_Angeles",

    "san francisco":
        "America/Los_Angeles",

    "seattle":
        "America/Los_Angeles",

    "denver":
        "America/Denver",

    "phoenix":
        "America/Phoenix",

    "london":
        "Europe/London",

    "paris":
        "Europe/Paris",

    "berlin":
        "Europe/Berlin",

    "tokyo":
        "Asia/Tokyo",

    "seoul":
        "Asia/Seoul",

    "beijing":
        "Asia/Shanghai",

    "shanghai":
        "Asia/Shanghai",

    "singapore":
        "Asia/Singapore",

    "sydney":
        "Australia/Sydney",

    "dubai":
        "Asia/Dubai",

    "mumbai":
        "Asia/Kolkata",

    "delhi":
        "Asia/Kolkata",

    "toronto":
        "America/Toronto",

    "vancouver":
        "America/Vancouver",

    "mexico city":
        "America/Mexico_City",
}


def _resolve_timezone(argument):

    name = (
        str(argument or "")
        .strip()
    )

    if not name:
        return None

    lowered = name.lower()

    if lowered in TIMEZONE_ALIASES:

        return TIMEZONE_ALIASES[
            lowered
        ]

    return name


def current_time(argument=""):

    timezone_name = (
        _resolve_timezone(
            argument
        )
    )

    if timezone_name:

        try:

            now = datetime.now(
                ZoneInfo(timezone_name)
            )

            display_name = (
                str(argument)
                .strip()
            )

            return (
                f"The time in {display_name} is "
                f"{now.strftime('%I:%M %p').lstrip('0')}."
            )

        except Exception:

            return (
                f"I don't recognize the timezone "
                f"{str(argument).strip()}."
            )

    now = datetime.now()

    return (
        f"It's {now.strftime('%I:%M %p').lstrip('0')}."
    )


# ============================================================
# DATE
# ============================================================

def current_date():

    now = datetime.now()

    return (
        f"Today is "
        f"{now.strftime('%A, %B %d, %Y')}."
    )


# ============================================================
# WAIT
# ============================================================

def wait_seconds(argument=""):

    try:

        seconds = float(
            argument
        )

        seconds = max(
            0.0,
            min(
                seconds,
                30.0,
            ),
        )

        time.sleep(
            seconds
        )

        return (
            f"Waited {seconds:.1f} seconds."
        )

    except Exception:

        return "Invalid wait duration."


# ============================================================
# OPEN WEBSITE
# ============================================================

WEBSITE_URLS = {

    "youtube":
        "https://www.youtube.com/",

    "google":
        "https://www.google.com/",

    "amazon":
        "https://www.amazon.com/",

    "reddit":
        "https://www.reddit.com/",
}


def open_website(argument=""):

    argument = (
        str(argument or "")
        .strip()
    )

    if (
        argument.startswith(
            "http://"
        )
        or argument.startswith(
            "https://"
        )
    ):

        url = argument

    else:

        site = argument.lower()

        url = WEBSITE_URLS.get(
            site
        )

        if url is None:

            return (
                f"I don't have {argument} "
                f"configured as a website."
            )

    try:

        webbrowser.open(
            url
        )

        return (
            f"Opening {argument}."
        )

    except Exception as e:

        print(
            "Website launch error:",
            e,
        )

        return (
            f"I couldn't open {argument}."
        )


# ============================================================
# SEARCH WEBSITE
# ============================================================

def search_website(
    site,
    query="",
):
    """
    Search a known website directly.

    This is deliberately deterministic.

    Examples:

        search_website(
            "youtube",
            "wifi skeleton"
        )

        search_website(
            "google",
            "OpenAI"
        )
    """

    site = (
        str(site or "")
        .strip()
        .lower()
    )

    query = (
        str(query or "")
        .strip()
    )

    if not site:

        return (
            "No website was specified."
        )

    if not query:

        return (
            "No search query was provided."
        )

    # --------------------------------------------------------
    # Normalize common website names
    # --------------------------------------------------------

    aliases = {
        "yt": "youtube",
        "youtube.com": "youtube",
        "www.youtube.com": "youtube",

        "google.com": "google",
        "www.google.com": "google",

        "amazon.com": "amazon",
        "www.amazon.com": "amazon",

        "reddit.com": "reddit",
        "www.reddit.com": "reddit",
    }

    site = aliases.get(
        site,
        site,
    )

    # --------------------------------------------------------
    # Build URL
    # --------------------------------------------------------

    if site == "youtube":

        url = (
            "https://www.youtube.com/results"
            "?search_query="
            + quote_plus(query)
        )

        display_name = "YouTube"

    elif site == "google":

        # Use Google's Web-only results view so AI Overview,
        # generated answers, and other non-web result blocks
        # do not interfere with JARVIS visual targeting.
        #
        # Google Search currently supports the Web filter via
        # the udm=14 parameter.
        url = (
            "https://www.google.com/search?q="
            + quote_plus(query)
            + "&udm=14"
        )

        display_name = "Google"

    elif site == "amazon":

        url = (
            "https://www.amazon.com/s?k="
            + quote_plus(query)
        )

        display_name = "Amazon"

    elif site == "reddit":

        url = (
            "https://www.reddit.com/search/"
            "?q="
            + quote_plus(query)
        )

        display_name = "Reddit"

    else:

        return (
            f"I don't know how to search {site}."
        )

    # --------------------------------------------------------
    # Open through JARVIS CDP browser
    # --------------------------------------------------------

    try:

        from browser_controller import browser_goto

        result = browser_goto(url)

        if not result.get("success", False):

            return (
                f"I couldn't open {display_name} "
                f"for the search."
            )

        # Return a concise completion message. The query/site remain in
        # active browser context and execution logs, so TTS does not need
        # to repeat internal narration.
        return f"{display_name} search complete."

    except Exception as e:

        print(
            "Website search error:",
            e,
        )

        return (
            f"I couldn't search {display_name}."
        )


# ============================================================
# PROGRAM LAUNCHING
# ============================================================

PROGRAM_ALIASES = {

    "notepad":
        "notepad.exe",

    "calculator":
        "calc.exe",

    "calc":
        "calc.exe",

    "paint":
        "mspaint.exe",

    "microsoft paint":
        "mspaint.exe",

    "file explorer":
        "explorer.exe",

    "explorer":
        "explorer.exe",

    "command prompt":
        "cmd.exe",

    "cmd":
        "cmd.exe",

    "powershell":
        "powershell.exe",

    "terminal":
        "wt.exe",

    "windows terminal":
        "wt.exe",

    "edge":
        "msedge.exe",

    "microsoft edge":
        "msedge.exe",

    "firefox":
        "firefox.exe",

    "discord":
        "Discord.exe",

    "spotify":
        "Spotify.exe",

    "steam":
        "steam.exe",

    "visual studio code":
        "code.exe",

    "vs code":
        "code.exe",

    "vscode":
        "code.exe",

    "code":
        "code.exe",

    "word":
        "winword.exe",

    "microsoft word":
        "winword.exe",

    "excel":
        "excel.exe",

    "microsoft excel":
        "excel.exe",

    "powerpoint":
        "powerpnt.exe",

    "microsoft powerpoint":
        "powerpnt.exe",
}


# ============================================================
# WINDOWS START MENU APPLICATIONS
# ============================================================

START_MENU_NAMES = {

    "spotify": {
        "spotify",
    },

    "discord": {
        "discord",
    },

    "steam": {
        "steam",
    },

    "chrome": {
        "google chrome",
        "chrome",
    },

    "edge": {
        "microsoft edge",
        "edge",
    },

    "firefox": {
        "mozilla firefox",
        "firefox",
    },

    "code": {
        "visual studio code",
        "vs code",
        "code",
    },

    "word": {
        "word",
        "microsoft word",
    },

    "excel": {
        "excel",
        "microsoft excel",
    },

    "powerpoint": {
        "powerpoint",
        "microsoft powerpoint",
    },
}


def find_chrome():

    possible_paths = [

        os.path.expandvars(
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"
        ),

        os.path.expandvars(
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
        ),

        os.path.expandvars(
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe"
        ),
    ]

    for path in possible_paths:

        if os.path.exists(path):

            return path

    return None


def find_executable(executable):

    try:

        result = subprocess.run(
            [
                "where.exe",
                executable,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:

            lines = [
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
            ]

            if lines:

                return lines[0]

    except Exception as e:

        print(
            "Executable search error:",
            e,
        )

    return None


def find_start_menu_app(program):
    """
    Search Windows registered Start menu applications.
    """

    aliases = START_MENU_NAMES.get(
        program,
        {program},
    )

    try:

        powershell_command = """
$ErrorActionPreference = 'SilentlyContinue'
Get-StartApps |
    Select-Object Name, AppID |
    ConvertTo-Json -Compress
"""

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_command,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return None

        output = result.stdout.strip()

        if not output:
            return None

        data = json.loads(
            output
        )

        if isinstance(
            data,
            dict,
        ):
            data = [data]

        if not isinstance(
            data,
            list,
        ):
            return None

        normalized_aliases = {
            name.lower().strip()
            for name in aliases
        }

        # ----------------------------------------------------
        # Exact match first.
        # ----------------------------------------------------

        for app in data:

            name = str(
                app.get(
                    "Name",
                    "",
                )
            ).strip()

            app_id = str(
                app.get(
                    "AppID",
                    "",
                )
            ).strip()

            if not name or not app_id:
                continue

            if (
                name.lower()
                in normalized_aliases
            ):

                return {
                    "name": name,
                    "app_id": app_id,
                }

        # ----------------------------------------------------
        # Contains match.
        # ----------------------------------------------------

        for app in data:

            name = str(
                app.get(
                    "Name",
                    "",
                )
            ).strip()

            app_id = str(
                app.get(
                    "AppID",
                    "",
                )
            ).strip()

            if not name or not app_id:
                continue

            lowered_name = (
                name.lower()
            )

            for alias in normalized_aliases:

                if (
                    alias in lowered_name
                    or lowered_name in alias
                ):

                    return {
                        "name": name,
                        "app_id": app_id,
                    }

    except Exception as e:

        print(
            "Start menu search error:",
            e,
        )

    return None


def launch_start_menu_app(app_info):

    if not app_info:
        return False

    app_id = (
        app_info.get(
            "app_id",
            "",
        )
        .strip()
    )

    if not app_id:
        return False

    try:

        windows_dir = os.environ.get(
            "WINDIR",
            r"C:\Windows",
        )

        explorer_path = os.path.join(
            windows_dir,
            "explorer.exe",
        )

        subprocess.Popen(
            [
                explorer_path,
                f"shell:AppsFolder\\{app_id}",
            ]
        )

        return True

    except Exception as e:

        print(
            "Start menu launch error:",
            e,
        )

        return False


def open_program(program):

    if program is None:

        return (
            "No application was specified."
        )

    program = (
        str(program)
        .lower()
        .strip()
    )

    if not program:

        return (
            "No application was specified."
        )

    program = program.removesuffix(
        " application"
    ).strip()

    program = program.removesuffix(
        " app"
    ).strip()

    # --------------------------------------------------------
    # Chrome
    # --------------------------------------------------------

    if program in {
        "chrome",
        "google chrome",
    }:

        try:

            from browser_controller import ensure_cdp_chrome

            if ensure_cdp_chrome():

                return "Opening Chrome."

        except Exception as e:

            print(
                "CDP Chrome launch error:",
                e,
            )

        return (
            "I couldn't start the JARVIS Chrome browser."
        )

    # --------------------------------------------------------
    # Start Menu applications
    # --------------------------------------------------------

    if program in START_MENU_NAMES:

        app_info = (
            find_start_menu_app(
                program
            )
        )

        if launch_start_menu_app(
            app_info
        ):

            display_name = (
                app_info["name"]
                if app_info
                else program.title()
            )

            return (
                f"Opening {display_name}."
            )

    # --------------------------------------------------------
    # Executable alias
    # --------------------------------------------------------

    executable = (
        PROGRAM_ALIASES.get(
            program
        )
    )

    if executable is None:

        return (
            f"I don't have {program} configured "
            f"as an application I can open."
        )

    # --------------------------------------------------------
    # PATH
    # --------------------------------------------------------

    found_path = (
        find_executable(
            executable
        )
    )

    if found_path:

        try:

            subprocess.Popen(
                [found_path]
            )

            return (
                f"Opening {program}."
            )

        except Exception as e:

            print(
                "Program launch error:",
                e,
            )

    # --------------------------------------------------------
    # Direct launch
    # --------------------------------------------------------

    try:

        subprocess.Popen(
            [executable]
        )

        return (
            f"Opening {program}."
        )

    except FileNotFoundError:
        pass

    except Exception as e:

        print(
            "Direct program launch error:",
            e,
        )

    # --------------------------------------------------------
    # Last resort
    # --------------------------------------------------------

    try:

        subprocess.Popen(
            [
                "cmd.exe",
                "/c",
                "start",
                "",
                executable,
            ],
            creationflags=(
                subprocess.CREATE_NO_WINDOW
            ),
        )

        return (
            f"Opening {program}."
        )

    except Exception as e:

        print(
            "Windows start command error:",
            e,
        )

    return (
        f"I couldn't find {program} "
        f"on this computer."
    )


# ============================================================
# AUTONOMOUS CODE CHECKPOINTS
# ============================================================

CODE_CHECKPOINT_DIR = (
    __import__("pathlib").Path.cwd()
    / ".jarvis_checkpoints"
    / "latest"
)

CODE_SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".lua",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".bat",
    ".ps1",
}

CODE_CHECKPOINT_MANIFEST = (
    __import__("pathlib").Path.cwd()
    / ".jarvis_checkpoints"
    / "manifest.json"
)


def _checkpoint_source_files():
    base = __import__("pathlib").Path.cwd().resolve()
    excluded_names = {
        "profile.json",
        ".env",
        ".env.local",
        ".env.production",
    }

    files = []
    for path in iter_project_files(base):
        if not path.is_file():
            continue
        if path.name in excluded_names:
            continue
        if path.suffix.lower() not in CODE_SOURCE_EXTENSIONS:
            continue
        files.append(path)

    return files
def git_task_branch(argument=""):
    """Create or activate a task-scoped Git branch without destructive operations."""
    import json
    from autonomous_engineering import prepare_task_branch

    raw = str(argument or "").strip()
    branch = raw
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                branch = str(payload.get("branch", "") or "").strip()
        except (json.JSONDecodeError, TypeError):
            pass

    if not branch:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "git_task_branch requires a branch name.",
        }

    return prepare_task_branch(branch)

def code_checkpoint(argument=""):
    """Snapshot project source files before an autonomous edit."""
    import json
    import shutil
    from datetime import datetime
    from pathlib import Path

    base = Path.cwd().resolve()
    checkpoint_dir = (base / ".jarvis_checkpoints" / "latest").resolve()
    manifest_path = (base / ".jarvis_checkpoints" / "manifest.json").resolve()

    try:
        checkpoint_dir.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        files = _checkpoint_source_files()
        manifest_files = []

        for source in files:
            relative = source.relative_to(base)
            destination = checkpoint_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            manifest_files.append(str(relative))

        manifest = {
            "created_at": datetime.now().isoformat(),
            "file_count": len(manifest_files),
            "files": manifest_files,
        }

        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        return {
            "success": True,
            "verified": True,
            "message": (
                f"Checkpoint created for {len(manifest_files)} source files."
            ),
            "checkpoint": str(manifest_path),
            "file_count": len(manifest_files),
        }

    except Exception as e:
        return {
            "success": False,
            "verified": False,
            "message": f"Could not create code checkpoint: {e}",
            "error": str(e),
        }


def code_restore_checkpoint(argument=""):
    """Restore source files from the latest autonomous checkpoint."""
    import json
    import shutil
    from pathlib import Path

    base = Path.cwd().resolve()
    checkpoint_dir = (base / ".jarvis_checkpoints" / "latest").resolve()
    manifest_path = (base / ".jarvis_checkpoints" / "manifest.json").resolve()

    if not manifest_path.exists() or not checkpoint_dir.exists():
        return {
            "success": False,
            "verified": False,
            "message": "No JARVIS code checkpoint is available.",
        }

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        manifest_names = {
            str(Path(name)).replace("\\", "/")
            for name in manifest.get("files", [])
        }

        removed_new_files = 0
        for current_path in _checkpoint_source_files():
            relative_name = str(current_path.relative_to(base)).replace("\\", "/")
            if relative_name in manifest_names:
                continue
            try:
                current_path.unlink()
                removed_new_files += 1
            except OSError:
                pass

        restored = 0
        for relative_name in manifest.get("files", []):
            relative = Path(relative_name)
            source = (checkpoint_dir / relative).resolve()
            destination = (base / relative).resolve()

            try:
                source.relative_to(checkpoint_dir)
                destination.relative_to(base)
            except ValueError:
                continue

            if not source.exists():
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            restored += 1

        expected = int(manifest.get("file_count", restored))
        return {
            "success": restored > 0 or expected == 0,
            "verified": restored == expected,
            "message": (
                f"Restored {restored} of {expected} checkpointed source files."
                + (
                    f" Removed {removed_new_files} source file(s) created after the checkpoint."
                    if removed_new_files
                    else ""
                )
            ),
            "restored_files": restored,
            "expected_files": expected,
            "removed_new_source_files": removed_new_files,
        }

    except Exception as e:
        return {
            "success": False,
            "verified": False,
            "message": f"Could not restore code checkpoint: {e}",
            "error": str(e),
        }


# ============================================================
# CODE INSPECTION / VALIDATION
# ============================================================

def code_search(argument=""):
    """Search project text files for a symbol, string, or error message."""
    raw_argument = str(argument or "").strip()
    query = raw_argument

    if raw_argument:
        try:
            payload = json.loads(raw_argument)
            if isinstance(payload, dict) and "query" in payload:
                query = str(payload.get("query") or "").strip()
        except (json.JSONDecodeError, TypeError):
            try:
                payload = ast.literal_eval(raw_argument)
                if isinstance(payload, dict) and "query" in payload:
                    query = str(payload.get("query") or "").strip()
            except (ValueError, SyntaxError):
                pass

    if not query:
        return "Code search query cannot be empty."

    base = __import__("pathlib").Path.cwd().resolve()
    matches = []
    query_lower = query.lower()

    try:
        for path in iter_project_files(base):
            if len(matches) >= 50:
                break

            if not path.is_file():
                continue

            
            try:
                text = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                continue

            for line_number, line in enumerate(text.splitlines(), 1):
                if query_lower in line.lower():
                    relative = path.relative_to(base)
                    matches.append(
                        f"{relative}:{line_number}: {line.strip()}"
                    )

                    if len(matches) >= 50:
                        break

        if not matches:
            return f"No matches found for '{query}'."

        header = (
            f"Found {len(matches)} match(es) for "
            f"'{query}':"
        )

        return header + "\n" + "\n".join(matches)

    except Exception as e:
        return f"Code search failed: {e}"


def code_test(argument=""):
    """Run safe source, test-suite, diff, or browser validation."""


    import ast
    import json
    import sys

    raw = str(argument or "").strip()
    payload = {}

    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            try:
                candidate = ast.literal_eval(raw)

                if isinstance(candidate, dict):
                    payload = candidate
                else:
                    payload = {
                        "mode": "compile",
                        "path": raw,
                    }
            except (ValueError, SyntaxError):
                payload = {
                    "mode": "compile",
                    "path": raw,
                }

    mode = str(
        payload.get("mode", "compile")
    ).strip().lower()

    base = __import__("pathlib").Path.cwd().resolve()

    # Qwen sometimes emits py_compile while the public tool contract
    # uses compile. Accept the harmless alias at the tool boundary.
    if mode in {"py_compile", "python_compile"}:
        mode = "compile"

    if mode in {"git_diff_check", "diff_check", "git_diff"}:
        command = [
            "git",
            "diff",
            "--check",
            "--",
        ]

        timeout = int(payload.get("timeout", 60))

        try:
            completed = subprocess.run(
                command,
                cwd=str(base),
                capture_output=True,
                text=True,
                timeout=max(5, min(timeout, 120)),
            )

            stdout = (completed.stdout or "").strip()
            stderr = (completed.stderr or "").strip()
            success = completed.returncode == 0

            return {
                "success": success,
                "verified": success,
                "retryable": not success,
                "message": (
                    "Git diff whitespace validation passed."
                    if success
                    else "Git diff whitespace validation failed."
                ),
                "exit_code": completed.returncode,
                "stdout": stdout[:6000],
                "stderr": stderr[:6000],
                "mode": "git_diff_check",
                "path": ".",
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "message": f"Git diff check timed out after {timeout} seconds.",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "mode": "git_diff_check",
                "path": ".",
            }

        except Exception as e:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "message": f"Git diff check failed to start: {e}",
                "exit_code": None,
                "stdout": "",
                "stderr": str(e),
                "mode": "git_diff_check",
                "path": ".",
            }

    if mode in {"browser_smoke", "browser_self_test"}:
        try:
            from browser_controller import browser_self_test

            result = browser_self_test()
            if not isinstance(result, dict):
                return {
                    "success": False,
                    "verified": False,
                    "retryable": True,
                    "message": "Code validation failed: browser smoke test returned an invalid result.",
                    "mode": "browser_smoke",
                    "path": "browser_controller.py",
                }

            result = dict(result)
            result["mode"] = "browser_smoke"
            result.setdefault("path", "browser_controller.py")
            return result
        except Exception as e:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "message": f"Browser smoke test failed to start: {e}",
                "mode": "browser_smoke",
                "path": "browser_controller.py",
            }

    target = str(
        payload.get("path", "")
    ).strip()

    if target:
        target_path = (base / target).resolve()

        try:
            target_path.relative_to(base)
        except ValueError:
            return "Code test refused: target is outside the project."

        if not target_path.exists():
            return f"Code test target not found: {target}"

        target_arg = str(target_path)
    else:
        target_arg = ""

    if mode == "compile":
        if not target_arg:
            return "Compile mode requires a Python file path."

        if not target_arg.lower().endswith(".py"):
            return "Compile mode requires a .py file."

        command = [
            sys.executable,
            "-m",
            "py_compile",
            target_arg,
        ]

    elif mode == "pytest":
        command = [
            sys.executable,
            "-m",
            "pytest",
        ]

        if target_arg:
            command.append(target_arg)

        command.append("-q")

    else:
        return (
            "Unsupported code test mode. Use 'compile', 'pytest', "
            "'git_diff_check', or 'browser_smoke'."
        )

    timeout = int(payload.get("timeout", 120))

    try:
        completed = subprocess.run(
            command,
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=max(5, min(timeout, 300)),
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()

        success = completed.returncode == 0

        message = (
            "Code validation passed."
            if success
            else "Code validation failed."
        )

        return {
            "success": success,
            "verified": success,
            "retryable": not success,
            "message": message,
            "exit_code": completed.returncode,
            "stdout": stdout[:6000],
            "stderr": stderr[:6000],
            "mode": mode,
            "path": target or ".",
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": f"Code test timed out after {timeout} seconds.",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "mode": mode,
            "path": target or ".",
        }

    except Exception as e:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "message": f"Code test failed to start: {e}",
            "exit_code": None,
            "stdout": "",
            "stderr": str(e),
            "mode": mode,
            "path": target or ".",
        }


def dev_command(argument=""):
    """Run an allowlisted developer command without invoking a shell."""
    import json
    import shlex
    import sys

    raw = str(argument or "").strip()
    if not raw:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "Developer command cannot be empty.",
        }

    try:
        candidate = json.loads(raw)
        if isinstance(candidate, dict):
            command_text = str(candidate.get("command", "") or "").strip()
            timeout = int(candidate.get("timeout", 120))
        else:
            command_text = raw
            timeout = 120
    except (json.JSONDecodeError, TypeError, ValueError):
        command_text = raw
        timeout = 120

    if not command_text:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "Developer command cannot be empty.",
        }

    try:
        argv = shlex.split(command_text, posix=False)
    except ValueError as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": f"Could not parse developer command: {exc}",
        }

    if not argv:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": "Developer command cannot be empty.",
        }

    shell_operators = ("&&", "||", ";", "|", ">", "<")
    if any(operator in command_text for operator in shell_operators):
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "command": command_text,
            "message": (
                "Shell operators are not allowed in developer commands. "
                "Use one developer command at a time."
            ),
        }

    executable = argv[0].strip().lower()
    allowed = {
        "python",
        "python.exe",
        "py",
        "py.exe",
        "pip",
        "pip.exe",
        "pytest",
        "pytest.exe",
        "ruff",
        "ruff.exe",
        "mypy",
        "mypy.exe",
        "node",
        "node.exe",
        "npm",
        "npm.cmd",
        "npx",
        "npx.cmd",
        "git",
        "git.exe",
    }

    if executable not in allowed:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "message": (
                f"Developer command '{argv[0]}' is not allowed. "
                "Use Python, pip, pytest, ruff, mypy, node, npm, npx, or git."
            ),
        }

    # Always execute from the JARVIS project root and never use shell=True.
    # Rewrite bare Python/pip/pytest tooling to the active interpreter so
    # JARVIS does not accidentally use a different Windows installation.
    if executable in {"python", "python.exe", "py", "py.exe"}:
        argv = [sys.executable, *argv[1:]]
    elif executable in {"pip", "pip.exe"}:
        argv = [sys.executable, "-m", "pip", *argv[1:]]
    elif executable in {"pytest", "pytest.exe"}:
        argv = [sys.executable, "-m", "pytest", *argv[1:]]
    elif executable in {"ruff", "ruff.exe"}:
        argv = [sys.executable, "-m", "ruff", *argv[1:]]
    elif executable in {"mypy", "mypy.exe"}:
        argv = [sys.executable, "-m", "mypy", *argv[1:]]

    base = __import__("pathlib").Path.cwd().resolve()
    timeout = max(5, min(timeout, 300))

    try:
        completed = subprocess.run(
            argv,
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        success = completed.returncode == 0

        return {
            "success": success,
            "verified": success,
            "retryable": not success,
            "command": command_text,
            "exit_code": completed.returncode,
            "stdout": stdout[:12000],
            "stderr": stderr[:12000],
            "message": (
                "Developer command completed successfully."
                if success
                else "Developer command failed."
            ),
        }

    except FileNotFoundError as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": False,
            "command": command_text,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "message": "Developer command executable was not found.",
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "command": command_text,
            "exit_code": None,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
            "message": "Developer command timed out.",
        }

    except Exception as exc:
        return {
            "success": False,
            "verified": False,
            "retryable": True,
            "command": command_text,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "message": f"Developer command failed to start: {exc}",
        }


def code_diagnose(argument=""):
    """Run a bounded project-wide diagnostic pass for autonomous coding work."""
    import ast
    import json
    import sys
    from pathlib import Path

    raw = str(argument or "").strip()
    payload = {}

    if raw:
        try:
            candidate = json.loads(raw)
            if isinstance(candidate, dict):
                payload = candidate
        except (json.JSONDecodeError, TypeError):
            try:
                candidate = ast.literal_eval(raw)
                if isinstance(candidate, dict):
                    payload = candidate
            except (ValueError, SyntaxError):
                payload = {"path": raw}

    base = Path.cwd().resolve()
    target = str(payload.get("path", "") or "").strip()
    run_tests = bool(payload.get("run_tests", True))
    run_lint = bool(payload.get("run_lint", True))
    run_types = bool(payload.get("run_types", False))
    timeout = max(15, min(int(payload.get("timeout", 180)), 300))

    def resolve_target(value: str):
        if not value:
            return None, None

        raw_value = str(value).strip()
        candidate = (base / raw_value).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            return None, f"Target is outside the project: {value}"

        if candidate.exists() and candidate.is_file():
            return candidate, None

        normalized_target = re.sub(r"[^a-z0-9]", "", raw_value.lower())

        if normalized_target:

            matches = []
            try:
                for path in iter_project_files(base):
                    if not path.is_file():
                        continue
                    
                    normalized_name = re.sub(
                        r"[^a-z0-9]",
                        "",
                        path.name.lower(),
                    )

                    if normalized_name == normalized_target:
                        matches.append(path)

                        if len(matches) > 1:
                            break
            except OSError:
                matches = []

            if len(matches) == 1:
                return matches[0], None

        return None, f"Target not found: {value}"

    target_path, target_error = resolve_target(target)
    if target_error:
        return {
            "success": False,
            "verified": False,
            "mode": "diagnose",
            "path": target,
            "checks": [],
            "failures": [target_error],
            "message": "Project diagnostic could not start.",
        }

    if target_path is not None:
        python_files = (
            [target_path]
            if target_path.is_file() and target_path.suffix.lower() == ".py"
            else []
        )
    else:
        python_files = list(
            iter_project_files(
                base,
                suffixes={".py"},
            )
        )

    checks = []
    failures = []

    def run_check(name, command, required=True):
        try:
            completed = subprocess.run(
                command,
                cwd=str(base),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            checks.append({
                "name": name,
                "status": "unavailable",
                "required": required,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            })
            if required:
                failures.append(f"{name} is unavailable: {exc}")
            return None
        except subprocess.TimeoutExpired:
            checks.append({
                "name": name,
                "status": "timeout",
                "required": required,
                "returncode": None,
                "stdout": "",
                "stderr": f"Timed out after {timeout} seconds.",
            })
            if required:
                failures.append(f"{name} timed out after {timeout} seconds.")
            return None
        except Exception as exc:
            checks.append({
                "name": name,
                "status": "error",
                "required": required,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            })
            if required:
                failures.append(f"{name} could not start: {exc}")
            return None

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        passed = completed.returncode == 0

        checks.append({
            "name": name,
            "status": "passed" if passed else "failed",
            "required": required,
            "returncode": completed.returncode,
            "stdout": stdout[:6000],
            "stderr": stderr[:6000],
        })

        if not passed and required:
            detail = stderr or stdout or "No diagnostic output."
            failures.append(
                f"{name} failed (exit {completed.returncode}): {detail[:5000]}"
            )

        return completed

    if target_path is not None:
        if target_path.is_file() and target_path.suffix.lower() == ".py":
            run_check(
                f"compile:{target_path.relative_to(base)}",
                [sys.executable, "-m", "py_compile", str(target_path)],
            )
        else:
            checks.append({
                "name": "python_compile",
                "status": "skipped",
                "required": False,
                "returncode": None,
                "stdout": "",
                "stderr": "Target is not a Python file.",
            })
    elif python_files:
        # Compile only the source files discovered above. Using "." here
        # would recurse into JARVIS's runtime checkpoint directory and let
        # stale/broken checkpoint copies masquerade as real project bugs.
        compile_targets = [
            str(path.relative_to(base))
            for path in python_files
        ]
        run_check(
            "compile_all",
            [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                *compile_targets,
            ],
        )
    else:
        checks.append({
            "name": "compile_all",
            "status": "skipped",
            "required": False,
            "returncode": None,
            "stdout": "",
            "stderr": "No Python source files were discovered.",
        })

    tests_dir = base / "tests"
    target_is_test_file = (
        target_path is not None
        and target_path.is_file()
        and (
            target_path.name.startswith("test_")
            or target_path.name.endswith("_test.py")
            or "tests" in target_path.relative_to(base).parts
        )
    )

    if run_tests and tests_dir.exists() and tests_dir.is_dir() and (
        target_path is None or target_is_test_file
    ):
        test_target = str(target_path) if target_path is not None else "tests"
        run_check(
            "pytest",
            [sys.executable, "-m", "pytest", test_target, "-q"],
        )
    elif run_tests and target_path is not None and not target_is_test_file:
        checks.append({
            "name": "pytest",
            "status": "skipped",
            "required": False,
            "returncode": None,
            "stdout": "",
            "stderr": "Skipped: targeted diagnostic is for an implementation file, not a test file.",
        })
    elif run_tests:
        checks.append({
            "name": "pytest",
            "status": "skipped",
            "required": False,
            "returncode": None,
            "stdout": "",
            "stderr": "No tests directory is present.",
        })

    if run_lint:
        probe = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            cwd=str(base),
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            lint_targets = (
                [str(target_path)]
                if target_path is not None
                else [
                    str(path.relative_to(base))
                    for path in python_files
                ]
            )

            if lint_targets:
                run_check(
                    "ruff",
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        "check",
                        *lint_targets,
                    ],
                    required=False,
                )
            else:
                checks.append({
                    "name": "ruff",
                    "status": "skipped",
                    "required": False,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "No Python source files were discovered.",
                })
        else:
            checks.append({
                "name": "ruff",
                "status": "unavailable",
                "required": False,
                "returncode": None,
                "stdout": "",
                "stderr": "ruff is not installed in the active Python environment.",
            })

    if run_types:
        probe = subprocess.run(
            [sys.executable, "-m", "mypy", "--version"],
            cwd=str(base),
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            type_targets = (
                [str(target_path)]
                if target_path is not None
                else [
                    str(path.relative_to(base))
                    for path in python_files
                ]
            )

            if type_targets:
                run_check(
                    "mypy",
                    [
                        sys.executable,
                        "-m",
                        "mypy",
                        *type_targets,
                    ],
                    required=False,
                )
            else:
                checks.append({
                    "name": "mypy",
                    "status": "skipped",
                    "required": False,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "No Python source files were discovered.",
                })
        else:
            checks.append({
                "name": "mypy",
                "status": "unavailable",
                "required": False,
                "returncode": None,
                "stdout": "",
                "stderr": "mypy is not installed in the active Python environment.",
            })

    required_checks = [
        check
        for check in checks
        if check.get("required")
        and check.get("status") not in {"skipped", "unavailable"}
    ]

    success = bool(required_checks) and not failures

    summary = (
        "Project diagnostic passed."
        if success
        else "Project diagnostic found actionable issues."
        if failures
        else "Project diagnostic completed without required checks."
    )

    message = summary
    if failures:
        message += " " + str(failures[0])

    return {
        "success": success,
        "verified": success,
        "mode": "diagnose",
        "path": target or ".",
        "summary": summary,
        "message": message,
        "checks": checks,
        "failures": failures[:20],
        "check_count": len(checks),
        "failure_count": len(failures),
    }


# ============================================================
# SYSTEM STATUS
# ============================================================

def system_status():

    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    health = runtime_health.collect_health()

    return (
        f"CPU usage is {cpu}%.\n"
        f"RAM usage is {ram.percent}%.\n\n"
        + runtime_health.format_health(health)
    )


# ============================================================
# MAIN TOOL DISPATCHER
# ============================================================

# ============================================================
# BROWSER / CDP TOOLS
# ============================================================

BAREHANDS_TOOLS = {
    "barehands_state",
    "barehands_present",
    "barehands_add_card",
    "barehands_add_image",
    "barehands_clear",
    "barehands_board_state",
}


PRODUCT_RESEARCH_TOOLS = {
    "product_research",
}


N8N_BRIDGE_TOOLS = {
    "n8n_status",
    "n8n_run_workflow",
}


BROWSER_TOOLS = BROWSER_TOOLS


# ============================================================
# FREE PUBLIC API TOOLS
# ============================================================

API_TOOLS = {
    "holiday_lookup",
    "knowledge_lookup",
    "book_search",
    "define_word",
    "research_arxiv",
    "research_crossref",
    "vehicle_lookup",
    "earthquake_search",
    "api_discover",
    "currency_convert",
    "location_lookup",
    "air_quality",
    "weather_alerts",
    "elevation_lookup",
}

EXTENDED_API_TOOLS = {
    "country_info",
    "crypto_price",
    "trivia_question",
    "joke",
    "meal_search",
    "tv_search",
    "music_search",
    "musicbrainz_search",
    "anime_search",
    "anime_episodes",
    "ghibli_search",
    "openalex_search",
    "pubchem_lookup",
    "art_search",
    "nasa_eonet",
    "spacex_lookup",
    "sunrise_sunset",
    "topo_elevation",
    "public_ip",
    "reverse_geocode",
    "news_search",
    "cat_fact",
    "dog_image",
    "osm_search",
    "pokemon_lookup",
    "food_product",
    "cocktail_search",
    "openverse_search",
    "iss_location",
}

GODS_EYE_TOOLS = {
    "gods_eye_status",
    "gods_eye_setup",
    "gods_eye_start",
    "gods_eye_open",
    "gods_eye_stop",
    "gods_eye_contacts",
    "gods_eye_vessels",
    "gods_eye_satellites",
    "gods_eye_launches",
    "gods_eye_cameras",
    "gods_eye_radio",
    "gods_eye_transit",
}

SCREEN_MEMORY_TOOLS = {
    "screen_memory_status",
    "screen_memory_search",
    "screen_memory_recent",
}

API_TOOLS = API_TOOLS | EXTENDED_API_TOOLS


def normalize_tool_result(tool_name: str, result: Any) -> ToolResult:
    """
    Convert an existing raw tool result into the unified ToolResult format.

    Existing tool behavior is preserved in ToolResult.data.
    """

    if isinstance(result, ToolResult):
        return result

    if isinstance(result, dict):
        success = result.get("success")

        if success is True:
            return ToolResult(
                success=True,
                tool=tool_name,
                data=result,
                observation=result,
            )

        if success is False:
            return ToolResult(
                success=False,
                tool=tool_name,
                data=result,
                error=str(
                    result.get("error")
                    or result.get("message")
                    or f"{tool_name} failed"
                ),
                retryable=bool(result.get("retryable", False)),
                observation=result,
            )

    if isinstance(result, str):
        stripped = result.strip()

        if stripped == "Unknown tool requested.":
            return ToolResult(
                success=False,
                tool=tool_name,
                data=result,
                error=result,
                retryable=False,
            )

        file_tools = {
            "write_file",
            "edit_file",
            "read_file",
            "delete_file",
        }

        if tool_name in file_tools:
            file_error_prefixes = (
                "Filename cannot be empty.",
                "Content cannot be None.",
                "Invalid folder path.",
                "Folder not found:",
                "Not a folder:",
                "Invalid filename.",
                "File not found:",
                "Not a file:",
                "old_text cannot be empty.",
                "old_text not found in ",
                "I couldn't write the file:",
                "I couldn't edit the file:",
                "I couldn't delete the file:",
                "Error reading file:",
            )

            if stripped.startswith(file_error_prefixes):
                return ToolResult(
                    success=False,
                    tool=tool_name,
                    data=result,
                    error=result,
                    retryable=False,
                )

        code_test_errors = (
            "Code test refused:",
            "Code test target not found:",
            "Compile mode requires",
            "Unsupported code test mode.",
            "Code test timed out",
            "Code test failed to start:",
            "Code validation failed.",
        )

        if (
            tool_name == "code_test"
            and stripped.startswith(code_test_errors)
        ):
            return ToolResult(
                success=False,
                tool=tool_name,
                data=result,
                error=result,
                retryable=False,
            )

        return ToolResult(
            success=True,
            tool=tool_name,
            data=result,
        )

    if result is None:
        return ToolResult(
            success=False,
            tool=tool_name,
            error=f"{tool_name} returned no result",
        )

    return ToolResult(
        success=True,
        tool=tool_name,
        data=result,
    )


def _parse_browser_object_argument(argument: str, label: str = "Browser") -> dict[str, Any]:
    """Parse a browser tool object argument from JSON or Python-literal dict syntax."""
    raw = str(argument or "").strip()
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as json_exc:
        try:
            payload = ast.literal_eval(raw)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(
                f"{label} argument must be valid JSON: {json_exc}"
            ) from exc

    if not isinstance(payload, dict):
        raise ValueError(
            f"{label} argument must be a JSON object."
        )

    return payload


def run_browser_tool(
    tool_name: str,
    argument: str = "",
):
    """
    Dispatch browser automation tools to browser_controller.py.

    All browser tool results are normalized into ToolResult while
    preserving the original controller payload in ToolResult.data.
    """

    from browser_controller import (
        browser_connect,
        browser_search_google,
        browser_search_bing,
        browser_click_first_bing_result,
        browser_click_first_result,
        browser_click_result,
        browser_back,
        browser_goto,
        browser_page_info,
        browser_page_snapshot,
        browser_find_text,
        browser_refresh,
        browser_forward,
        browser_new_tab,
        browser_switch_tab,
        browser_current_tab,
        browser_close_tab,
        browser_get_links,
        browser_open_link,
        browser_scroll,
    )

    argument = str(argument or "").strip()

    def normalize(result):
        return normalize_tool_result(tool_name, result)

    if tool_name == "browser_agent_status":
        from browser_agent import browser_agent_status
        return normalize(browser_agent_status())

    if tool_name == "browser_agent_run":
        from browser_agent import browser_agent_run
        return normalize(browser_agent_run(argument))

    if tool_name == "browser_connect":
        return normalize(browser_connect())

    if tool_name == "browser_search_google":
        return normalize(browser_search_google(argument))

    if tool_name == "browser_search_bing":
        return normalize(browser_search_bing(argument))

    if tool_name == "browser_click_first_bing_result":
        query = argument if argument else None
        return normalize(browser_click_first_bing_result(query))

    if tool_name == "browser_click_first_result":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="First-result browser",
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                tool=tool_name,
                error=str(exc),
            )

        return normalize(
            browser_click_first_result(
                site=payload.get("site", ""),
                query=payload.get("query", ""),
            )
        )

    if tool_name == "browser_click_result":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="Result browser",
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                tool=tool_name,
                error=str(exc),
            )

        return normalize(
            browser_click_result(
                index=payload.get(
                    "index",
                    payload.get(
                        "number",
                        payload.get("result_number", 1),
                    ),
                ),
                site=payload.get("site", ""),
                query=payload.get("query", ""),
            )
        )

    if tool_name == "browser_back":
        return normalize(browser_back())

    if tool_name == "browser_goto":
        return normalize(browser_goto(argument))

    if tool_name in {
        "browser_find_element",
        "browser_click_element",
        "browser_fill_element",
        "browser_press_key",
        "browser_wait_for_element",
        "browser_extract_text",
        "browser_find_text",
    }:
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="DOM browser tool",
            )
        except ValueError as exc:
            return ToolResult(
                success=False,
                tool=tool_name,
                error=str(exc),
            )

        from browser_controller import (
            browser_find_element,
            browser_click_element,
            browser_fill_element,
            browser_press_key,
            browser_wait_for_element,
            browser_extract_text,
            browser_find_text,
        )

        # Preserve compatibility with older monkeypatches/alternate browser
        # controller implementations: omit the optional accessible-name
        # argument when the caller did not provide one.
        dom_kwargs = {
            "selector": payload.get("selector", ""),
            "text": payload.get("text", ""),
            "role": payload.get("role", ""),
        }
        if payload.get("name"):
            dom_kwargs["name"] = payload.get("name")

        if tool_name == "browser_find_element":
            return normalize(browser_find_element(**dom_kwargs))

        if tool_name == "browser_click_element":
            return normalize(browser_click_element(**dom_kwargs))

        if tool_name == "browser_fill_element":
            fill_kwargs = {
                "value": payload.get("value", ""),
                **dom_kwargs,
            }
            return normalize(browser_fill_element(**fill_kwargs))

        if tool_name == "browser_press_key":
            press_kwargs = {
                "key": payload.get("key", ""),
                **dom_kwargs,
            }
            return normalize(browser_press_key(**press_kwargs))

        if tool_name == "browser_wait_for_element":
            wait_kwargs = {
                **dom_kwargs,
                "timeout": int(payload.get("timeout", 10000)),
            }
            return normalize(browser_wait_for_element(**wait_kwargs))

        if tool_name == "browser_extract_text":
            return normalize(browser_extract_text(**dom_kwargs))

        if tool_name == "browser_find_text":
            return normalize(
                browser_find_text(
                    query=payload.get("query", ""),
                    context_chars=payload.get("context_chars", 120),
                    max_matches=payload.get("max_matches", 3),
                )
            )

    if tool_name == "browser_refresh":
        return normalize(browser_refresh())

    if tool_name == "browser_forward":
        return normalize(browser_forward())

    if tool_name == "browser_current_tab":
        return normalize(browser_current_tab())

    if tool_name == "browser_new_tab":
        return normalize(browser_new_tab(argument))

    if tool_name == "browser_switch_tab":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="Browser tab",
            )
        except ValueError as exc:
            return ToolResult(success=False, tool=tool_name, error=str(exc))
        return normalize(browser_switch_tab(payload.get("index", "current")))

    if tool_name == "browser_close_tab":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="Browser tab",
            )
        except ValueError as exc:
            return ToolResult(success=False, tool=tool_name, error=str(exc))
        return normalize(browser_close_tab(payload.get("index", "current")))

    if tool_name == "browser_get_links":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="Browser links",
            )
        except ValueError as exc:
            return ToolResult(success=False, tool=tool_name, error=str(exc))
        return normalize(browser_get_links(payload.get("limit", 30)))

    if tool_name == "browser_open_link":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="Browser link",
            )
        except ValueError as exc:
            return ToolResult(success=False, tool=tool_name, error=str(exc))
        return normalize(
            browser_open_link(
                index=payload.get("index", 1),
                text=payload.get("text", ""),
                href=payload.get("href", ""),
            )
        )

    if tool_name == "browser_scroll":
        try:
            payload = _parse_browser_object_argument(
                argument,
                label="Browser scroll",
            )
        except ValueError:
            raw = str(argument or "").strip().lower()
            return normalize(browser_scroll(raw or "down", 500))
        return normalize(
            browser_scroll(
                payload.get("direction", "down"),
                payload.get("distance", 500),
            )
        )

    if tool_name == "browser_page_info":
        return normalize(browser_page_info())

    if tool_name == "browser_page_snapshot":
        return normalize(browser_page_snapshot())

    return ToolResult(
        success=False,
        tool=tool_name,
        error=f"Unknown browser tool: {tool_name}",
    )

def _run_tool_raw(
    tool_name: str,
    argument: str = "",
) -> Union[str, Dict[str, Any]]:
    """
    Internal JARVIS tool dispatcher.

    This preserves the existing raw tool behavior. The public
    run_tool() wrapper below converts the result into ToolResult.
    """

    # --------------------------------------------------------
    # ROBLOX STUDIO MCP
    # --------------------------------------------------------

    if tool_name in ROBLOX_MCP_TOOLS:
        from roblox_mcp import (
            roblox_mcp_setup,
            roblox_mcp_status,
        )

        if tool_name == "roblox_mcp_status":
            return roblox_mcp_status(argument)

        return roblox_mcp_setup(argument)

    if tool_name.startswith("roblox__"):
        from roblox_mcp import run_roblox_tool

        return run_roblox_tool(
            tool_name[len("roblox__"):],
            argument,
        )

    # --------------------------------------------------------
    # BROWSER / CDP
    # --------------------------------------------------------

    if tool_name in BAREHANDS_TOOLS:
        return getattr(barehands_tools, tool_name)(argument)

    if tool_name in PRODUCT_RESEARCH_TOOLS:
        from product_research import research_product
        return research_product(argument)

    if tool_name in N8N_BRIDGE_TOOLS:
        from n8n_bridge import n8n_status, run_n8n_workflow

        if tool_name == "n8n_status":
            return n8n_status()

        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "message": "n8n workflow arguments must be valid JSON.",
            }

        if not isinstance(payload, dict):
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "message": "n8n workflow arguments must be a JSON object.",
            }

        return run_n8n_workflow(
            request=str(payload.get("request") or "").strip(),
            workflow_class=str(payload.get("workflow_class") or "").strip(),
            context=payload.get("context") if isinstance(payload.get("context"), dict) else {},
        )

    if tool_name in SYSTEM_HEALTH_TOOLS:
        from integration_health import run_integration_health

        return run_integration_health(argument)

    if tool_name.startswith("n8n_mcp__"):
        from n8n_mcp import call_tool

        remote_tool = tool_name[len("n8n_mcp__"):].strip()
        if not remote_tool:
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "message": "n8n MCP tool name is empty.",
            }

        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "message": "n8n MCP tool arguments must be valid JSON.",
            }

        if not isinstance(payload, dict):
            return {
                "success": False,
                "verified": False,
                "retryable": False,
                "terminal": True,
                "execution_owner": "n8n",
                "message": "n8n MCP tool arguments must be a JSON object.",
            }

        return call_tool(remote_tool, payload)

    if tool_name == "n8n_mcp_status":
        from n8n_mcp import status
        return status()

    if tool_name == "n8n_mcp_list_tools":
        from n8n_mcp import list_tools
        return {
            "success": True,
            "verified": True,
            "tools": list_tools(),
        }

    if tool_name == "n8n_workflow_architect":
        from n8n_workflow_architect import run_architect
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "verified": False, "message": "n8n_workflow_architect expects JSON."}
        return run_architect(payload if isinstance(payload, dict) else {})

    if tool_name == "n8n_workflow_builder":
        from n8n_workflow_builder import run_builder
        try:
            payload = json.loads(str(argument or "{}"))
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "verified": False, "message": "n8n_workflow_builder expects JSON."}
        return run_builder(payload if isinstance(payload, dict) else {})

    if tool_name == "tool_contract_audit":
        from tool_registry import tool_contract_audit
        return tool_contract_audit()

    if tool_name in ADAPTIVE_RUNTIME_TOOLS:
        from adaptive_runtime import run_adaptive_tool

        return run_adaptive_tool(tool_name, argument)

    if tool_name in BROWSER_TOOLS:
        return run_browser_tool(
            tool_name,
            argument,
        )

    if tool_name in ANIPY_TOOLS:
        from anipy_integration import run_anipy_tool

        return run_anipy_tool(
            tool_name,
            argument,
        )

    if tool_name in UNREAL_MCP_TOOLS:
        from unreal_mcp import run_unreal_mcp_tool

        return run_unreal_mcp_tool(
            tool_name,
            argument,
        )

    if tool_name in CONTEXT_MEMORY_TOOLS:
        from agent_context import run_context_tool

        return run_context_tool(
            tool_name,
            argument,
        )

    if tool_name in AGENT_SKILL_TOOLS:
        if tool_name == "harness_review":
            from harness_policy import review_plan
            try:
                payload = json.loads(str(argument or "{}"))
            except (json.JSONDecodeError, TypeError):
                return {"success": False, "message": "harness_review expects JSON."}
            steps = payload.get("steps", []) if isinstance(payload, dict) else []
            return review_plan(steps)

        from skill_catalog import run_skill_tool
        return run_skill_tool(tool_name, argument)

    if tool_name in EXTENDED_API_TOOLS:
        from extended_api_tools import run_extended_api_tool

        return run_extended_api_tool(
            tool_name,
            argument,
        )

    if tool_name in GODS_EYE_TOOLS:
        from gods_eye import run_gods_eye_tool

        return run_gods_eye_tool(
            tool_name,
            argument,
        )

    if tool_name in SCREEN_MEMORY_TOOLS:
        from screen_memory import run_screen_memory_tool

        return run_screen_memory_tool(
            tool_name,
            argument,
        )


    # --------------------------------------------------------
    # FREE PUBLIC API HUB
    # --------------------------------------------------------

    if tool_name in API_TOOLS:
        from api_tools import run_api_tool

        return run_api_tool(
            tool_name,
            argument,
        )


    # --------------------------------------------------------
    # WEATHER
    # --------------------------------------------------------

    if tool_name == "weather":

        return weather(
            argument
        )

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    elif tool_name == "current_time":

        return current_time(
            argument
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    elif tool_name == "current_date":

        return current_date()

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    elif tool_name == "wait":

        return wait_seconds(
            argument
        )

    # --------------------------------------------------------
    # WEBSITE
    # --------------------------------------------------------

    elif tool_name == "open_website":

        return open_website(
            argument
        )

    # --------------------------------------------------------
    # WEBSITE SEARCH
    # --------------------------------------------------------

    elif tool_name == "search_website":

        argument = str(
            argument or ""
        ).strip()

        if "|" not in argument:

            return (
                "Invalid website search format. "
                "Expected: site|query"
            )

        site, query = argument.split(
            "|",
            1,
        )

        site = site.strip()
        query = query.strip()

        if not site:

            return (
                "Invalid website search: "
                "website is missing."
            )

        if not query:

            return (
                "Invalid website search: "
                "search query is missing."
            )

        return search_website(
            site,
            query,
        )

    # --------------------------------------------------------
    # PROGRAM
    # --------------------------------------------------------

    elif tool_name == "open_program":

        return open_program(
            argument
        )

    # --------------------------------------------------------
    # AUTONOMOUS CODE CHECKPOINTS
    # --------------------------------------------------------

    elif tool_name == "git_task_branch":

        return git_task_branch(argument)

    elif tool_name == "code_checkpoint":

        return code_checkpoint(argument)

    elif tool_name == "code_restore_checkpoint":

        return code_restore_checkpoint(argument)

    # --------------------------------------------------------
    # CODE INSPECTION / VALIDATION
    # --------------------------------------------------------

    elif tool_name == "code_search":

        return code_search(argument)

    elif tool_name == "code_test":

        return code_test(argument)


    elif tool_name == "dev_command":

        return dev_command(argument)

    elif tool_name == "code_diagnose":

        return code_diagnose(argument)

    # --------------------------------------------------------
    # JARVIS PLATFORM / SELF-OBSERVABILITY
    # --------------------------------------------------------

    elif tool_name == "jarvis_doctor":
        import jarvis_doctor
        raw = str(argument or "").strip()
        deep = raw.lower() in {"deep", "true", "1", "yes", "doctor"}
        run_tests = False
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    deep = bool(payload.get("deep", deep))
                    run_tests = bool(payload.get("run_tests", False))
            except (json.JSONDecodeError, TypeError):
                pass
        result = jarvis_doctor.run_doctor(deep=deep, run_tests=run_tests)
        result["report"] = jarvis_doctor.format_doctor_report(result)
        return result

    elif tool_name == "tool_health":
        from resilience_kernel import tool_health_status
        return {
            "success": True,
            "verified": True,
            **tool_health_status(),
        }

    elif tool_name == "memory_remember":
        import local_memory
        raw = str(argument or "").strip()
        payload = {}
        if raw:
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict):
                    payload = candidate
            except (json.JSONDecodeError, TypeError):
                payload = {"text": raw}
        return local_memory.remember(
            str(payload.get("text", "") or ""),
            kind=str(payload.get("kind", "fact") or "fact"),
            tags=payload.get("tags") if isinstance(payload.get("tags"), list) else [],
        )

    elif tool_name == "memory_recall":
        import local_memory
        raw = str(argument or "").strip()
        payload = {}
        if raw:
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict):
                    payload = candidate
            except (json.JSONDecodeError, TypeError):
                payload = {"query": raw}
        return {
            "success": True,
            "verified": True,
            "query": str(payload.get("query", "") or ""),
            "results": local_memory.recall(
                str(payload.get("query", "") or ""),
                limit=int(payload.get("limit", 5) or 5),
                kind=str(payload.get("kind", "") or ""),
            ),
        }

    elif tool_name == "memory_forget":
        import local_memory
        raw = str(argument or "").strip()
        query = raw
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    query = str(payload.get("query", "") or "")
            except (json.JSONDecodeError, TypeError):
                pass
        return local_memory.forget(query)

    elif tool_name == "healing_history":
        from healing_kernel import healing_history
        raw = str(argument or "").strip()
        try:
            limit = int(raw) if raw else 10
        except (TypeError, ValueError):
            limit = 10
        return {
            "success": True,
            "verified": True,
            "events": healing_history(limit=limit),
        }

    elif tool_name == "healing_hints":
        from healing_kernel import healing_hints
        raw = str(argument or "").strip()
        payload = {}
        if raw:
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict):
                    payload = candidate
            except (json.JSONDecodeError, TypeError):
                payload = {"error": raw}
        return {
            "success": True,
            "verified": True,
            "hints": healing_hints(
                str(payload.get("tool", "") or ""),
                category=str(payload.get("category", "") or ""),
                error=str(payload.get("error", "") or ""),
                limit=int(payload.get("limit", 5) or 5),
            ),
        }

    elif tool_name == "tool_reset":
        from resilience_kernel import get_resilience
        name = str(argument or "").strip()
        if name:
            try:
                payload = json.loads(name)
                if isinstance(payload, dict):
                    name = str(payload.get("tool", "") or "").strip()
            except (json.JSONDecodeError, TypeError):
                pass
        reset = get_resilience().reset_tool(name) if name else False
        return {
            "success": bool(name),
            "verified": bool(name),
            "tool": name,
            "reset": reset,
            "message": (
                f"Reset resilience state for {name}."
                if name
                else "Tool name is required."
            ),
        }

    elif tool_name == "memory_status":
        import local_memory
        return local_memory.memory_status()

    elif tool_name in {"autonomy_status", "strategy_history", "regression_status"}:
        from strategy_selector import (
            autonomy_status,
            strategy_history,
            regression_status,
        )
        raw = str(argument or "").strip()
        if tool_name == "autonomy_status":
            return {
                "success": True,
                "verified": True,
                **autonomy_status(),
            }

        payload = {}
        if raw:
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict):
                    payload = candidate
                else:
                    payload = {"request": raw}
            except (json.JSONDecodeError, TypeError):
                payload = {"request": raw}

        request = str(payload.get("request", "") or "")
        limit = int(payload.get("limit", 10) or 10)
        if tool_name == "strategy_history":
            return {
                "success": True,
                "verified": True,
                "strategies": strategy_history(request, limit=limit),
            }
        return {
            "success": True,
            "verified": True,
            **regression_status(request),
        }

    elif tool_name in {
        "jarvis_quickcheck",
        "resource_status",
        "process_snapshot",
        "project_snapshot",
        "service_status",
        "dependency_status",
    }:
        import qol_tools
        handler = getattr(qol_tools, tool_name)
        if tool_name in {"process_snapshot", "service_status"}:
            return handler(argument)
        return handler()

    elif tool_name == "code_index_rebuild":
        import code_index
        return code_index.rebuild()

    elif tool_name == "code_index_status":
        import code_index
        return code_index.status()

    elif tool_name == "jarvis_capabilities":
        inventory = {
            "browser": sorted(BROWSER_TOOLS),
            "n8n": sorted(N8N_TOOLS),
            "platform": sorted(JARVIS_PLATFORM_TOOLS),
            "adaptive": sorted(ADAPTIVE_RUNTIME_TOOLS),
            "context": sorted(CONTEXT_MEMORY_TOOLS),
            "skills": sorted(AGENT_SKILL_TOOLS),
            "gods_eye": sorted(GODS_EYE_TOOLS),
            "screen_memory": sorted(SCREEN_MEMORY_TOOLS),
        }
        try:
            from roblox_mcp import get_roblox_planner_tools
            inventory["roblox"] = sorted(get_roblox_planner_tools().keys())
        except Exception:
            inventory["roblox"] = []
        try:
            from unreal_mcp import get_unreal_planner_tool_descriptions
            inventory["unreal"] = sorted(get_unreal_planner_tool_descriptions().keys())
        except Exception:
            inventory["unreal"] = []
        return {
            "success": True,
            "verified": True,
            "categories": {key: len(value) for key, value in inventory.items()},
            "tools": inventory,
        }

    elif tool_name == "ollama_models":
        from model_manager import ModelManager
        manager = ModelManager()
        try:
            models = manager.list_local_models()
        except Exception as exc:
            return {
                "success": False,
                "verified": False,
                "retryable": True,
                "message": f"Could not query local Ollama models: {exc}",
                "configured": {
                    "chat": manager.chat_model,
                    "planner": manager.planner_model,
                    "change_planner": manager.change_planner_model,
                    "coding": manager.coding_model,
                    "coding_fallback": manager.coding_fallback_model,
                },
                "available": [],
                "missing_configured": {},
            }
        names = sorted({
            str(item.get("name") or item.get("model") or "").strip()
            for item in models
            if str(item.get("name") or item.get("model") or "").strip()
        })
        configured = {
            "chat": manager.chat_model,
            "planner": manager.planner_model,
            "change_planner": manager.change_planner_model,
            "coding": manager.coding_model,
            "coding_fallback": manager.coding_fallback_model,
        }
        return {
            "success": True,
            "verified": True,
            "configured": configured,
            "available": names,
            "missing_configured": {
                role: model
                for role, model in configured.items()
                if model and model not in names
            },
        }

    # --------------------------------------------------------
    # SYSTEM
    # --------------------------------------------------------

    elif tool_name == "system_status":

        return system_status()

    elif tool_name == "startup_status":

        return startup_manager.status_text()

    elif tool_name == "enable_startup":

        return (
            "JARVIS will start with Windows."
            if startup_manager.enable_startup()
            else "I couldn't enable Windows startup for JARVIS."
        )

    elif tool_name == "disable_startup":

        return (
            "JARVIS will no longer start with Windows."
            if startup_manager.disable_startup()
            else "I couldn't disable Windows startup for JARVIS."
        )

    elif tool_name == "task_history":

        return task_memory.format_recent(5)

    # --------------------------------------------------------
    # FILE TOOLS
    # --------------------------------------------------------

    elif tool_name == "create_folder":

        return file_tools.create_folder(
            argument
        )

    elif tool_name == "list_files":

        return file_tools.list_files(
            argument
        )

    elif tool_name == "find_file":

        return file_tools.find_file(
            argument
        )

    elif tool_name == "open_folder":

        return file_tools.open_folder(
            argument
        )

    elif tool_name == "write_file":

        if "|||" not in argument:

            return (
                "Invalid write_file format. "
                "Use: filename|||content"
            )

        parts = argument.split(
            "|||",
            1,
        )

        filename = (
            parts[0]
            .strip()
        )

        content = (
            parts[1]
            if len(parts) > 1
            else ""
        )

        return file_tools.write_file(
            filename,
            content,
            overwrite=True,
        )

    elif tool_name == "read_file":

        return file_tools.read_file(
            argument
        )

    elif tool_name == "edit_file":

        if argument.count(
            "|||"
        ) < 2:

            return (
                "Invalid edit_file format. "
                "Use: filename|||old_text|||new_text"
            )

        parts = argument.split(
            "|||",
            2,
        )

        filename = (
            parts[0]
            .strip()
        )

        old_text = parts[1]

        new_text = (
            parts[2]
            if len(parts) > 2
            else ""
        )

        return file_tools.edit_file(
            filename,
            old_text,
            new_text,
        )

    elif tool_name == "delete_file":

        return file_tools.delete_file(
            argument
        )

    # --------------------------------------------------------
    # WEB SEARCH
    # --------------------------------------------------------

    elif tool_name == "web_search":

        results = web_tools.web_search(
            argument
        )

        return (
            web_summary.summarize_web_results(
                results
            )
        )

    # --------------------------------------------------------
    # JARVIS STATUS
    # --------------------------------------------------------

    elif tool_name == "jarvis_status":

        return jarvis_status.get_status()

    # --------------------------------------------------------
    # SCREEN CAPTURE
    # --------------------------------------------------------

    elif tool_name == "capture_screen":

        return (
            screen_vision.capture_screen()
        )

    elif tool_name == "screenshot":

        return (
            screen_vision.capture_screen()
        )

    # --------------------------------------------------------
    # SCREEN SIZE
    # --------------------------------------------------------

    elif tool_name == "screen_size":

        return (
            screen_vision.get_screen_size()
        )

    # --------------------------------------------------------
    # ACTIVE WINDOW
    # --------------------------------------------------------

    elif tool_name == "get_active_window":

        return (
            screen_vision.get_active_window()
        )

    elif tool_name == "active_window":

        return (
            screen_vision.get_active_window()
        )

    # --------------------------------------------------------
    # SCREEN ANALYSIS
    # --------------------------------------------------------

    elif tool_name == "analyze_screen":

        return (
            screen_vision.analyze_screen(
                argument
            )
        )

    # --------------------------------------------------------
    # MOUSE
    # --------------------------------------------------------

    elif tool_name == "move_mouse":

        return (
            screen_vision.move_mouse_to_target(
                argument
            )
        )

    elif tool_name == "click_screen":

        return (
            screen_vision.click_screen_target(
                argument
            )
        )

    elif tool_name == "double_click_screen":

        return (
            screen_vision.double_click_screen_target(
                argument
            )
        )

    elif tool_name == "right_click_screen":

        return (
            screen_vision.right_click_screen_target(
                argument
            )
        )

    # --------------------------------------------------------
    # SCROLL
    # --------------------------------------------------------

    elif tool_name == "scroll_screen":

        return (
            screen_vision.scroll_screen(
                argument
            )
        )

    # --------------------------------------------------------
    # SCREEN VERIFICATION
    # --------------------------------------------------------

    elif tool_name == "verify_screen":

        return (
            screen_vision.verify_screen_state(
                argument
            )
        )

    # --------------------------------------------------------
    # KEYBOARD
    # --------------------------------------------------------

    elif tool_name == "type_text":

        return (
            screen_vision.type_text(
                argument
            )
        )

    elif tool_name == "press_key":

        return (
            screen_vision.press_key(
                argument
            )
        )

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    else:

        return (
            "Unknown tool requested."
        )


def run_tool(
    tool_name: str,
    argument: str = "",
) -> ToolResult:
    """
    Public JARVIS tool dispatcher.

    Every execution is observed by the runtime resilience layer. Circuit
    breaking remains bounded and fail-closed while existing tool behavior is
    preserved inside the normalized ToolResult contract.
    """
    started = time.perf_counter()

    try:
        from resilience_kernel import get_resilience
        resilience = get_resilience()
        guard = resilience.before(tool_name)
        if not guard.get("allowed", True):
            return ToolResult(
                success=False,
                tool=tool_name,
                error=str(guard.get("reason") or "Tool temporarily unavailable."),
                retryable=True,
                observation=guard,
            )
    except Exception:
        resilience = None

    try:
        result = _run_tool_raw(
            tool_name,
            argument,
        )
    except Exception as exc:
        result = ToolResult(
            success=False,
            tool=tool_name,
            error=f"{type(exc).__name__}: {exc}",
            retryable=False,
        )

    normalized = normalize_tool_result(
        tool_name,
        result,
    )

    if resilience is not None:
        try:
            resilience.record(
                tool_name,
                success=normalized.success,
                retryable=normalized.retryable,
                error=normalized.error,
                duration_ms=(time.perf_counter() - started) * 1000,
                argument=argument,
            )
        except Exception:
            pass

    return normalized
