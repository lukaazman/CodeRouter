"""Minimal Model Context Protocol client over stdio (tools only).

Servers come from local_config.json ``"mcp_servers"`` (trusted, user owned)
and the project's ``.mcp.json`` (``{"mcpServers": {...}}``), which only start
after ``/mcp enable <name>``. Each server is an argv command; no shell.
"""

import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
REQUEST_TIMEOUT_SECONDS = 30
RESULT_MAX_CHARS = 16 * 1024
CATALOG_MAX_TOOLS = 40
SHELLS = {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"}


@dataclass
class ServerSpec:
    name: str
    command: list
    env: dict = field(default_factory=dict)
    source: str = "user"  # user | project
    cwd: str = ""


def _spec_from(name, data, source, cwd=""):
    if not isinstance(data, dict):
        return None
    command = data.get("command")
    args = data.get("args") or []
    if isinstance(command, str):
        command = [command] + [str(arg) for arg in args if isinstance(arg, (str, int, float))]
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        return None
    if os.path.basename(command[0]).lower() in SHELLS:
        return None
    env = {str(k): str(v) for k, v in (data.get("env") or {}).items()} if isinstance(data.get("env"), dict) else {}
    return ServerSpec(name=name, command=command, env=env, source=source, cwd=cwd)


def load_server_specs(config, project_root=None):
    specs = {}
    for name, data in (config.get("mcp_servers") or {}).items():
        spec = _spec_from(str(name), data, "user")
        if spec:
            specs[spec.name] = spec
    if project_root:
        path = Path(project_root) / ".mcp.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        for name, entry in (data.get("mcpServers") or {}).items():
            spec = _spec_from(str(name), entry, "project", cwd=str(project_root))
            if spec and spec.name not in specs:
                specs[spec.name] = spec
    return specs


class McpError(RuntimeError):
    pass


class McpServer:
    def __init__(self, spec, popen=subprocess.Popen):
        self.spec = spec
        self.tools = []
        self._popen = popen
        self._process = None
        self._responses = queue.Queue()
        self._lock = threading.Lock()
        self._next_id = 0
        self.error = ""

    @property
    def running(self):
        return self._process is not None and self._process.poll() is None

    def start(self):
        env = dict(os.environ)
        env.update(self.spec.env)
        self._process = self._popen(
            self.spec.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=self.spec.cwd or None,
            env=env,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "CodeRouter", "version": "1.0"},
        })
        self.notify("notifications/initialized")
        result = self.request("tools/list", {})
        self.tools = list(result.get("tools") or [])[:CATALOG_MAX_TOOLS]
        return self.tools

    def _reader(self):
        stream = self._process.stdout
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and "id" in message and ("result" in message or "error" in message):
                self._responses.put(message)

    def _send(self, payload):
        if not self.running:
            raise McpError(f"{self.spec.name} is not running")
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()

    def notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def request(self, method, params, timeout=REQUEST_TIMEOUT_SECONDS):
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            while True:
                try:
                    message = self._responses.get(timeout=timeout)
                except queue.Empty as exc:
                    raise McpError(f"{self.spec.name}: {method} timed out") from exc
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message["error"] or {}
                    raise McpError(f"{self.spec.name}: {error.get('message', 'error')}")
                return message.get("result") or {}

    def call_tool(self, tool, arguments):
        result = self.request("tools/call", {"name": tool, "arguments": arguments or {}})
        parts = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict):
                parts.append(f"[{item.get('type', 'content')} omitted]")
        text = "\n".join(parts) or json.dumps(result.get("structuredContent", {}))[:RESULT_MAX_CHARS]
        if result.get("isError"):
            text = "Tool error: " + text
        return text[:RESULT_MAX_CHARS]

    def stop(self):
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass
        for stream in (process.stdout,):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


class McpManager:
    def __init__(self, specs=None, enabled_project=(), popen=subprocess.Popen):
        self.specs = dict(specs or {})
        self.enabled_project = set(enabled_project)
        self.servers = {}
        self._popen = popen

    def startable(self, name):
        spec = self.specs.get(name)
        return bool(spec) and (spec.source == "user" or name in self.enabled_project)

    def start(self, name):
        if not self.startable(name):
            raise McpError(f"{name} is a project server; run /mcp enable {name} first")
        server = self.servers.get(name)
        if server and server.running:
            return server
        server = McpServer(self.specs[name], popen=self._popen)
        try:
            server.start()
        except (OSError, McpError) as exc:
            server.error = str(exc)
            server.stop()
            raise McpError(f"{name}: {exc}") from exc
        self.servers[name] = server
        return server

    def start_all(self):
        errors = []
        for name in self.specs:
            if self.startable(name):
                try:
                    self.start(name)
                except McpError as exc:
                    errors.append(str(exc))
        return errors

    def stop_all(self):
        for server in self.servers.values():
            server.stop()
        self.servers = {}

    def tool_names(self):
        return [f"{name}.{tool.get('name')}" for name, server in self.servers.items() if server.running for tool in server.tools]

    def catalog_text(self):
        lines = []
        for name, server in self.servers.items():
            if not server.running:
                continue
            for tool in server.tools:
                schema = json.dumps(tool.get("inputSchema") or {}, separators=(",", ":"))[:400]
                description = " ".join(str(tool.get("description") or "").split())[:200]
                lines.append(f"- {name}.{tool.get('name')}: {description} args={schema}")
        return "\n".join(lines)

    def call(self, qualified, arguments):
        name, _, tool = str(qualified).partition(".")
        server = self.servers.get(name)
        if server is None or not server.running:
            raise McpError(f"MCP server {name} is not connected")
        if tool not in {item.get("name") for item in server.tools}:
            raise McpError(f"{name} has no tool {tool}")
        return server.call_tool(tool, arguments)
