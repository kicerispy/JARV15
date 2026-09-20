from tool_result import ToolResult

from decimal import Decimal

"""

JARVIS API Hub



Free/no-key public API integrations used by JARVIS.



These APIs are deliberately kept behind one module so the planner

and main tool dispatcher do not become tightly coupled to individual

third-party services.

"""



import json

import re

import xml.etree.ElementTree as ET

from urllib.parse import quote_plus



import requests
import time





USER_AGENT = "JARVIS/1.0"





# ============================================================

# COMMON HTTP HELPERS

# ============================================================



def _get_json(

    url: str,

    *,

    params=None,

    timeout: float = 12.0,

    headers=None,

):

    request_headers = {

        "User-Agent": USER_AGENT,

        "Accept": "application/json",

    }



    if headers:

        request_headers.update(headers)



    response = requests.get(

        url,

        params=params,

        headers=request_headers,

        timeout=timeout,

    )



    response.raise_for_status()

    return response.json()





def _post_json(

    url: str,

    *,

    data=None,

    timeout: float = 12.0,

    headers=None,

):

    request_headers = {

        "User-Agent": USER_AGENT,

        "Accept": "application/json",

    }



    if headers:

        request_headers.update(headers)



    response = requests.post(

        url,

        data=data,

        headers=request_headers,

        timeout=timeout,

    )



    response.raise_for_status()

    return response.json()





def _error(tool: str, message: str):

    message_text = str(message).lower()



    transient_markers = (

        "timed out",

        "timeout",

        "connection error",

        "connection reset",

        "connection aborted",

        "connection refused",

        "name resolution",

        "failed to resolve",

        "getaddrinfo failed",

        "temporary failure",

        "temporarily unavailable",

        "service unavailable",

        "bad gateway",

        "gateway timeout",

        "too many requests",

        "429",

        "502",

        "503",

        "504",

    )



    retryable = any(

        marker in message_text

        for marker in transient_markers

    )



    return {

        "success": False,

        "tool": tool,

        "error": message,

        "retryable": retryable,

    }





def _success(tool: str, data, message: str = ""):

    result = {

        "success": True,

        "tool": tool,

        "data": data,

    }



    if message:

        result["message"] = message



    return result





# ============================================================

# HOLIDAYS

# ============================================================



def holiday_lookup(argument: str = ""):

    """

    Get public holidays.



    Input:

        "US"

        "US 2026"

        "United States 2026" is not guaranteed; ISO country

        codes are preferred.

    """



    tool = "holiday_lookup"



    raw = str(argument or "").strip()



    if not raw:

        return _error(

            tool,

            "Provide a country code, for example 'US' or 'US 2026'.",

        )



    # Accept common country names as well as ISO codes so the

    # planner does not need to produce perfectly normalized arguments.

    country_aliases = {

        "united states": "US",

        "united states of america": "US",

        "usa": "US",

        "u.s.": "US",

        "u.s.a.": "US",

        "united kingdom": "GB",

        "great britain": "GB",

        "england": "GB",

        "canada": "CA",

        "australia": "AU",

        "new zealand": "NZ",

        "germany": "DE",

        "france": "FR",

        "italy": "IT",

        "spain": "ES",

        "mexico": "MX",

        "brazil": "BR",

        "india": "IN",

        "japan": "JP",

        "china": "CN",

        "south korea": "KR",

        "ireland": "IE",

        "netherlands": "NL",

        "switzerland": "CH",

        "sweden": "SE",

        "norway": "NO",

        "denmark": "DK",

    }



    country_alias_match = re.fullmatch(

        r"(.+?)\s+(20\d{2})",

        raw.strip(),

        re.IGNORECASE,

    )



    if country_alias_match:

        country_phrase = (

            country_alias_match.group(1)

            .strip()

            .lower()

        )



        alias_code = country_aliases.get(

            country_phrase

        )



        if alias_code:

            raw = (

                f"{alias_code} "

                f"{country_alias_match.group(2)}"

            )



    else:

        alias_code = country_aliases.get(

            raw.strip().lower()

        )



        if alias_code:

            raw = alias_code



    parts = raw.upper().split()



    country = parts[0]

    year = 2026



    if len(parts) > 1:

        try:

            year = int(parts[1])

        except ValueError:

            return _error(

                tool,

                "Invalid year. Example: 'US 2026'.",

            )



    if not re.fullmatch(r"[A-Z]{2}", country):

        return _error(

            tool,

            "Country must be a two-letter ISO code such as US, CA, or GB.",

        )



    # Community API.

    url = (

        "https://date.nager.at/api/v3/"

        f"publicholidays/{year}/{country}"

    )



    try:

        data = _get_json(url)



        holidays = []



        for item in data:

            holidays.append({

                "date": item.get("date"),

                "name": item.get("name"),

                "local_name": item.get("localName"),

                "country_code": item.get("countryCode"),

                "global": item.get("global"),

                "counties": item.get("counties") or [],

                "types": item.get("types") or [],

            })



        return _success(

            tool,

            {

                "country": country,

                "year": year,

                "holidays": holidays,

            },

            f"Found {len(holidays)} public holidays for "

            f"{country} in {year}.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"Holiday lookup failed: {exc}",

        )





