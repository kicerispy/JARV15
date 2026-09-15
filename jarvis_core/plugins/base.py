"""
JARVIS Plugin System - Base classes and plugin manager.
"""
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Plugin, PluginManifest, Tool

logger = get_logger(__name__)


class BasePlugin:
    def __init__(self):
        self._initialized = False
        self._config: Dict[str, Any] = {}

    @property
    def manifest(self) -> PluginManifest:
        raise NotImplementedError

    async def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}
        self._initialized = True
        logger.debug(f"Plugin initialized: {self.manifest.name}")

    async def shutdown(self) -> None:
        self._initialized = False
        logger.debug(f"Plugin shutdown: {self.manifest.name}")

    def get_tools(self) -> List[Tool]:
        return []

    def get_agents(self) -> List[Agent]:
        return []


class PluginManager:
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._plugin_dirs: List[Path] = []

    def add_plugin_dir(self, path: Path) -> None:
        if path not in self._plugin_dirs:
            self._plugin_dirs.append(path)

    async def load_plugin(self, plugin_path: Path) -> Optional[Plugin]:
        try:
            spec = importlib.util.spec_from_file_location("plugin_module", plugin_path)
            if not spec or not spec.loader:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules["plugin_module"] = module
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BasePlugin) and attr is not BasePlugin:
                    plugin = attr()
                    await plugin.initialize()
                    self._plugins[plugin.manifest.name] = plugin
                    logger.info(f"Loaded plugin: {plugin.manifest.name} v{plugin.manifest.version}")
                    return plugin

        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_path}: {e}")

        return None

    async def load_all_plugins(self) -> None:
        for plugin_dir in self._plugin_dirs:
            if not plugin_dir.exists():
                continue

            for plugin_file in plugin_dir.glob("*.py"):
                if plugin_file.name.startswith("_"):
                    continue
                await self.load_plugin(plugin_file)

    async def load_builtin_plugins(self) -> None:
        from jarvis_core.plugins.code_tools import CodeToolsPlugin
        from jarvis_core.plugins.file_tools import FileToolsPlugin
        from jarvis_core.plugins.screen_tools import ScreenToolsPlugin
        from jarvis_core.plugins.system_tools import SystemToolsPlugin
        from jarvis_core.plugins.web_tools import WebToolsPlugin

        builtins = [
            FileToolsPlugin(),
            WebToolsPlugin(),
            SystemToolsPlugin(),
            ScreenToolsPlugin(),
            CodeToolsPlugin(),
        ]

        for plugin in builtins:
            await plugin.initialize()
            self._plugins[plugin.manifest.name] = plugin

    def get_plugin(self, name: str) -> Optional[Plugin]:
        return self._plugins.get(name)

    def get_all_tools(self) -> Dict[str, Tool]:
        tools = {}
        for plugin in self._plugins.values():
            for tool in plugin.get_tools():
                tools[tool.name] = tool
        return tools

    def get_all_agents(self) -> List[Agent]:
        agents = []
        for plugin in self._plugins.values():
            agents.extend(plugin.get_agents())
        return agents

    async def shutdown_all(self) -> None:
        for plugin in self._plugins.values():
            await plugin.shutdown()
        self._plugins.clear()


_global_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _global_plugin_manager
    if _global_plugin_manager is None:
        _global_plugin_manager = PluginManager()
    return _global_plugin_manager
