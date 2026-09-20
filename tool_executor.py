        result.get(
            "message",
            "Browser action completed.",
        )
    )



def _api_spoken_summary(
    tool_name: str,
    result: Any,
) -> Optional[str]:
    """
    Turn structured public-API results into concise JARVIS speech.

    The complete ToolResult remains untouched in task state and execution
    traces. This function only controls what reaches TTS/chat history.
    """

    tool = str(tool_name or "").strip().lower()

    api_tools = {
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

    if tool not in api_tools:
        return None

    raw = result.data if isinstance(result, ToolResult) else result

    if not isinstance(raw, dict):
        return None

    # API results have appeared in several wrapper shapes over time. Peel
    # only small dict envelopes so TTS remains tolerant of dispatcher changes.
    data = raw
    for _ in range(3):
        if data.get("success") is False:
            return None
        nested_data = data.get("data")
        if isinstance(nested_data, dict) and nested_data is not data:
            data = nested_data
            continue
        nested_result = data.get("result")
        if isinstance(nested_result, dict) and nested_result is not data:
            data = nested_result
            continue
        break

    def clean(value: Any, limit: int = 260) -> str:
        value = str(value or "").strip()
        value = " ".join(value.split())

        if len(value) > limit:
            return value[:limit].rstrip() + "..."

        return value

    # --------------------------------------------------------
    # HOLIDAYS
    # --------------------------------------------------------

    if tool == "holiday_lookup":
        country = clean(data.get("country"), 40)
        year = clean(data.get("year"), 10)
        holidays = data.get("holidays", [])

        if not isinstance(holidays, list):
            return None

        count = len(holidays)

        names = []
        seen = set()

        for item in holidays:
            if not isinstance(item, dict):
                continue

            name = clean(item.get("name"), 70)

            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)

            if len(names) >= 5:
                break

        prefix = "I found"

        if country and year:
            prefix += f" {count} holiday entries for {country} in {year}."
        else:
            prefix += f" {count} holiday entries."

        if names:
            spoken_names = names[:2]

            return (
                prefix
                + " Key entries include "
                + " and ".join(spoken_names)
                + "."
            )

        return prefix

    # --------------------------------------------------------
    # KNOWLEDGE
    # --------------------------------------------------------

    if tool == "knowledge_lookup":
        title = clean(data.get("title"), 120)
        summary = clean(data.get("summary"), 1200)

        if title and summary:
            # Speak only the first complete sentence.
            # The complete source summary remains available
            # inside the ToolResult for follow-up questions.
            sentences = re.split(
                r"(?<=[.!?])\s+",
                summary,
            )

            sentence = next(
                (
                    item.strip()
                    for item in sentences
                    if item.strip()
                ),
                summary,
            )

            return f"{title}: {sentence}"

        if summary:
            return summary

        if title:
            return f"I found information about {title}."

        return None

    if tool == "book_search":
        books = data.get("books", [])

        if not isinstance(books, list):
            return None

        titles = []

        for item in books:
            if not isinstance(item, dict):
                continue

            title = clean(item.get("title"), 120)

            if title and title not in titles:
                titles.append(title)

            if len(titles) >= 4:
                break

        count = (
            data.get("total_found")
            if isinstance(data.get("total_found"), int)
            else len(books)
        )

        returned_count = len(books)

        if titles:
            spoken_titles = titles[:2]

            return (
                f"I found {returned_count} book results, "
                f"including {' and '.join(spoken_titles)}."
            )

        return f"I found {returned_count} book results."

    # --------------------------------------------------------
    # DICTIONARY
    # --------------------------------------------------------

    if tool == "define_word":
        word = clean(
            data.get("word")
            or data.get("query"),
            80,
        )

        definitions = []

        meanings = data.get("meanings", [])

        if isinstance(meanings, list):
            for meaning in meanings:
                if not isinstance(meaning, dict):
                    continue

                meaning_defs = meaning.get("definitions", [])

                if not isinstance(meaning_defs, list):
                    continue

                for item in meaning_defs:
                    if not isinstance(item, dict):
                        continue

                    definition = clean(
                        item.get("definition"),
                        280,
                    )

                    if definition:
                        definitions.append(definition)

                    if definitions:
                        break

                if definitions:
                    break

        if word and definitions:
            return f"{word} means {definitions[0]}"

        if definitions:
            return definitions[0]

        return None

    # --------------------------------------------------------
    # ARXIV
    # --------------------------------------------------------

    if tool == "research_arxiv":
        papers = data.get("papers", [])

        if not isinstance(papers, list):
            return None

        titles = []

        for item in papers:
            if not isinstance(item, dict):
                continue

            title = clean(item.get("title"), 140)

            if title:
                titles.append(title)

            if len(titles) >= 3:
                break

        if titles:
            return (
                f"I found {len(papers)} arXiv papers. "
                f"The first result is {titles[0]}."
            )

        return f"I found {len(papers)} arXiv papers."

    # --------------------------------------------------------
    # CROSSREF
    # --------------------------------------------------------

    if tool == "research_crossref":
        results = data.get("results", [])

        if not isinstance(results, list):
            return None

        titles = []

        for item in results:
            if not isinstance(item, dict):
                continue

            title = clean(item.get("title"), 140)

            if title:
                titles.append(title)

            if len(titles) >= 3:
                break

        if titles:
            return (
                f"I found {len(results)} scholarly results. "
                f"The first result is {titles[0]}."
            )

        return f"I found {len(results)} scholarly results."

    # --------------------------------------------------------
    # VEHICLE / VIN
    # --------------------------------------------------------

    if tool == "vehicle_lookup":
        vin = clean(data.get("vin"), 30)
        vehicle = data.get("vehicle", {})

        if not isinstance(vehicle, dict):
            return None

        make = clean(vehicle.get("Make"), 60)
        model = clean(vehicle.get("Model"), 80)
        year = clean(vehicle.get("ModelYear"), 10)
        trim = clean(vehicle.get("Trim"), 80)

        vehicle_name = " ".join(
            value
            for value in (year, make, model)
            if value
        ).strip()

        if vehicle_name:
            if trim:
                vehicle_name += f", {trim}"

            if vin:
                return f"VIN {vin} decodes to a {vehicle_name}."

            return f"The vehicle is a {vehicle_name}."

        return None

    # --------------------------------------------------------
    # EARTHQUAKES
    # --------------------------------------------------------

    if tool == "earthquake_search":
        earthquakes = data.get("earthquakes", [])

        if not isinstance(earthquakes, list):
            return None

        if not earthquakes:
            return "No earthquake events were found."

        strongest = None
        strongest_magnitude = None

        for item in earthquakes:
            if not isinstance(item, dict):
                continue

            magnitude = item.get("magnitude")

            try:
                numeric_magnitude = float(magnitude)
            except (TypeError, ValueError):
                continue

            if (
                strongest_magnitude is None
                or numeric_magnitude > strongest_magnitude
            ):
                strongest_magnitude = numeric_magnitude
                strongest = item

        if strongest is not None:
            place = clean(
                strongest.get("place"),
                140,
            )

            if place:
                return (
                    f"I found {len(earthquakes)} earthquake events. "
                    f"The largest listed was magnitude "
                    f"{strongest_magnitude:g} near {place}."
                )

            return (
                f"I found {len(earthquakes)} earthquake events. "
                f"The largest listed was magnitude "
                f"{strongest_magnitude:g}."
            )

        return f"I found {len(earthquakes)} earthquake events."

    # --------------------------------------------------------
    # --------------------------------------------------------
    # CURRENCY
    # --------------------------------------------------------

    if tool == "currency_convert":
        amount = data.get("amount")
        base = clean(
            data.get("base")
            or data.get("from")
            or data.get("from_currency"),
            10,
        )
        quote = clean(
            data.get("quote")
            or data.get("to")
            or data.get("to_currency"),
            10,
        )
        converted = data.get("converted")
        if converted is None and amount is not None and data.get("rate") is not None:
            try:
                converted = float(amount) * float(data.get("rate"))
            except (TypeError, ValueError):
                converted = None
        rate = data.get("rate")

        if amount is None or not base or not quote:
            return None

        try:
            amount_text = f"{float(amount):g}"
        except (TypeError, ValueError):
            amount_text = clean(amount, 30)

        try:
            converted_text = f"{float(converted):.2f}"
        except (TypeError, ValueError):
            converted_text = clean(converted, 30)

        if rate is not None:
            try:
                rate_text = f"{float(rate):.5f}"
            except (TypeError, ValueError):
                rate_text = clean(rate, 30)

            return (
                f"{amount_text} {base} is "
                f"{converted_text} {quote}. "
                f"The exchange rate is {rate_text}."
            )

        return (
            f"{amount_text} {base} is "
            f"{converted_text} {quote}."
        )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    if tool == "location_lookup":
        results = data.get("results", [])