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
MIC_DEVICE = 1

# voice.py currently manages the output device itself.
OUTPUT_DEVICE = 5


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

DEFAULT_WEATHER_LOCATION = "Belvidere, IL"

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
        "160",
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