# ============================================================

# WIKIPEDIA

# ============================================================



def knowledge_lookup(argument: str = ""):

    """

    Look up a concise Wikipedia article summary.

    """



    tool = "knowledge_lookup"



    query = str(argument or "").strip()



    if not query:

        return _error(

            tool,

            "Provide a topic to look up.",

        )



    url = (

        "https://en.wikipedia.org/api/rest_v1/page/summary/"

        + quote_plus(query.replace(" ", "_"))

    )



    try:

        data = _get_json(url)



        return _success(

            tool,

            {

                "title": data.get("title"),

                "description": data.get("description"),

                "summary": data.get("extract"),

                "url": (

                    data.get("content_urls", {})

                    .get("desktop", {})

                    .get("page")

                ),

                "thumbnail": (

                    data.get("thumbnail", {})

                    .get("source")

                ),

            },

            f"Wikipedia lookup completed for {query}.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"Wikipedia lookup failed: {exc}",

        )





# ============================================================

# OPEN LIBRARY

# ============================================================



def book_search(argument: str = ""):
    """
    Search Open Library with an Internet Archive fallback for transient outages.
    """

    tool = "book_search"
    query = str(argument or "").strip()

    if not query:
        return _error(
            tool,
            "Provide a book, author, or subject to search.",
        )

    last_exc = None

    # Open Library remains the primary source. Retry short-lived network
    # failures before falling back to Internet Archive's public search API.
    for attempt in range(2):
        try:
            data = _get_json(
                "https://openlibrary.org/search.json",
                params={
                    "q": query,
                    "limit": 8,
                    "fields": (
                        "key,title,author_name,first_publish_year,"
                        "edition_count,isbn,cover_i"
                    ),
                },
                timeout=12.0,
            )

            books = []
            for item in data.get("docs", [])[:8]:
                books.append({
                    "title": item.get("title"),
                    "authors": item.get("author_name") or [],
                    "first_publish_year": item.get("first_publish_year"),
                    "edition_count": item.get("edition_count"),
                    "isbn": (item.get("isbn") or [])[:3],
                    "cover_id": item.get("cover_i"),
                    "key": item.get("key"),
                })

            return _success(
                tool,
                {
                    "query": query,
                    "total_found": data.get("numFound", 0),
                    "books": books,
                    "source": "openlibrary",
                },
                f"Found {len(books)} book results.",
            )
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(0.75)

    # Internet Archive is a keyless, read-only fallback. Its metadata is not
    # as rich as Open Library, but it keeps simple book/author lookups alive.
    try:
        archive = _get_json(
            "https://archive.org/advancedsearch.php",
            params={
                "q": query,
                "fl[]": ["identifier", "title", "creator", "date"],
                "rows": 8,
                "page": 1,
                "output": "json",
            },
            timeout=12.0,
        )
        docs = (
            ((archive.get("response") or {}).get("docs"))
            if isinstance(archive, dict)
            else []
        ) or []

        books = []
        for item in docs[:8]:
            authors = item.get("creator") or []
            if isinstance(authors, str):
                authors = [authors]
            books.append({
                "title": item.get("title"),
                "authors": authors,
                "first_publish_year": item.get("date"),
                "edition_count": None,
                "isbn": [],
                "cover_id": None,
                "key": item.get("identifier"),
            })

        if books:
            return _success(
                tool,
                {
                    "query": query,
                    "total_found": len(books),
                    "books": books,
                    "source": "archive.org",
                },
                f"Found {len(books)} book results.",
            )

        return _error(
            tool,
            f"No books found for '{query}'.",
            retryable=False,
        )
    except Exception as archive_exc:
        return _error(
            tool,
            f"Book search failed: {last_exc or archive_exc}",
        )


