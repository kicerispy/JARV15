"""
JARVIS Configuration System - Centralized, typed, environment-aware.
"""
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class PersonaType(str, Enum):
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    TECHNICAL = "technical"
    CREATIVE = "creative"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class PersonaConfig:
    name: str
    formality: float = 0.5
    verbosity: float = 0.5
    humor: float = 0.3
    jargon: float = 0.5
    response_style: str = "balanced"


DEFAULT_PERSONAS: Dict[str, PersonaConfig] = {
    "professional": PersonaConfig(
        name="professional", formality=0.8, verbosity=0.4, humor=0.1, jargon=0.6, response_style="concise"
    ),
    "casual": PersonaConfig(
        name="casual", formality=0.3, verbosity=0.6, humor=0.7, jargon=0.3, response_style="conversational"
    ),
    "technical": PersonaConfig(
        name="technical", formality=0.6, verbosity=0.5, humor=0.2, jargon=0.9, response_style="detailed"
    ),
    "creative": PersonaConfig(
        name="creative", formality=0.4, verbosity=0.7, humor=0.5, jargon=0.4, response_style="expressive"
    ),
}


@dataclass
class ModelConfig:
    chat_model: str = os.environ.get("JARVIS_CHAT_MODEL", "gemma4:e2b")
    planner_model: str = os.environ.get("JARVIS_PLANNER_MODEL", "gemma4:26b")
    vision_model: str = os.environ.get("JARVIS_VISION_MODEL", "gemma4:26b")
    verify_model: str = os.environ.get("JARVIS_VERIFY_MODEL", "gemma4:e2b")
    whisper_model: str = os.environ.get("JARVIS_WHISPER_MODEL", "base")
    embedding_model: str = os.environ.get("JARVIS_EMBEDDING_MODEL", "nomic-embed-text")
    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    chunk_size: int = 1024
    mic_device: int = int(os.environ.get("JARVIS_MIC_DEVICE", "1"))
    output_device: int = int(os.environ.get("JARVIS_OUTPUT_DEVICE", "5"))
    voice_model_path: str = os.path.expanduser(
        os.environ.get("JARVIS_VOICE_MODEL", "~/.heed/voices/en_US-libritts_r-medium.onnx")
    )
    tts_length_scale: float = 1.30
    tts_noise_scale: float = 0.45
    tts_noise_w: float = 0.60
    pitch_ratio: float = 0.94
    interrupt_threshold: int = 220
    interrupt_chunks: int = 5
    interrupt_grace_seconds: float = 0.40
    prebuffer_seconds: float = 0.35
    start_timeout: float = 5.0
    continuous_start_timeout: float = 2.5
    max_recording_seconds: float = 10.0
    silence_threshold: int = 500
    silence_duration: float = 0.8
    barge_in_minimum_capture: float = 1.25
    barge_in_silence_duration: float = 1.0


@dataclass
class VisionConfig:
    min_confidence: float = 0.70
    mouse_offset_x: int = 300
    mouse_offset_y: int = 0
    click_bias_x: int = 25
    click_bias_y: int = 0
    screenshot_path: Path = BASE_DIR / "jarvis_screen.png"


@dataclass
class MemoryConfig:
    database_path: Path = BASE_DIR / "jarvis_memory.db"
    vector_db_path: Path = BASE_DIR / "vector_memory"
    graph_db_path: Path = BASE_DIR / "knowledge_graph"
    conversation_history_path: Path = BASE_DIR / "conversation_history.json"
    profile_path: Path = BASE_DIR / "profile.json"
    max_history_messages: int = 12
    max_memories_in_prompt: int = 30
    max_history_file_size: int = 200
    episodic_retention_days: int = 90
    encryption_enabled: bool = True
    encryption_key_path: Path = BASE_DIR / ".jarvis_key"


