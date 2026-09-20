"""
JARVIS task planner - converts user requests into tool calls.
"""
import ast
import json
import re
from typing import Any, Dict, List, Optional

import config
from model_manager import ModelManager
from logger import logger

MODEL_MANAGER = ModelManager()
PLANNER_MODEL = MODEL_MANAGER.planner_model

# ==========================================================
# Available Tools
# ==========================================================

AVAILABLE_TOOLS: Dict[str, str] = {
    "browser_connect": "Connect to the JARVIS-controlled Chrome browser.",
    "browser_search_google": "Search Google using the controlled browser.",
    "browser_search_bing": "Search Bing using the controlled browser.",
    "browser_click_first_bing_result": "Click the first Bing search result in the controlled browser.",
    "browser_goto": "Navigate the controlled browser to a URL.",
    "browser_page_info": "Read the current browser page title and URL.",
    "holiday_lookup": "Look up public holidays. Argument = ISO country code and optional year, e.g. US 2026.",
    "knowledge_lookup": "Look up a concise Wikipedia knowledge summary. Argument = topic.",
    "book_search": "Search Open Library for books or authors. Argument = title, author, or subject.",
    "define_word": "Define an English word using a public dictionary. Argument = word.",
    "research_arxiv": "Search arXiv research papers. Argument = research topic.",
    "research_crossref": "Search Crossref scholarly metadata. Argument = scholarly query.",
    "vehicle_lookup": "Decode a vehicle VIN using NHTSA. Argument = 17-character VIN.",
    "earthquake_search": "Get USGS earthquake information. Argument = day, week, or magnitude such as 4.5.",
    "api_discover": "Discover free no-auth public APIs. Argument = category or topic.",
"currency_convert": "Convert currencies using current exchange rates. Argument = 100 USD to EUR, or USD to EUR.",
"location_lookup": "Resolve a city or place to coordinates, timezone, country, and elevation. Argument = city or place.",
"air_quality": "Get current air-quality conditions including PM2.5, PM10, ozone, and other pollutants. Argument = city or coordinates.",
"weather_alerts": "Get active U.S. National Weather Service alerts. Argument = U.S. state, state code, or coordinates.",
"elevation_lookup": "Look up elevation for a place or coordinates. Argument = city or lat,lon.",
    "country_info": "Get World Bank country metadata such as capital, region, income level, and coordinates. Argument = country name or two-letter code.",
    "crypto_price": "Get current cryptocurrency market data without an API key. Argument = coin name or symbol.",
    "trivia_question": "Generate one free trivia question. Argument = optional category hint.",
    "joke": "Get a safe random joke from JokeAPI. Argument = optional category hint.",
    "meal_search": "Find a recipe or random meal using TheMealDB. Argument = meal or ingredient search, or empty for a random meal.",
    "tv_search": "Search TV shows with TVMaze. Argument = show name.",
    "music_search": "Search songs, artists, and albums with the iTunes Search API. Argument = song, artist, or album.",
    "musicbrainz_search": "Search MusicBrainz recording metadata. Argument = song, recording, or artist.",
    "anime_search": "Search anime using Jikan/MyAnimeList data. Argument = anime title.",
    "anime_episodes": "Find an anime and return its episodes using AniAPI, Kitsu, and Jikan fallbacks. Argument = anime title or JSON with anime/title and optional page.",
    "ghibli_search": "Search Studio Ghibli films. Argument = title, director, or empty.",
    "openalex_search": "Search scholarly works using OpenAlex. Argument = research topic.",
    "pubchem_lookup": "Look up chemical compound information from PubChem. Argument = compound name.",
    "art_search": "Search Art Institute of Chicago artworks. Argument = artist, title, or subject.",
    "nasa_eonet": "Query active NASA Earth Observatory Natural Event Tracker events. Argument = event category or empty.",
    "spacex_lookup": "Look up historical SpaceX launch records from the public community API. Argument = latest or historical.",
    "sunrise_sunset": "Get sunrise, sunset, solar noon, and twilight for a place. Argument = city or lat,lon.",
    "topo_elevation": "Get topographic elevation from OpenTopoData. Argument = place or lat,lon.",
    "public_ip": "Get the computer's current public IP address. Argument = empty.",
    "reverse_geocode": "Reverse geocode latitude,longitude with OpenStreetMap Nominatim. Argument = lat,lon.",
    "news_search": "Search recent news via the GDELT DOC 2.0 API. Argument = news topic.",
    "cat_fact": "Get a random cat fact. Argument = empty.",
    "dog_image": "Get a random dog image URL. Argument = optional breed hint.",
    "osm_search": "Search OpenStreetMap/Nominatim for a place, address, landmark, or map feature. Argument = search phrase.",
    "pokemon_lookup": "Look up Pokémon data including types, abilities, stats, and image. Argument = name or number.",
    "food_product": "Look up food product nutrition and ingredients from Open Food Facts. Argument = barcode.",
    "cocktail_search": "Find a cocktail recipe using TheCocktailDB. Argument = cocktail name, or empty for a random cocktail.",
    "openverse_search": "Search openly licensed images with Openverse. Argument = image search phrase.",
    "iss_location": "Get the International Space Station's current latitude and longitude. Argument = empty.",
    "gods_eye_status": "Report God's Eye View installation and local server status. Argument = empty.",
    "gods_eye_setup": "Install or update God's Eye View in the JARVIS external-tools directory and run its setup doctor. Argument = empty.",
    "gods_eye_start": "Start God's Eye View locally and open it in the browser. Argument = empty.",
    "gods_eye_open": "Open the local God's Eye View console in the browser. Argument = empty.",
    "gods_eye_stop": "Stop the JARVIS-managed God's Eye View process. Argument = empty.",
    "gods_eye_contacts": "Read live aircraft contacts from God's Eye View's local OpenSky bridge. Argument = empty.",
    "gods_eye_vessels": "Read live vessel contacts from God's Eye View's AIS bridge. Argument = empty.",
    "gods_eye_satellites": "Read satellite TLE records exposed by God's Eye View/CelesTrak. Argument = stations, active, or starlink.",
    "gods_eye_launches": "Read the local God's Eye View launch feed. Argument = empty.",
    "gods_eye_cameras": "Read the public camera source catalog from God's Eye View. Argument = empty.",
    "gods_eye_radio": "Read the Radio Browser station catalog from God's Eye View. Argument = empty.",
    "gods_eye_transit": "Read registered public transit feeds from God's Eye View. Argument = empty.",
    "screen_memory_status": "Check the optional local Screenpipe memory bridge. Argument = empty.",
    "screen_memory_search": "Search Screenpipe's local screen/audio/UI memory. Argument = query text or JSON filters.",
    "screen_memory_recent": "Read recent Screenpipe memory from the local machine. Argument = optional time window such as '1h ago'.",
    "browser_page_snapshot": "Read a bounded structured snapshot of the current browser page: title, URL, headings, results, buttons, inputs, links, and cleaned readable text.",
    "browser_click_result": "Click a numbered or last organic Google/YouTube result. Argument is JSON.",
    "browser_back": "Navigate the controlled browser back one page.",
    "browser_find_element": "Find a browser DOM element by CSS selector, visible text, or ARIA role with optional accessible name.",
    "browser_click_element": "Click a browser DOM element by CSS selector, visible text, or ARIA role with optional accessible name.",
    "browser_fill_element": "Fill a browser input by CSS selector, visible text, or ARIA role with optional accessible name. Argument is JSON.",