def define_word(argument: str = ""):

    """

    Define an English word.

    """



    tool = "define_word"



    word = str(argument or "").strip()



    if not word:

        return _error(

            tool,

            "Provide a word to define.",

        )



    # Keep only the first word when voice input adds punctuation.

    word = word.split()[0].strip(".,!?;:\"'")



    try:

        data = _get_json(

            "https://api.dictionaryapi.dev/api/v2/entries/en/"

            + quote_plus(word)

        )



        definitions = []



        for entry in data[:3]:

            for meaning in entry.get("meanings", []):

                part_of_speech = meaning.get(

                    "partOfSpeech"

                )



                for definition in meaning.get(

                    "definitions",

                    [],

                )[:3]:



                    definitions.append({

                        "part_of_speech": part_of_speech,

                        "definition": definition.get(

                            "definition"

                        ),

                        "example": definition.get(

                            "example"

                        ),

                        "synonyms": (

                            definition.get("synonyms")

                            or []

                        )[:5],

                    })



        return _success(

            tool,

            {

                "word": word,

                "definitions": definitions,

            },

            f"Definition lookup completed for {word}.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"Dictionary lookup failed: {exc}",

        )





# ============================================================

# arXiv

# ============================================================



def research_arxiv(argument: str = ""):

    """

    Search arXiv research papers.

    """



    tool = "research_arxiv"



    query = str(argument or "").strip()



    if not query:

        return _error(

            tool,

            "Provide a research topic.",

        )



    url = "https://export.arxiv.org/api/query"



    try:

        response = requests.get(

            url,

            params={

                "search_query": f"all:{query}",

                "start": 0,

                "max_results": 6,

            },

            headers={

                "User-Agent": USER_AGENT,

            },

            timeout=15,

        )



        response.raise_for_status()



        root = ET.fromstring(response.text)



        namespace = {

            "atom": "http://www.w3.org/2005/Atom",

        }



        papers = []



        for entry in root.findall(

            "atom:entry",

            namespace,

        )[:6]:



            authors = []



            for author in entry.findall(

                "atom:author",

                namespace,

            ):

                name = author.find(

                    "atom:name",

                    namespace,

                )



                if name is not None and name.text:

                    authors.append(name.text)



            papers.append({

                "title": (

                    entry.findtext(

                        "atom:title",

                        default="",

                        namespaces=namespace,

                    )

                    .strip()

                    .replace("\n", " ")

                ),

                "summary": (

                    entry.findtext(

                        "atom:summary",

                        default="",

                        namespaces=namespace,

                    )

                    .strip()

                    .replace("\n", " ")

                ),

                "authors": authors,

                "published": entry.findtext(

                    "atom:published",

                    default="",

                    namespaces=namespace,

                ),

                "updated": entry.findtext(

                    "atom:updated",

                    default="",

                    namespaces=namespace,

                ),

                "url": (

                    entry.findtext(

                        "atom:id",

                        default="",

                        namespaces=namespace,

                    )

                ),

            })



        return _success(

            tool,

            {

                "query": query,

                "papers": papers,

            },

            f"Found {len(papers)} arXiv papers.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"arXiv search failed: {exc}",

        )





# ============================================================

# CROSSREF

# ============================================================



def research_crossref(argument: str = ""):

    """

    Search Crossref scholarly metadata.

    """



    tool = "research_crossref"



    query = str(argument or "").strip()



    if not query:

        return _error(

            tool,

            "Provide a scholarly search query.",

        )



    try:

        data = _get_json(

            "https://api.crossref.org/works",

            params={

                "query.bibliographic": query,

                "rows": 6,

            },

        )



        results = []



        for item in (

            data.get("message", {})

            .get("items", [])

        )[:6]:



            authors = []



            for author in item.get("author", [])[:8]:

                name_parts = [

                    author.get("given"),

                    author.get("family"),

                ]



                name = " ".join(

                    x for x in name_parts

                    if x

                )



                if name:

                    authors.append(name)



            results.append({

                "title": (

                    item.get("title") or [None]

                )[0],

                "authors": authors,

                "published": (

                    item.get("published-print")

                    or item.get("published-online")

                    or item.get("issued")

                ),

                "journal": (

                    item.get("container-title")

                    or [None]

                )[0],

                "doi": item.get("DOI"),

                "type": item.get("type"),

                "url": item.get("URL"),

            })



        return _success(

            tool,

            {

                "query": query,

                "results": results,

            },

            f"Found {len(results)} scholarly results.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"Crossref search failed: {exc}",

        )





