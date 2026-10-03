"""Plain data types describing a run and its plan."""

from dataclasses import dataclass
from pathlib import Path

from model_router import MODEL_SELECTION_AUTO


@dataclass
class SourceFile:
    path: Path
    relative_path: str
    content: str


@dataclass(frozen=True)
class PlanStep:
    id: str
    title: str
    detail: str


@dataclass(frozen=True)
class ExecutionPlan:
    summary: str
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    project_root: Path
    extra_context_paths: tuple[Path, ...]
    session_history: tuple[tuple[str, str], ...]
    apply_mode: str
    model_selection_mode: str = MODEL_SELECTION_AUTO
    model_override: str = ""
    project_instructions: str = ""
    project_instructions_status: str = ""
    request_text: str = ""
    approved_plan: ExecutionPlan | None = None
    task_id: str = ""
    inspect_round: int = 0
    inspect_parent_run_id: str = ""
    verification_round: int = 0
    session_id: str = ""
    parent_task_id: str = ""
    parent_session_id: str = ""
