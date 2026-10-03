"""Shared configuration, limits, and policy constants."""

import re
from pathlib import Path

APP_TITLE = "CodeRouter"


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_AUTH_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
OPENROUTER_OAUTH_CALLBACK_PATH = "/oauth/callback"
OPENROUTER_OAUTH_HOST = "127.0.0.1"
OPENROUTER_OAUTH_TIMEOUT_SECONDS = 180
OPENROUTER_OAUTH_KEY_LABEL = "CodeRouter"
MODEL_DISCOVERY_TIMEOUT_SECONDS = 5
CONFIG_PATH = Path(__file__).with_name("local_config.json")
EXTERNAL_CONTEXT_PREFIX = "__external_context__"
PROJECT_INSTRUCTIONS_FILENAME = "AGENTS.md"
PROJECT_INSTRUCTIONS_MAX_BYTES = 32 * 1024
PROJECT_INSTRUCTIONS_ENCODING = "utf-8"
PROJECT_INSTRUCTIONS_MAX_DEPTH = 3
PROJECT_INSTRUCTIONS_MAX_FILES = 6
PROJECT_INSTRUCTIONS_MAX_TOTAL_BYTES = 64 * 1024
PROJECT_INSTRUCTIONS_MAX_STATUS_ITEMS = 8
VERIFICATION_COMMAND_MAX_CHARS = 240
VERIFICATION_REQUEST_MAX_CHARS = 240
VERIFICATION_TIMEOUT_SECONDS = 60
VERIFICATION_MAX_OUTPUT_BYTES = 128 * 1024
VERIFICATION_RESULT_MAX_OUTPUT_BYTES = 16 * 1024
VERIFICATION_STREAM_CHUNK_BYTES = 4096
VERIFICATION_STREAM_QUEUE_SIZE = 1
VERIFICATION_TERMINATE_GRACE_SECONDS = 0.5
VERIFICATION_POLL_INTERVAL_SECONDS = 0.1
VERIFICATION_BLOCKED_EXECUTABLES = frozenset(
    {
        "cmd",
        "cmd.exe",
        "command.com",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "sh.exe",
        "bash",
        "bash.exe",
        "zsh",
        "zsh.exe",
        "wsl",
        "wsl.exe",
        "npm.cmd",
        "pnpm.cmd",
    }
)
VERIFICATION_ALLOWED_EXECUTABLES = frozenset(
    {
        "python",
        "python.exe",
        "python3",
        "python3.exe",
        "py",
        "py.exe",
        "node",
        "node.exe",
        "npm",
        "pnpm",
        "pytest",
        "pytest.exe",
        "cargo",
        "cargo.exe",
        "dotnet",
        "dotnet.exe",
        "git",
        "git.exe",
    }
)
VERIFICATION_ENV_ALLOWED_KEYS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "HOMEDRIVE",
        "HOMEPATH",
        "USERPROFILE",
        "HOME",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "NUMBER_OF_PROCESSORS",
    }
)
VERIFICATION_ENV_MAX_ITEMS = 32
VERIFICATION_ENV_MAX_VALUE_CHARS = 4096
VERIFICATION_ENV_MAX_TOTAL_CHARS = 16 * 1024
VERIFICATION_SENSITIVE_ENV_KEY_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|authorization|bearer|password|credential|cookie|private[_-]?key)"
)
VERIFICATION_SENSITIVE_ENV_VALUE_PATTERN = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|token|secret|authorization|bearer)\b|bearer\s+\S+|authorization\s*[:=]\s*\S+|(?:api[_-]?key|token|secret)\s*[:=]\s*\S+|\bsk-(?:or-v1|proj)?-[A-Za-z0-9._-]{8,})"
)
VERIFICATION_SHELL_PATTERN = re.compile(r"[\x00\r\n;&|<>^`()$`]")

LOCAL_COMMANDS = ("/status", "/model", "/permissions", "/review")
LOCAL_COMMAND_MAX_RESULT_CHARS = 720
LOCAL_COMMAND_MAX_ITEMS = 6
LOCAL_COMMAND_HINT = "Ctrl+K command | Tab accept | Esc dismiss | Ctrl+Enter run"
MODEL_QUEUE_DISCLOSURE_MAX_RECORDS = 4
MODEL_QUEUE_DISCLOSURE_MAX_CHARS = 1200
ACTIVITY_DIGEST_MAX_CHARS = 240
ACTIVITY_DIGEST_LAST_LABEL_MAX_CHARS = 72
REVIEW_SELECTION_META_MAX_CHARS = 240
SCANNED_CONTEXT_MAX_PATHS = 6
SCANNED_CONTEXT_MAX_PATH_CHARS = 180
SCANNED_CONTEXT_MAX_CHARS = 760
TRUST_SETTINGS_MAX_CHARS = 960
LOCAL_COMMAND_POLICY_TEXT = (
    "Typed input + explicit user action only; routing settings are local and locked during active runs."
)

TASK_STATE_IDLE = "idle"
TASK_STATE_COLLECTING = "collecting"
TASK_STATE_PLANNING = "planning"
TASK_STATE_PLAN = "plan"
TASK_STATE_RUNNING = "running"
TASK_STATE_REVIEW = "review"
TASK_STATE_APPLIED = "applied"
TASK_STATE_REJECTED = "rejected"
TASK_STATE_ERROR = "error"