# ============================================================

# NHTSA / VEHICLES

# ============================================================



def vehicle_lookup(argument: str = ""):

    """

    Decode a VIN using NHTSA's public vPIC API.

    """



    tool = "vehicle_lookup"



    vin = (

        str(argument or "")

        .strip()

        .upper()

        .replace(" ", "")

    )



    if not vin:

        return _error(

            tool,

            "Provide a VIN.",

        )



    if len(vin) != 17:

        return _error(

            tool,

            "A VIN should contain 17 characters.",

        )



    try:

        data = _get_json(

            "https://vpic.nhtsa.dot.gov/api/vehicles/"

            f"decodevinvalues/{quote_plus(vin)}",

            params={

                "format": "json",

            },

        )



        results = data.get(

            "Results",

            [],

        )



        decoded = {}



        if results:

            item = results[0]



            useful_fields = [

                "Make",

                "Model",

                "ModelYear",

                "VehicleType",

                "BodyClass",

                "Trim",

                "Series",

                "EngineModel",

                "EngineCylinders",

                "DisplacementL",

                "FuelTypePrimary",

                "DriveType",

                "PlantCountry",

            ]



            for field in useful_fields:

                value = item.get(field)



                if value not in (

                    None,

                    "",

                    "Not Applicable",

                    "null",

                ):

                    decoded[field] = value



        return _success(

            tool,

            {

                "vin": vin,

                "vehicle": decoded,

                "raw_count": len(results),

            },

            "VIN lookup completed.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"Vehicle lookup failed: {exc}",

        )





# ============================================================

# USGS EARTHQUAKES

# ============================================================



def earthquake_search(argument: str = ""):

    """

    Query USGS earthquake feed.



    Examples:

        ""

        "day"

        "week"

        "4.5"

    """



    tool = "earthquake_search"



    raw = str(argument or "").strip().lower()



    if raw in ("", "day", "today"):

        feed = "all_day.geojson"

    elif raw in ("week", "7 days"):

        feed = "all_week.geojson"

    elif raw.replace(".", "", 1).isdigit():

        magnitude = float(raw)



        if magnitude >= 4.5:

            feed = "4.5_week.geojson"

        elif magnitude >= 2.5:

            feed = "2.5_week.geojson"

        else:

            feed = "1.0_week.geojson"

    else:

        feed = "all_day.geojson"



    try:

        data = _get_json(

            "https://earthquake.usgs.gov/earthquakes/"

            f"feed/v1.0/summary/{feed}"

        )



        earthquakes = []



        for feature in data.get(

            "features",

            [],

        )[:20]:



            properties = feature.get(

                "properties",

                {},

            )



            geometry = feature.get(

                "geometry",

                {},

            )



            coordinates = geometry.get(

                "coordinates",

                [],

            )



            earthquakes.append({

                "magnitude": properties.get("mag"),

                "place": properties.get("place"),

                "time": properties.get("time"),

                "url": properties.get("url"),

                "longitude": (

                    coordinates[0]

                    if len(coordinates) > 0

                    else None

                ),

                "latitude": (

                    coordinates[1]

                    if len(coordinates) > 1

                    else None

                ),

                "depth_km": (

                    coordinates[2]

                    if len(coordinates) > 2

                    else None

                ),

            })



        return _success(

            tool,

            {

                "feed": feed,

                "count": len(earthquakes),

                "earthquakes": earthquakes,

            },

            f"Retrieved {len(earthquakes)} earthquake events.",

        )



    except Exception as exc:

        return _error(

            tool,

            f"Earthquake lookup failed: {exc}",

        )





# ============================================================

# PUBLIC API DISCOVERY

# ============================================================