@dataclass
class MonitoringConfig:
    enabled: bool = True
    system_health_interval: int = 30
    cpu_threshold: float = 80.0
    ram_threshold: float = 85.0
    temp_threshold: float = 75.0
    code_quality_on_save: bool = True
    code_quality_tools: List[str] = field(default_factory=lambda: ["ruff", "mypy", "pytest"])
    git_status_interval: int = 60
    calendar_lookahead_minutes: int = 15


@dataclass
class SelfImprovementConfig:
    enabled: bool = True
    evaluation_interval_minutes: int = 60
    suggestion_batch_size: int = 5
    auto_apply_trait_changes: bool = True
    confidence_threshold: float = 0.7
    max_metric_history: int = 500
    feedback_enabled: bool = True
    feedback_keywords: List[str] = field(
        default_factory=lambda: ["good", "bad", "wrong", "thanks", "perfect", "terrible"]
    )


@dataclass
class SecurityConfig:
    sandbox_enabled: bool = True
    sandbox_profile: str = "firejail"
    capabilities_path: Path = BASE_DIR / "config" / "capabilities.yaml"
    audit_log_enabled: bool = True
    plugin_signing_required: bool = False


@dataclass
class UIConfig:
    dashboard_port: int = 8080
    dashboard_host: str = "127.0.0.1"
    theme: str = "holographic"
    transparency: float = 0.9
    always_on_top: bool = True
    websocket_path: str = "/ws"


@dataclass
class PluginConfig:
    enabled: List[str] = field(default_factory=lambda: ["github", "jira", "docker", "homeassistant"])
    marketplace_url: str = "https://skills.jarvis.local"
    auto_update: bool = False
    plugin_dirs: List[Path] = field(default_factory=lambda: [BASE_DIR / "jarvis_core" / "plugins"])


@dataclass
class Settings:
    persona: PersonaConfig = field(
        default_factory=lambda: PersonaConfig(
            name="professional", formality=0.8, verbosity=0.4,
            humor=0.1, jargon=0.6, response_style="concise",
        )
    )
    models: ModelConfig = field(default_factory=ModelConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    self_improvement: SelfImprovementConfig = field(default_factory=SelfImprovementConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
    log_level: LogLevel = LogLevel.INFO
    debug: bool = False

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Settings":
        settings = cls()
        if config_path and config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data:
                settings = cls._apply_dict(settings, data)
        return settings

    @classmethod
    def _apply_dict(cls, settings: "Settings", data: Dict[str, Any]) -> "Settings":
        for key, value in data.items():
            if hasattr(settings, key):
                attr = getattr(settings, key)
                if isinstance(attr, (PersonaConfig, ModelConfig, AudioConfig, VisionConfig,
                                     MemoryConfig, MonitoringConfig, SelfImprovementConfig,
                                     SecurityConfig, UIConfig, PluginConfig)):
                    if isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            if hasattr(attr, sub_key):
                                setattr(attr, sub_key, sub_value)
                elif isinstance(attr, Enum):
                    setattr(settings, key, type(attr)(value))
                else:
                    setattr(settings, key, value)
        return settings

    def save(self, config_path: Path) -> None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._to_dict()
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _to_dict(self) -> Dict[str, Any]:
        result = {}
        for key in dir(self):
            if key.startswith("_"):
                continue
            value = getattr(self, key)
            if callable(value):
                continue
            if isinstance(value, (PersonaConfig, ModelConfig, AudioConfig, VisionConfig,
                                 MemoryConfig, MonitoringConfig, SelfImprovementConfig,
                                 SecurityConfig, UIConfig, PluginConfig)):
                result[key] = value.__dict__
            elif isinstance(value, Enum):
                result[key] = value.value
            elif isinstance(value, Path):
                result[key] = str(value)
            else:
                result[key] = value
        return result


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        config_path = BASE_DIR / "config.yaml"
        _settings = Settings.load(config_path)
    return _settings


def reload_settings(config_path: Optional[Path] = None) -> Settings:
    global _settings
    path = config_path or (BASE_DIR / "config.yaml")
    _settings = Settings.load(path)
    return _settings
