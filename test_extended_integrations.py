import unittest

from extended_api_tools import API_TOOLS, run_extended_api_tool
from gods_eye import GEV_REPO, GEV_URL
from screen_memory import _base_url


class ExtendedIntegrationTests(unittest.TestCase):
    def test_extended_api_registry(self):
        expected = {
            "country_info", "crypto_price", "trivia_question", "joke",
            "meal_search", "tv_search", "music_search", "musicbrainz_search",
            "anime_search", "ghibli_search", "openalex_search", "pubchem_lookup",
            "art_search", "nasa_eonet", "spacex_lookup", "sunrise_sunset",
            "topo_elevation", "public_ip", "reverse_geocode", "news_search",
            "cat_fact", "dog_image", "osm_search",
            "pokemon_lookup", "food_product", "cocktail_search",
            "openverse_search", "iss_location",
        }
        self.assertTrue(expected.issubset(API_TOOLS))
        self.assertTrue(callable(run_extended_api_tool))

    def test_extended_invalid_tool(self):
        result = run_extended_api_tool("definitely_not_a_real_api", "")
        self.assertFalse(result["success"])

    def test_gev_constants(self):
        self.assertTrue(GEV_REPO.startswith("https://github.com/"))
        self.assertEqual(GEV_URL, "http://127.0.0.1:4173")

    def test_screenpipe_default(self):
        self.assertEqual(_base_url(), "http://127.0.0.1:3030")


if __name__ == "__main__":
    unittest.main()