def api_discover(argument: str = ""):

    """

    Search the public-apis catalog for APIs.



    The official catalog API is used first. If that service is

    unavailable, fall back to the public-apis GitHub README.

    """



    tool = "api_discover"

    query = str(argument or "").strip()



    # --------------------------------------------------------

    # PRIMARY: public-apis catalog API

    # --------------------------------------------------------



    try:

        params = {

            "https": "true",

        }



        if query:

            params["description"] = query



        data = _get_json(

            "https://api.publicapis.org/entries",

            params=params,

        )



        entries = []



        for item in data.get(

            "entries",

            [],

        )[:100]:



            auth = item.get("Auth")



            # Only expose APIs that do not require authentication.

            if auth:

                continue



            entries.append({

                "name": item.get("API"),

                "description": item.get(

                    "Description"

                ),

                "url": item.get("Link"),

                "category": item.get(

                    "Category"

                ),

                "https": item.get(

                    "HTTPS"

                ),

                "cors": item.get(

                    "Cors"

                ),

            })



            if len(entries) >= 20:

                break



        return _success(

            tool,

            {

                "query": query,

                "count": len(entries),

                "apis": entries,

                "source": "public-apis catalog API",

            },

            f"Found {len(entries)} no-auth API candidates.",

        )



    except Exception as primary_exc:



        # ----------------------------------------------------

        # FALLBACK: GitHub public-apis README

        # ----------------------------------------------------



        try:

            readme = requests.get(

                "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md",

                headers={

                    "User-Agent": USER_AGENT,

                    "Accept": "text/plain",

                },

                timeout=15,

            )



            readme.raise_for_status()



            entries = []

            current_category = ""



            for raw_line in readme.text.splitlines():



                line = raw_line.strip()



                # Track the category heading.

                if line.startswith("### "):

                    current_category = line[4:].strip()

                    continue



                # Only process Markdown table rows.

                if not line.startswith("|"):

                    continue



                columns = [

                    part.strip()

                    for part in line.strip("|").split("|")

                ]



                # Current public-apis format is:

                # API | Description | Auth | CORS

                if len(columns) < 4:

                    continue



                api_column = columns[0]

                description = columns[1]

                auth = columns[2]

                cors = columns[3]



                # Skip table headers/separators.

                if (

                    api_column.lower() == "api"

                    or set(api_column.replace("-", "")) == set()

                ):

                    continue



                if "description" in api_column.lower():

                    continue



                # Only keep explicitly no-auth entries.

                normalized_auth = (

                    auth

                    .replace("`", "")

                    .strip()

                    .lower()

                )



                if normalized_auth not in {

                    "no",

                    "",

                }:

                    continue



                link_match = re.search(

                    r"\[([^\]]+)\]\((https?://[^)]+)\)",

                    api_column,

                )



                if link_match:

                    name = link_match.group(1).strip()

                    url = link_match.group(2).strip()

                else:

                    name = api_column.strip()

                    url = ""



                searchable = " ".join(

                    (

                        name,

                        description,

                        current_category,

                    )

                ).lower()



                if query and query.lower() not in searchable:

                    continue



                entries.append({

                    "name": name,

                    "description": description,

                    "url": url,

                    "category": current_category,

                    "https": url.lower().startswith("https://"),

                    "cors": cors,

                })



                if len(entries) >= 20:

                    break



            return _success(

                tool,

                {

                    "query": query,

                    "count": len(entries),

                    "apis": entries,

                    "source": "public-apis GitHub README fallback",

                    "primary_error": str(primary_exc),

                },

                f"Found {len(entries)} no-auth API candidates using the GitHub catalog fallback.",

            )



        except Exception as fallback_exc:

            return _error(

                tool,

                "Public API discovery failed: "

                f"catalog error: {primary_exc}; "

                f"GitHub fallback error: {fallback_exc}",

            )







# ============================================================

# EXPANDED FREE PUBLIC API TOOLS

# ============================================================