TASK_STATE_LABELS = {
    TASK_STATE_IDLE: "IDLE",
    TASK_STATE_COLLECTING: "COLLECTING",
    TASK_STATE_PLANNING: "PLAN",
    TASK_STATE_PLAN: "PLAN",
    TASK_STATE_RUNNING: "RUNNING",
    TASK_STATE_REVIEW: "REVIEW",
    TASK_STATE_APPLIED: "APPLIED",
    TASK_STATE_REJECTED: "REJECTED",
    TASK_STATE_ERROR: "ERROR",
}

APPLY_MODE_REVIEW = "review"
APPLY_MODE_AUTO = "auto"
PLAN_MAX_STEPS = 12
PLAN_MAX_FIELD_CHARS = 600
HISTORY_MAX_RECORDS = 50
HISTORY_MAX_BYTES = 512 * 1024
HISTORY_MAX_TEXT_CHARS = 240
HISTORY_MAX_PATH_CHARS = 1024
HISTORY_MAX_REASONS = 40
HISTORY_MAX_TRANSITIONS = 80
HISTORY_SEARCH_MAX_CHARS = 96
HISTORY_SEARCH_STATUS_MAX_CHARS = 160
HISTORY_BROWSER_MAX_STEPS = 8
HISTORY_BROWSER_MAX_TRANSITIONS = 8
HISTORY_BROWSER_MAX_REASONS = 8
SESSION_ID_MAX_CHARS = 96
SESSION_PARENT_MAX_CHARS = 128
HANDOFF_MAX_TEXT_CHARS = 240
HANDOFF_MAX_ITEMS = 24
HANDOFF_MAX_PATHS = 64
HANDOFF_MAX_BYTES = 64 * 1024
HANDOFF_MAX_COUNT = 100_000
UNDO_MAX_FILES = 64
UNDO_MAX_TOTAL_BYTES = 512 * 1024
REPORT_MAX_BYTES = 48 * 1024
REPORT_MAX_LINES = 160
REPORT_MAX_RECORDS = 40
REPORT_MAX_TEXT_CHARS = 240
REPORT_PROTECTED_NAMES = frozenset({".git", ".env", "local_config.json"})
REPORT_PROTECTED_SUFFIXES = (".key", ".pem")
PERMISSION_LEDGER_MAX_RECORDS = 64
PERMISSION_LEDGER_MAX_BYTES = 12 * 1024
PERMISSION_LEDGER_MAX_FIELD_CHARS = 96
PERMISSION_DECISION_ALLOW = "allow"
PERMISSION_DECISION_DENY = "deny"
PERMISSION_DECISION_CANCEL = "cancel"
PERMISSION_DECISIONS = frozenset(
    {
        PERMISSION_DECISION_ALLOW,
        PERMISSION_DECISION_DENY,
        PERMISSION_DECISION_CANCEL,
    }
)
PERMISSION_CATEGORIES = frozenset(
    {"inspect", "verify", "verify_policy", "apply", "undo"}
)
PERMISSION_POLICY_OUTCOMES = frozenset(
    {"preset", "unknown", "blocked", "not_applicable"}
)
WORKER_SHUTDOWN_JOIN_SECONDS = 0.15
PROVIDER_REQUEST_TIMEOUT_SECONDS = 120
MODEL_RESPONSE_MAX_SUMMARY_CHARS = 600
MODEL_RESPONSE_MAX_FILES = 64
MODEL_RESPONSE_MAX_CONTENT_BYTES = 512 * 1024
INSPECT_MAX_PATHS = 8
INSPECT_MAX_PATH_CHARS = 240
INSPECT_MAX_FILES = 8
INSPECT_MAX_FILE_BYTES = 16 * 1024
INSPECT_MAX_TOTAL_BYTES = 64 * 1024
INSPECT_MAX_ROUNDS = 2


MODEL_FALLBACKS = [
    "qwen/qwen3-coder:free",
    "deepseek/deepseek-chat-v3.1:free",
    "z-ai/glm-4.5-air:free",
    "moonshotai/kimi-k2:free",
    "openrouter/free",
]

MODEL_SOURCE_DISCOVERED = "discovered"
MODEL_SOURCE_STATIC = "static"
FREE_PROOF_ID_SUFFIX = "id_suffix"
FREE_PROOF_ZERO_PRICING = "zero_pricing"
FREE_PROOF_STATIC = "static_known_free"

MODEL_HEALTH_SUCCESS = "success"
MODEL_HEALTH_FAILURE = "failure"
MODEL_HEALTH_CANCELLED = "cancelled"
MODEL_HEALTH_STATUSES = {
    MODEL_HEALTH_SUCCESS,
    MODEL_HEALTH_FAILURE,
    MODEL_HEALTH_CANCELLED,
}
MODEL_HEALTH_DISCOVERY_ID = "__discovery__"
MODEL_HEALTH_MAX_RECORDS = 256
MODEL_HEALTH_MAX_LATENCY_MS = 120_000
MODEL_HEALTH_MAX_REASON_CHARS = 180

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    ".gradle",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "env",
}

DEFAULT_IGNORE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".jar",
    ".pyc",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".sqlite",
    ".db",
}

DEFAULT_IGNORE_FILE_NAMES = {
    ".env",
    "local_config.json",
}

DEFAULT_IGNORE_SECRET_EXTENSIONS = {
    ".key",
    ".pem",
}

PROTECTED_EDIT_PATH_NAMES = {
    ".git",
    ".env",
    "local_config.json",
    "agents.md",
}

PROTECTED_EDIT_SUFFIXES = {
    ".key",
    ".pem",
}
