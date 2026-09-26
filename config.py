import os
from pathlib import Path


# ============================================================
# BASE PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent


# ============================================================
# JARVIS MODEL CONFIGURATION
# ============================================================

CHAT_MODEL = os.environ.get(
    "JARVIS_CHAT_MODEL",
    "qwen3.5:9b",
)

PLANNER_MODEL = os.environ.get(
    "JARVIS_PLANNER_MODEL",
    "qwen3.5:9b",
)

# Bounded software-change planning does not need the larger coding model.
# Keep it configurable so advanced users can opt back into the coding model.
CHANGE_PLANNER_MODEL = os.environ.get(
    "JARVIS_CHANGE_PLANNER_MODEL",
    PLANNER_MODEL,
)

CODING_MODEL = os.environ.get(
    "JARVIS_CODING_MODEL",
    "qwen2.5-coder:14b",
)

CODING_FALLBACK_MODEL = os.environ.get(
    "JARVIS_CODING_FALLBACK_MODEL",
    "gemma4:26b",
)

VISION_MODEL = os.environ.get(
    "JARVIS_VISION_MODEL",
    "qwen2.5vl:3b",
)

VERIFY_MODEL = os.environ.get(
    "JARVIS_VERIFY_MODEL",
    "gemma4:e2b",
)


# ============================================================
# WHISPER
# ============================================================

# "base" was producing poor short-command transcriptions.
#
# small.en is a better next step while keeping transcription
# reasonably fast on your CUDA setup.
WHISPER_MODEL = os.environ.get(
    "JARVIS_WHISPER_MODEL",
    "small.en",
)

WHISPER_DEVICE = os.environ.get(
    "JARVIS_WHISPER_DEVICE",
    "cpu",
)

WHISPER_COMPUTE_TYPE = os.environ.get(
    "JARVIS_WHISPER_COMPUTE_TYPE",
    "int8",
)


# ============================================================
# OLLAMA
# ============================================================

OLLAMA_HOST = os.environ.get(
    "OLLAMA_HOST",
    "http://127.0.0.1:11434",
)

# Keep model transport recovery small and deterministic. The first failed
# attempt should not make JARVIS feel sluggish, while a second attempt catches
# transient Ollama/HTTP failures without creating long retry loops.
OLLAMA_GENERATION_MAX_ATTEMPTS = int(
    os.environ.get(
        "JARVIS_OLLAMA_GENERATION_MAX_ATTEMPTS",
        "2",
    )
)

OLLAMA_GENERATION_RETRY_DELAY = float(
    os.environ.get(
        "JARVIS_OLLAMA_GENERATION_RETRY_DELAY",
        "0.35",
    )
)


# ============================================================
# ROBLOX MCP
# ============================================================

ROBLOX_MCP_URL = os.environ.get(
    "JARVIS_ROBLOX_MCP_URL",
    "http://127.0.0.1:58741",
).rstrip("/")

ROBLOX_MCP_DISCOVERY_TTL = float(
    os.environ.get(
        "JARVIS_ROBLOX_MCP_DISCOVERY_TTL",
        "60",
    )
)

ROBLOX_MCP_TIMEOUT = float(
    os.environ.get(
        "JARVIS_ROBLOX_MCP_TIMEOUT",
        "60",
    )
)

# ============================================================
# UNREAL ENGINE MCP
# ============================================================

UNREAL_MCP_URL = os.environ.get(
    "JARVIS_UNREAL_MCP_URL",
    "http://127.0.0.1:3000/mcp",
).rstrip("/")

UNREAL_MCP_PROJECT_PATH = os.environ.get(
    "JARVIS_UNREAL_MCP_PROJECT_PATH",
    "",
).strip()

UNREAL_MCP_TOKEN = os.environ.get(
    "JARVIS_UNREAL_MCP_TOKEN",
    "",
).strip()

UNREAL_MCP_TOKEN_FILE = os.environ.get(
    "JARVIS_UNREAL_MCP_TOKEN_FILE",
    "",
).strip()

UNREAL_MCP_TIMEOUT_SECONDS = float(
    os.environ.get(
        "JARVIS_UNREAL_MCP_TIMEOUT",
        "120",
    )
)

UNREAL_MCP_EXTERNAL_DIR = os.environ.get(
    "JARVIS_UNREAL_MCP_EXTERNAL_DIR",
    str(BASE_DIR / ".jarvis_external" / "Unreal_mcp"),
).strip()

# ============================================================
# SELF-HEALING / RESILIENCE / LEARNED AUTONOMY
# ============================================================