_STATE_CODES = {

    "alabama": "AL",

    "alaska": "AK",

    "arizona": "AZ",

    "arkansas": "AR",

    "california": "CA",

    "colorado": "CO",

    "connecticut": "CT",

    "delaware": "DE",

    "florida": "FL",

    "georgia": "GA",

    "hawaii": "HI",

    "idaho": "ID",

    "illinois": "IL",

    "indiana": "IN",

    "iowa": "IA",

    "kansas": "KS",

    "kentucky": "KY",

    "louisiana": "LA",

    "maine": "ME",

    "maryland": "MD",

    "massachusetts": "MA",

    "michigan": "MI",

    "minnesota": "MN",

    "mississippi": "MS",

    "missouri": "MO",

    "montana": "MT",

    "nebraska": "NE",

    "nevada": "NV",

    "new hampshire": "NH",

    "new jersey": "NJ",

    "new mexico": "NM",

    "new york": "NY",

    "north carolina": "NC",

    "north dakota": "ND",

    "ohio": "OH",

    "oklahoma": "OK",

    "oregon": "OR",

    "pennsylvania": "PA",

    "rhode island": "RI",

    "south carolina": "SC",

    "south dakota": "SD",

    "tennessee": "TN",

    "texas": "TX",

    "utah": "UT",

    "vermont": "VT",

    "virginia": "VA",

    "washington": "WA",

    "west virginia": "WV",

    "wisconsin": "WI",

    "wyoming": "WY",

}





def _parse_lat_lon(value):

    """Parse 'lat,lon' or 'lat lon' into floats."""

    raw = str(value or "").strip()



    if "," in raw:

        parts = raw.split(",", 1)

    else:

        parts = raw.split()



    if len(parts) != 2:

        return None



    try:

        lat = float(parts[0].strip())

        lon = float(parts[1].strip())

    except (TypeError, ValueError):

        return None



    if not (-90 <= lat <= 90 and -180 <= lon <= 180):

        return None



    return lat, lon





def _open_meteo_geocode(query):

    """Resolve a human location to coordinates."""

    url = (

        "https://geocoding-api.open-meteo.com/v1/search"

        f"?name={quote_plus(str(query).strip())}"

        "&count=5"

        "&language=en"

        "&format=json"

    )



    data = _get_json(url)



    if not isinstance(data, dict):

        raise ValueError("Geocoding API returned an invalid response.")



    results = data.get("results") or []



    if not results:

        raise ValueError(f"No location found for '{query}'.")



    return results





def currency_convert(argument):

    """

    Convert currency using Frankfurter.



    Examples:

      100 USD to EUR

      USD to EUR

      USD EUR 100

    """

    tool = "currency_convert"

    raw = str(argument or "").strip()



    if not raw:

        return ToolResult(

            success=False,

            tool=tool,

            error="Please provide a currency conversion such as '100 USD to EUR'.",

        )



    amount = 1.0

    base = None

    quote = None



    patterns = [

        re.search(

            r"(?i)^\s*(\d+(?:\.\d+)?)\s*([A-Z]{3})\s*(?:to|into|in|->)\s*([A-Z]{3})\s*$",

            raw,

        ),

        re.search(

            r"(?i)^\s*([A-Z]{3})\s+(?:to|into|in|->)\s+([A-Z]{3})\s*$",

            raw,

        ),

        re.search(

            r"(?i)^\s*([A-Z]{3})\s+([A-Z]{3})\s+(\d+(?:\.\d+)?)\s*$",

            raw,

        ),

    ]



    first = patterns[0]

    second = patterns[1]

    third = patterns[2]



    if first:

        amount = float(first.group(1))

        base = first.group(2).upper()

        quote = first.group(3).upper()

    elif second:

        base = second.group(1).upper()

        quote = second.group(2).upper()

    elif third:

        base = third.group(1).upper()

        quote = third.group(2).upper()

        amount = float(third.group(3))

    else:

        return ToolResult(

            success=False,

            tool=tool,

            error=(

                "Invalid currency format. "

                "Example: '100 USD to EUR'."

            ),

        )



    if base == quote:

        rate = 1.0

        date = None

    else:

        url = (

            "https://api.frankfurter.dev/v2/rate/"

            f"{quote_plus(base)}/{quote_plus(quote)}"

        )



        try:

            data = _get_json(url)

        except Exception as exc:

            return ToolResult(

                success=False,

                tool=tool,

                error=str(exc),

                retryable=True,

            )



        if not isinstance(data, dict) or "rate" not in data:

            return ToolResult(

                success=False,

                tool=tool,

                error="Frankfurter returned an invalid exchange-rate response.",

            )



        rate = float(data["rate"])

        date = data.get("date")



    converted = float(

        (Decimal(str(amount)) * Decimal(str(rate))).quantize(

            Decimal("0.000001")

        )

    )



    return ToolResult(

        success=True,

        tool=tool,

        data={

            "amount": amount,

            "base": base,

            "quote": quote,

            "rate": rate,

            "converted": converted,

            "date": date,

        },

    )





