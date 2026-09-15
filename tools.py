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

import file_tools
import jarvis_status
import screen_vision
import web_summary
import web_tools

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
        weather in Chicago
        weather for Chicago
        weather in Chicago today
        weather in Chicago tomorrow
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

        url = (
            "https://www.google.com/search?q="
            + quote_plus(query)
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
    # Open directly in the browser
    # --------------------------------------------------------

    try:

        opened = webbrowser.open(
            url
        )

        if not opened:

            return (
                f"I couldn't open {display_name} "
                f"for the search."
            )

        return (
            f"Searching {display_name} for {query}."
        )

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

        chrome_path = find_chrome()

        if chrome_path:

            try:

                subprocess.Popen(
                    [chrome_path]
                )

                return "Opening Chrome."

            except Exception as e:

                print(
                    "Chrome launch error:",
                    e,
                )

        chrome_path = (
            find_executable(
                "chrome.exe"
            )
        )

        if chrome_path:

            try:

                subprocess.Popen(
                    [chrome_path]
                )

                return "Opening Chrome."

            except Exception:
                pass

        app_info = (
            find_start_menu_app(
                "chrome"
            )
        )

        if launch_start_menu_app(
            app_info
        ):

            return "Opening Chrome."

        return (
            "I couldn't find Google Chrome "
            "on this computer."
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
# SYSTEM STATUS
# ============================================================

def system_status():

    cpu = psutil.cpu_percent(
        interval=1
    )

    ram = psutil.virtual_memory()

    return (
        f"CPU usage is {cpu}%.\n"
        f"RAM usage is {ram.percent}%."
    )


# ============================================================
# MAIN TOOL DISPATCHER
# ============================================================

def run_tool(
    tool_name: str,
    argument: str = "",
) -> Union[str, Dict[str, Any]]:
    """
    Main JARVIS tool dispatcher.
    """

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
    # SYSTEM
    # --------------------------------------------------------

    elif tool_name == "system_status":

        return system_status()

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

        return jarvis_status.get_status(
            "gemma4:e2b"
        )

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