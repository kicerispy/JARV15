import json
from pathlib import Path


def test_spotify_workflow_template_is_wired():
    path = Path(__file__).parents[1] / "n8n" / "workflows" / "jarvis-gateway-spotify.json"
    workflow = json.loads(path.read_text(encoding="utf-8"))

    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert nodes["JARVIS Gateway Webhook"]["parameters"]["path"] == "jarvis-gateway"
    assert nodes["JARVIS Gateway Webhook"]["parameters"]["responseMode"] == "responseNode"
    assert nodes["Spotify Liked Songs?"]["type"] == "n8n-nodes-base.if"
    assert nodes["JARVIS Spotify Action"]["parameters"]["url"] == "http://127.0.0.1:8765/v1/jarvis/action"
    assert "spotify_play_liked_songs" in nodes["JARVIS Spotify Action"]["parameters"]["jsonBody"]
    assert nodes["Return Spotify Result"]["type"] == "n8n-nodes-base.respondToWebhook"