def location_lookup(argument):

    """Resolve a city or place into structured location information."""

    tool = "location_lookup"

    query = str(argument or "").strip()



    if not query:

        return ToolResult(

            success=False,

            tool=tool,

            error="Please provide a city, place, or postal code.",

        )



    try:

        results = _open_meteo_geocode(query)

    except Exception as exc:

        return ToolResult(

            success=False,

            tool=tool,

            error=str(exc),

            retryable=True,

        )



    simplified = []



    for item in results:

        simplified.append(

            {

                "name": item.get("name"),

                "country": item.get("country"),

                "country_code": item.get("country_code"),

                "admin1": item.get("admin1"),

                "latitude": item.get("latitude"),

                "longitude": item.get("longitude"),

                "elevation": item.get("elevation"),

                "timezone": item.get("timezone"),

                "population": item.get("population"),

            }

        )



    return ToolResult(

        success=True,

        tool=tool,

        data={

            "query": query,

            "results": simplified,

        },

    )





def air_quality(argument):

    """

    Return current air-quality conditions.



    Accepts:

      Chicago

      Chicago, Illinois

      41.8781,-87.6298

    """

    tool = "air_quality"

    query = str(argument or "").strip()



    if not query:

        return ToolResult(

            success=False,

            tool=tool,

            error="Please provide a city or coordinates.",

        )



    coords = _parse_lat_lon(query)



    try:

        if coords:

            latitude, longitude = coords

            location = {

                "name": "Requested coordinates",

                "country": None,

                "admin1": None,

                "latitude": latitude,

                "longitude": longitude,

            }

        else:

            results = _open_meteo_geocode(query)

            top = results[0]



            latitude = float(top["latitude"])

            longitude = float(top["longitude"])



            location = {

                "name": top.get("name"),

                "country": top.get("country"),

                "admin1": top.get("admin1"),

                "latitude": latitude,

                "longitude": longitude,

            }



        variables = (

            "pm10,pm2_5,carbon_monoxide,"

            "nitrogen_dioxide,sulphur_dioxide,ozone"

        )



        url = (

            "https://air-quality-api.open-meteo.com/v1/air-quality"

            f"?latitude={latitude}"

            f"&longitude={longitude}"

            f"&current={variables}"

            "&timezone=auto"

        )



        data = _get_json(url)



    except Exception as exc:

        return ToolResult(

            success=False,

            tool=tool,

            error=str(exc),

            retryable=True,

        )



    if not isinstance(data, dict):

        return ToolResult(

            success=False,

            tool=tool,

            error="Air-quality API returned an invalid response.",

        )



    return ToolResult(

        success=True,

        tool=tool,

        data={

            "location": location,

            "timezone": data.get("timezone"),

            "current_units": data.get("current_units", {}),

            "current": data.get("current", {}),

            "source": "Open-Meteo Air Quality",

        },

    )





