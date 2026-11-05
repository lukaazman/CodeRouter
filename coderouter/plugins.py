"""Plugins: folders that bundle commands, skills, agents, output styles,
hooks and MCP servers.

    ~/.coderouter/plugins/<name>/        user plugins
    <project>/.coderouter/plugins/<name>/  project plugins

Each may contain ``commands/``, ``skills/<skill>/SKILL.md``, ``agents/``,
``output-styles/``, ``hooks.json`` (same shape as the "hooks" config) and
``.mcp.json`` (``{"mcpServers": {...}}``). An optional ``plugin.json`` gives
``description`` and ``version``. Disabled names live in config
``"plugins_disabled"``.
"""

import json
from dataclasses import dataclass
from pathlib import Path

PLUGIN_MAX = 50


@dataclass(frozen=True)
class Plugin:
    name: str
    root: Path
    scope: str
    description: str = ""
    version: str = ""

    def subdir(self, name):
        path = self.root / name
        return path if path.is_dir() else None


def plugin_roots(project_root=None, home=None):
    home = Path(home) if home else Path.home()
    roots = [("user", home / ".coderouter" / "plugins")]
    if project_root:
        roots.append(("project", Path(project_root) / ".coderouter" / "plugins"))
    return roots


def discover_plugins(project_root=None, home=None, disabled=()):
    disabled = set(disabled or ())
    found = []
    for scope, base in plugin_roots(project_root, home):
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir())[:PLUGIN_MAX]:
            if not path.is_dir() or path.is_symlink() or path.name.startswith("."):
                continue
            meta = {}
            manifest = path / "plugin.json"
            try:
                if manifest.is_file():
                    meta = json.loads(manifest.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                meta = {}
            plugin = Plugin(path.name, path, scope, str(meta.get("description", ""))[:200], str(meta.get("version", ""))[:20])
            found.append((plugin, plugin.name not in disabled))
    return found


def enabled_plugins(project_root=None, home=None, disabled=()):
    return [plugin for plugin, enabled in discover_plugins(project_root, home, disabled) if enabled]


def plugin_dirs(plugins, folder):
    """(scope, path) pairs for a content folder ("commands", "skills", ...)."""
    pairs = []
    for plugin in plugins:
        path = plugin.subdir(folder)
        if path:
            pairs.append((f"plugin:{plugin.name}", path))
    return pairs


def plugin_hooks(plugins):
    merged = {}
    for plugin in plugins:
        path = plugin.root / "hooks.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            continue
        for event, entries in (data.get("hooks", data) or {}).items():
            if isinstance(entries, list):
                merged.setdefault(event, []).extend(entries)
    return merged


def plugin_mcp_servers(plugins):
    servers = {}
    for plugin in plugins:
        path = plugin.root / ".mcp.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            continue
        for name, spec in (data.get("mcpServers") or {}).items():
            if isinstance(spec, dict):
                servers[f"{plugin.name}-{name}"] = {**spec, "_plugin": plugin.name, "_cwd": str(plugin.root)}
    return servers
