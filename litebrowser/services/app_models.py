from dataclasses import dataclass, field


@dataclass
class Workspace:
    id: str
    name: str
    kind: str = "generic"


@dataclass
class LibraryItem:
    id: str
    kind: str
    title: str
    subtitle: str = ""
    target: str = ""
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class SavedPage:
    id: str
    title: str
    url: str
    summary: str = ""
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class Note:
    id: str
    title: str
    kind: str = "markdown"
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class Task:
    id: str
    title: str
    bucket: str = "personal"
    completed: bool = False
    due_at: int = 0
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class CalendarEvent:
    id: str
    title: str
    starts_at: int = 0
    bucket: str = "life"
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class BoardNode:
    id: str
    kind: str
    title: str
    x: float = 0
    y: float = 0
    color: str = "#c39d63"
    payload: str = ""


@dataclass
class BoardEdge:
    id: str
    source_id: str
    target_id: str


@dataclass
class BoardStroke:
    id: str
    color: str = "#6f4e37"
    width: float = 3.0
    points: list[dict[str, float]] = field(default_factory=list)


@dataclass
class Board:
    id: str
    title: str
    nodes: list[BoardNode] = field(default_factory=list)
    edges: list[BoardEdge] = field(default_factory=list)
    strokes: list[BoardStroke] = field(default_factory=list)
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class AIMessage:
    id: str
    role: str
    content: str
    created_at: int = 0


@dataclass
class AISourceRef:
    id: str
    label: str
    target: str
    source_type: str


@dataclass
class AIThread:
    id: str
    title: str
    messages: list[AIMessage] = field(default_factory=list)
    workspace_id: str = "default"
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    archived: bool = False


@dataclass
class SyncAccount:
    id: str
    email: str
    display_name: str
    status: str = "offline-ready"


@dataclass
class SyncState:
    enabled: bool = False
    last_sync_at: int = 0
    pending_changes: int = 0
    mode: str = "local-cache"


@dataclass
class AppShellState:
    active_workspace: str = "home"
    right_panel_open: bool = True
    density: str = "comfortable"
    theme: str = "minimal"