SELF_HEALING_ENABLED = os.environ.get(
    "JARVIS_SELF_HEALING_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

SELF_HEALING_MAX_ATTEMPTS = int(
    os.environ.get("JARVIS_SELF_HEALING_MAX_ATTEMPTS", "2")
)

TOOL_RESILIENCE_ENABLED = os.environ.get(
    "JARVIS_TOOL_RESILIENCE_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

TOOL_CIRCUIT_BREAKER_ENABLED = os.environ.get(
    "JARVIS_TOOL_CIRCUIT_BREAKER_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

TOOL_CIRCUIT_FAILURE_THRESHOLD = int(
    os.environ.get("JARVIS_TOOL_CIRCUIT_FAILURE_THRESHOLD", "4")
)

TOOL_CIRCUIT_COOLDOWN_SECONDS = float(
    os.environ.get("JARVIS_TOOL_CIRCUIT_COOLDOWN_SECONDS", "20")
)

AUTONOMY_LEARNED_STRATEGY_ENABLED = os.environ.get(
    "JARVIS_AUTONOMY_LEARNED_STRATEGY_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

AUTONOMY_AUTO_VERIFICATION_ENABLED = os.environ.get(
    "JARVIS_AUTONOMY_AUTO_VERIFICATION_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

AUTONOMY_STRATEGY_QUARANTINE_SECONDS = float(
    os.environ.get("JARVIS_AUTONOMY_STRATEGY_QUARANTINE_SECONDS", "3600")
)

AUTONOMY_STRATEGY_MIN_SUCCESSES = int(
    os.environ.get("JARVIS_AUTONOMY_STRATEGY_MIN_SUCCESSES", "3")
)

AUTONOMY_STRATEGY_MIN_SUCCESS_RATE = float(
    os.environ.get("JARVIS_AUTONOMY_STRATEGY_MIN_SUCCESS_RATE", "0.75")
)

SELF_HEALING_FAILURE_MEMORY_ENABLED = os.environ.get(
    "JARVIS_SELF_HEALING_FAILURE_MEMORY_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

SELF_HEALING_RETRY_BACKOFF_BASE_SECONDS = float(
    os.environ.get("JARVIS_SELF_HEALING_RETRY_BACKOFF_BASE_SECONDS", "0.25")
)

SELF_HEALING_RETRY_BACKOFF_MAX_SECONDS = float(
    os.environ.get("JARVIS_SELF_HEALING_RETRY_BACKOFF_MAX_SECONDS", "4.0")
)

# ============================================================
# EXTERNAL CONTEXT / MEMORY
# ============================================================

CONTEXT_MEMORY_BACKEND = os.environ.get(
    "JARVIS_CONTEXT_MEMORY_BACKEND",
    "auto",
).strip().lower()

AGENT_MEMORY_URL = os.environ.get(
    "JARVIS_AGENTMEMORY_URL",
    "http://127.0.0.1:3111",
).strip().rstrip("/")

AGENT_MEMORY_SECRET = os.environ.get(
    "JARVIS_AGENTMEMORY_SECRET",
    "",
).strip()

OPENVIKING_URL = os.environ.get(
    "JARVIS_OPENVIKING_URL",
    "http://127.0.0.1:1933",
).strip().rstrip("/")

OPENVIKING_API_KEY = os.environ.get(
    "JARVIS_OPENVIKING_API_KEY",
    "",
).strip()

OPENVIKING_ACCOUNT = os.environ.get(
    "JARVIS_OPENVIKING_ACCOUNT",
    "",
).strip()

OPENVIKING_USER = os.environ.get(
    "JARVIS_OPENVIKING_USER",
    "",
).strip()

# Optional Hindsight long-term memory. Disabled by default so existing
# local/OpenViking/agentmemory behavior is unchanged until explicitly enabled.
HINDSIGHT_URL = os.environ.get(
    "JARVIS_HINDSIGHT_URL",
    "http://127.0.0.1:8888",
).strip().rstrip("/")

HINDSIGHT_BANK_ID = os.environ.get(
    "JARVIS_HINDSIGHT_BANK_ID",
    "jarvis",
).strip() or "jarvis"

HINDSIGHT_API_KEY = os.environ.get(
    "JARVIS_HINDSIGHT_API_KEY",
    "",
).strip()

HINDSIGHT_TIMEOUT = max(
    0.5,
    float(os.environ.get("JARVIS_HINDSIGHT_TIMEOUT", "8")),
)

ADAPTIVE_MEMORY_ENABLED = os.environ.get(
    "JARVIS_ADAPTIVE_MEMORY_ENABLED",
    "0",
).strip().lower() not in {"0", "false", "no", "off"}

JARVIS_RESPONSE_STYLE = os.environ.get(
    "JARVIS_RESPONSE_STYLE",
    "action_first",
).strip().lower()

AGENT_SKILLS_DIR = os.environ.get(
    "JARVIS_AGENT_SKILLS_DIR",
    str(BASE_DIR / ".jarvis_external" / "agent_skill_sources"),
).strip()

AGENT_SKILL_SOURCES_FILE = os.environ.get(
    "JARVIS_AGENT_SKILL_SOURCES_FILE",
    str(BASE_DIR / "skills_sources.json"),
).strip()

AGENT_SKILL_SYNC_DEPTH = max(
    1,
    int(os.environ.get("JARVIS_AGENT_SKILL_SYNC_DEPTH", "1")),
)


# ============================================================
# SUPERPOWERS SOFTWARE WORKFLOW
# ============================================================

SUPERPOWERS_ENABLED = os.environ.get(
    "JARVIS_SUPERPOWERS_ENABLED",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

SUPERPOWERS_VERSION = "6.4.1"

# ============================================================
# TEXT INPUT
# ============================================================

TYPED_INPUT_ENABLED = os.environ.get(
    "JARVIS_TYPED_INPUT",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}


# ============================================================
# JARVIS IDENTITY
# ============================================================

JARVIS_NAME = "JARVIS"

JARVIS_PERSONALITY = """
You are JARVIS, a highly capable personal AI assistant.

Your primary role is to assist the user, understand their
intent, coordinate tasks, operate tools, and communicate
clearly.

You are not merely a coding assistant.

Programming, computer control, web research, vision,
automation, file management, and other capabilities are
tools that you can use when appropriate.

Remain JARVIS regardless of which capability you are using.

When a specialist model is needed, delegate the task to it.
The specialist performs the technical work and returns the
result to you.

You remain responsible for the final response to the user.

Your communication should be:
- intelligent
- concise
- calm
- confident
- helpful
- natural
- slightly futuristic when appropriate

Do not unnecessarily explain your internal architecture,
models, prompts, routing, or tools to the user.

Do not behave like a generic software-engineering chatbot
unless the user specifically asks for detailed technical
assistance.

You are the orchestrator.
Your tools are capabilities.
The user interacts with JARVIS.
"""


# ============================================================
# FILE PATHS
# ============================================================

DATABASE_PATH = BASE_DIR / "jarvis_memory.db"

CONVERSATION_HISTORY_PATH = (
    BASE_DIR / "conversation_history.json"
)

PROFILE_PATH = BASE_DIR / "profile.json"

SCREENSHOT_PATH = BASE_DIR / "jarvis_screen.png"

TASK_STATE_PATH = BASE_DIR / "task_state.json"

TASK_MEMORY_PATH = BASE_DIR / "task_memory.json"

MAX_TASK_MEMORY = 20


# ============================================================
# MEMORY / CONVERSATION
# ============================================================

MAX_HISTORY_MESSAGES = 12

MAX_MEMORIES_IN_PROMPT = 30

MAX_HISTORY_FILE_SIZE = 5 * 1024 * 1024


# ============================================================
# AUDIO
# ============================================================

SAMPLE_RATE = 16000

CHUNK_SIZE = 1024

# Explicitly use the microphone we have already verified.
MIC_DEVICE = int(
    os.environ.get(
        "JARVIS_MIC_DEVICE",
        "1",
    )
)

# voice.py currently manages the output device itself.
OUTPUT_DEVICE = int(
    os.environ.get(
        "JARVIS_OUTPUT_DEVICE",
        "5",
    )
)


# ============================================================
# WAKE WORD
# ============================================================

WAKE_MODEL_PATH = BASE_DIR / "models"

WAKE_METADATA_PATH = BASE_DIR / "models"

WAKE_CHUNK_SIZE = 1280


# ============================================================
# TTS
# ============================================================

# Keep the active Piper voice configurable without changing the working
# local voice path. Environment variables allow fast tuning without code edits.
VOICE_MODEL_PATH = Path(
    os.path.expanduser(
        os.environ.get(
            "JARVIS_TTS_VOICE_MODEL",
            "~/.heed/voices/en_GB-alan-medium.onnx",
        )
    )
)

TTS_LENGTH_SCALE = float(
    os.environ.get(
        "JARVIS_TTS_LENGTH_SCALE",
        "0.85",
    )
)

TTS_NOISE_SCALE = float(
    os.environ.get(
        "JARVIS_TTS_NOISE_SCALE",
        "0.45",
    )
)

TTS_NOISE_W = float(
    os.environ.get(
        "JARVIS_TTS_NOISE_W",
        "0.60",
    )
)

PITCH_RATIO = float(
    os.environ.get(
        "JARVIS_TTS_PITCH_RATIO",
        "0.94",
    )
)

LOW_SHELF_GAIN_DB = float(
    os.environ.get(
        "JARVIS_TTS_LOW_SHELF_GAIN_DB",
        "3.0",
    )
)

PRESENCE_GAIN_DB = float(
    os.environ.get(
        "JARVIS_TTS_PRESENCE_GAIN_DB",
        "-1.5",
    )
)

HIGH_GAIN_DB = float(
    os.environ.get(
        "JARVIS_TTS_HIGH_GAIN_DB",
        "-1.5",
    )
)

OUTPUT_GAIN = float(
    os.environ.get(
        "JARVIS_TTS_OUTPUT_GAIN",
        "0.30",
    )
)


# ============================================================
# VOICE / RECOGNITION
# ============================================================

MIN_CONFIDENCE = 0.5


# ============================================================
# MOUSE CALIBRATION
# ============================================================

MOUSE_OFFSET_X = 0

MOUSE_OFFSET_Y = 0

CLICK_BIAS_X = 0

CLICK_BIAS_Y = 0


# ============================================================
# WEATHER
# ============================================================

DEFAULT_WEATHER_LOCATION = os.environ.get(
    "JARVIS_DEFAULT_WEATHER_LOCATION",
    "Belvidere, IL",
).strip()

WEATHER_GEOCODING_URL = (
    "https://geocoding-api.open-meteo.com/v1/search"
)

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
)


# ============================================================
# TIMEOUTS
# ============================================================

START_TIMEOUT = 10

CONTINUOUS_START_TIMEOUT = 10

MAX_RECORDING_SECONDS = 30


# ============================================================
# VOICE ACTIVITY / SILENCE
# ============================================================

# Keep the threshold we've already tested successfully.
SILENCE_THRESHOLD = 200

# Give Whisper a full second of silence to finish the phrase.
SILENCE_DURATION = 1.0

# Preserve the first half-second of speech.
PREBUFFER_SECONDS = 0.5

BARGE_IN_MINIMUM_CAPTURE = 0.25

BARGE_IN_SILENCE_DURATION = 0.8

INTERRUPT_THRESHOLD = 0.02

INTERRUPT_CHUNKS = 3

INTERRUPT_GRACE_SECONDS = 0.5


# ============================================================
# GENERATION SETTINGS
# ============================================================

TEMPERATURE = float(
    os.environ.get(
        "JARVIS_TEMPERATURE",
        "0.7",
    )
)

CODING_TEMPERATURE = float(
    os.environ.get(
        "JARVIS_CODING_TEMPERATURE",
        "0.3",
    )
)

CODING_NUM_CTX = int(
    os.environ.get(
        "JARVIS_CODING_NUM_CTX",
        "8192",
    )
)

CHAT_THINK = os.environ.get(
    "JARVIS_CHAT_THINK",
    "false",
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}

CHAT_NUM_GPU = int(
    os.environ.get(
        "JARVIS_CHAT_NUM_GPU",
        "40",
    )
)

CHAT_NUM_PREDICT = int(
    os.environ.get(
        "JARVIS_CHAT_NUM_PREDICT",
        "220",
    )
)

PLANNER_NUM_PREDICT = int(
    os.environ.get(
        "JARVIS_PLANNER_NUM_PREDICT",
        "512",
    )
)

CHANGE_PLANNER_NUM_PREDICT = int(
    os.environ.get(
        "JARVIS_CHANGE_PLANNER_NUM_PREDICT",
        "512",
    )
)

# Product research synthesis can require a substantially larger structured
# JSON response than normal task planning. Keep it separate so ordinary
# planner responses remain fast.
PRODUCT_RESEARCH_NUM_PREDICT = int(
    os.environ.get(
        "JARVIS_PRODUCT_RESEARCH_NUM_PREDICT",
        "900",
    )
)

PLANNER_MODEL_KEEP_ALIVE = os.environ.get(
    "JARVIS_PLANNER_MODEL_KEEP_ALIVE",
    "10m",
).strip() or "10m"

# Preload the coding model in a background thread after startup so the first
# autonomous repair does not pay the full Ollama model-load penalty.
PRELOAD_CODING_MODEL = os.environ.get(
    "JARVIS_PRELOAD_CODING_MODEL",
    "1",
).strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

CODING_MODEL_KEEP_ALIVE = os.environ.get(
    "JARVIS_CODING_MODEL_KEEP_ALIVE",
    "15m",
).strip() or "15m"


# Delay the optional coding-model warm-up until the runtime has settled.
# This keeps JARVIS responsive during startup while still warming the model
# shortly after the assistant becomes idle.
CODING_MODEL_WARMUP_DELAY_SECONDS = float(
    os.environ.get(
        "JARVIS_CODING_MODEL_WARMUP_DELAY_SECONDS",
        "15",
    )
)


# ============================================================
# DEBUG
# ============================================================

DEBUG = os.environ.get(
    "JARVIS_DEBUG",
    "false",
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# ============================================================
# N8N MCP CLIENT
# ============================================================
#
# Optional direct n8n instance-level MCP. It remains fail-closed unless
# explicitly enabled or a token is already configured.

N8N_MCP_URL = os.environ.get(
    "JARVIS_N8N_MCP_URL",
    "http://127.0.0.1:5678/mcp-server/http",
).strip().rstrip("/")

N8N_MCP_TOKEN = os.environ.get(
    "JARVIS_N8N_MCP_TOKEN",
    "",
).strip()

N8N_MCP_TOKEN_FILE = os.environ.get(
    "JARVIS_N8N_MCP_TOKEN_FILE",
    str(BASE_DIR / ".jarvis_runtime" / "n8n_mcp_token"),
).strip()

_mcp_enabled_env = os.environ.get("JARVIS_N8N_MCP_ENABLED")
if _mcp_enabled_env is None:
    _mcp_token_file_exists = Path(
        os.path.expandvars(os.path.expanduser(N8N_MCP_TOKEN_FILE))
    ).is_file()
    N8N_MCP_ENABLED = bool(
        N8N_MCP_TOKEN
        or _mcp_token_file_exists
    )
else:
    N8N_MCP_ENABLED = _mcp_enabled_env.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

N8N_MCP_TIMEOUT_SECONDS = float(
    os.environ.get(
        "JARVIS_N8N_MCP_TIMEOUT_SECONDS",
        "20",
    )
)

N8N_MCP_DISCOVERY_TTL_SECONDS = float(
    os.environ.get(
        "JARVIS_N8N_MCP_DISCOVERY_TTL_SECONDS",
        "30",
    )
)

N8N_MCP_MAX_RESPONSE_BYTES = int(
    os.environ.get(
        "JARVIS_N8N_MCP_MAX_RESPONSE_BYTES",
        str(2 * 1024 * 1024),
    )
)

N8N_MCP_EXECUTION_TIMEOUT_SECONDS = float(
    os.environ.get(
        "JARVIS_N8N_MCP_EXECUTION_TIMEOUT_SECONDS",
        "60",
    )
)

# ============================================================
# N8N WORKFLOW ORCHESTRATION
# ============================================================
#
# n8n is optional. When enabled, workflow-class tasks such as
# schedules, persistent monitoring, notifications, and external
# service orchestration are delegated to n8n rather than handled
# by JARVIS's local task planner.
N8N_ENABLED = os.environ.get(
    "JARVIS_N8N_ENABLED",
    "0",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

N8N_BASE_URL = os.environ.get(
    "JARVIS_N8N_BASE_URL",
    "http://127.0.0.1:5678",
).strip().rstrip("/")

N8N_WEBHOOK_PATH = os.environ.get(
    "JARVIS_N8N_WEBHOOK_PATH",
    "webhook/jarvis-gateway",
).strip().strip("/")

N8N_WEBHOOK_TOKEN = os.environ.get(
    "JARVIS_N8N_WEBHOOK_TOKEN",
    "",
).strip()

N8N_TIMEOUT_SECONDS = float(
    os.environ.get(
        "JARVIS_N8N_TIMEOUT_SECONDS",
        "15",
    )
)

N8N_LOCAL_ACTION_PORT = int(
    os.environ.get(
        "JARVIS_N8N_LOCAL_ACTION_PORT",
        "8765",
    )
)


N8N_AUTOSTART = os.environ.get(
    "JARVIS_N8N_AUTOSTART",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}

N8N_AUTOSTART_TIMEOUT_SECONDS = float(
    os.environ.get(
        "JARVIS_N8N_AUTOSTART_TIMEOUT_SECONDS",
        "15",
    )
)

N8N_AUTOSTART_POLL_INTERVAL_SECONDS = float(
    os.environ.get(
        "JARVIS_N8N_AUTOSTART_POLL_INTERVAL_SECONDS",
        "0.5",
    )
)