def weather_alerts(argument):

    """

    Get active U.S. weather alerts.



    Accepts:

      IL

      Illinois

      Chicago coordinates: 41.8781,-87.6298

    """

    tool = "weather_alerts"

    raw = str(argument or "").strip()



    if not raw:

        return ToolResult(

            success=False,

            tool=tool,

            error="Please provide a U.S. state or coordinates.",

        )



    coords = _parse_lat_lon(raw)



    if coords:

        latitude, longitude = coords

        url = (

            "https://api.weather.gov/alerts/active"

            f"?point={latitude},{longitude}"

        )

    else:

        state = _STATE_CODES.get(raw.lower())



        if state is None:

            candidate = raw.upper()



            if len(candidate) == 2 and candidate.isalpha():

                state = candidate



        if state is None:

            return ToolResult(

                success=False,

                tool=tool,

                error=(

                    "Please provide a U.S. state name, "

                    "two-letter state code, or coordinates."

                ),

            )



        url = (

            "https://api.weather.gov/alerts/active"

            f"?area={quote_plus(state)}"

        )



    try:

        import requests



        response = requests.get(

            url,

            headers={

                "User-Agent": "JARVIS-local-assistant/1.0",

                "Accept": "application/geo+json, application/json",

            },

            timeout=15,

        )



        response.raise_for_status()

        data = response.json()



    except Exception as exc:

        message = str(exc).lower()



        retryable = any(

            marker in message

            for marker in (

                "timeout",

                "timed out",

                "connection",

                "502",

                "503",

                "504",

                "429",

            )

        )



        return ToolResult(

            success=False,

            tool=tool,

            error=str(exc),

            retryable=retryable,

        )



    features = data.get("features") or []

    alerts = []



    for feature in features[:20]:

        properties = feature.get("properties") or {}



        alerts.append(

            {

                "id": feature.get("id"),

                "event": properties.get("event"),

                "headline": properties.get("headline"),

                "severity": properties.get("severity"),

                "certainty": properties.get("certainty"),

                "urgency": properties.get("urgency"),

                "area_desc": properties.get("areaDesc"),

                "description": properties.get("description"),

                "instruction": properties.get("instruction"),

                "effective": properties.get("effective"),

                "expires": properties.get("expires"),

            }

        )



    return ToolResult(

        success=True,

        tool=tool,

        data={

            "count": len(alerts),

            "alerts": alerts,

            "source": "National Weather Service",

        },

    )





def elevation_lookup(argument):

    """

    Look up elevation for coordinates or a place name.

    """

    tool = "elevation_lookup"

    query = str(argument or "").strip()



    if not query:

        return ToolResult(

            success=False,

            tool=tool,

            error="Please provide a place or coordinates.",

        )



    coords = _parse_lat_lon(query)



    try:

        if coords:

            latitude, longitude = coords

            location = {

                "name": "Requested coordinates",

                "latitude": latitude,

                "longitude": longitude,

            }

        else:

            results = _open_meteo_geocode(query)

            top = results[0]



            latitude = float(top["latitude"])

            longitude = float(top["longitude"])



            location = {

                "name": top.get("name"),

                "country": top.get("country"),

                "admin1": top.get("admin1"),

                "latitude": latitude,

                "longitude": longitude,

            }



        url = (

            "https://api.open-meteo.com/v1/elevation"

            f"?latitude={latitude}"

            f"&longitude={longitude}"

        )



        data = _get_json(url)



    except Exception as exc:

        return ToolResult(

            success=False,

            tool=tool,

            error=str(exc),

            retryable=True,

        )



    if not isinstance(data, dict):

        return ToolResult(

            success=False,

            tool=tool,

            error="Elevation API returned an invalid response.",

        )



    elevations = data.get("elevation") or []



    elevation = elevations[0] if elevations else None



    return ToolResult(

        success=True,

        tool=tool,

        data={

            "location": location,

            "elevation_meters": elevation,

            "elevation_feet": (

                round(float(elevation) * 3.280839895, 2)

                if elevation is not None

                else None

            ),

            "source": "Open-Meteo Elevation",

        },

    )





EXPANDED_API_DISPATCH = {

    "currency_convert": currency_convert,

    "location_lookup": location_lookup,

    "air_quality": air_quality,

    "weather_alerts": weather_alerts,

    "elevation_lookup": elevation_lookup,

}





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





def run_api_tool(

    tool_name: str,

    argument: str = "",

):

    if tool_name in EXPANDED_API_DISPATCH:

        return EXPANDED_API_DISPATCH[tool_name](argument)



    if tool_name == "holiday_lookup":

        return holiday_lookup(argument)



    if tool_name == "knowledge_lookup":

        return knowledge_lookup(argument)



    if tool_name == "book_search":

        return book_search(argument)



    if tool_name == "define_word":

        return define_word(argument)



    if tool_name == "research_arxiv":

        return research_arxiv(argument)



    if tool_name == "research_crossref":

        return research_crossref(argument)



    if tool_name == "vehicle_lookup":

        return vehicle_lookup(argument)



    if tool_name == "earthquake_search":

        return earthquake_search(argument)



    if tool_name == "api_discover":

        return api_discover(argument)



    return _error(

        tool_name,

        f"Unknown API tool: {tool_name}",

    )
