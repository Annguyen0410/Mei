"""Slash-command registry: the single source of truth shared by the omnibar
hints, the command palette (quick switcher) and documentation.

Each entry: (command, takes_argument, description). The omnibar handler in
app_shell.py implements the dispatch; anything listed here MUST have a
matching _match_cmd branch there (checked by tests/test_command_registry.py).
"""

COMMANDS: tuple[tuple[str, bool, str], ...] = (
    ("/task", True, "Create a task"),
    ("/note", True, "Create a note"),
    ("/board", True, "Create an idea board"),
    ("/ask", True, "Ask with current workspace context"),
    ("/save-page", False, "Save the active browser page to Library"),
    ("/focus", True, "Start a café pour (minutes)"),
    ("/status", False, "Show current focus timer state"),
    ("/cafe", False, "Open café Focus journal / controls"),
    ("/freeze", False, "Suspend all background tabs to free memory"),
    ("/save-tabs", True, "Save current tabs as a named set"),
    ("/summarize", True, "Summarize the active browser page with AI"),
    ("/brief", False, "Show your local Morning Brief"),
    ("/agent", True, "Agent actions (summary / tasks / review)"),
    ("/group-tabs", False, "Label tabs by domain so you can filter them"),
    ("/sync", False, "Push + pull a self-hosted snapshot"),
    ("/review", False, "Flashcard review queue"),
    ("/routines", False, "Schedule daily automations"),
    ("/export", False, "Export notes as MD zip or HTML site"),
    ("/template", True, "Daily plan or weekly review note"),
    ("/theme", True, "Switch theme instantly"),
    ("/accent", True, "Switch accent color"),
    ("/hub", False, "Open the Project Hub app chain"),
)
