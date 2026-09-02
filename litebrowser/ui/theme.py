from PyQt5.QtCore import QEasingCurve, QPropertyAnimation
from PyQt5.QtWidgets import QGraphicsOpacityEffect

PALETTES = {
    "cafe-night": {
        # Warm dark chrome: deeper base, clearer separation, brighter accent for focus.
        "MAIN_BG": "#131009",
        "MAIN_BG_ALT": "#1a130c",
        "SIDEBAR_BG": "#171209",
        "SIDEBAR_BORDER": "#2c2115",
        "CARD_BG": "#1d1710",
        "INPUT_BG": "#221a11",
        "INPUT_BORDER": "#40301f",
        "INPUT_FOCUS": "#d0a55f",
        "TEXT": "#f4ead8",
        "TEXT_MUTED": "#b3a187",
        "ACCENT": "#c9a05a",
        "ACCENT_HOVER": "#e0b878",
        "ACCENT_SOFT": "#3a2c18",
        "ITEM_HOVER": "#2a2114",
        "ITEM_SELECTED": "#3a2b15",
        "ITEM_SELECTED_BORDER": "#e0b878",
        "BUTTON_BG": "#2a2013",
        "BUTTON_HOVER": "#37281a",
        "BUTTON_TEXT": "#f4ead8",
        "MENU_BG": "#1c150d",
        "MENU_ITEM_SEL": "#453017",
        "BORDER_SOFT": "#251b0e",
        "DANGER": "#d06a5a",
        "SUCCESS": "#8aa064",
    },
    "cafe-day": {
        "MAIN_BG": "#f1e7d5",
        "MAIN_BG_ALT": "#e7dac2",
        "SIDEBAR_BG": "#ead9bd",
        "SIDEBAR_BORDER": "#c3ab86",
        "CARD_BG": "#f7efe0",
        "INPUT_BG": "#fdfaf3",
        "INPUT_BORDER": "#c8ac82",
        "INPUT_FOCUS": "#9c6a30",
        "TEXT": "#2b2013",
        "TEXT_MUTED": "#665746",
        "ACCENT": "#99702f",
        "ACCENT_HOVER": "#b3823a",
        "ACCENT_SOFT": "#dfc69c",
        "ITEM_HOVER": "#e6d3b6",
        "ITEM_SELECTED": "#dfca9f",
        "ITEM_SELECTED_BORDER": "#99702f",
        "BUTTON_BG": "#ecdcbe",
        "BUTTON_HOVER": "#e0cba9",
        "BUTTON_TEXT": "#2b2013",
        "MENU_BG": "#f6edda",
        "MENU_ITEM_SEL": "#e3cdaa",
        "BORDER_SOFT": "#d9c49d",
        "DANGER": "#b3503e",
        "SUCCESS": "#5f7a3c",
    },
    "ocean-night": {
        # Cool, focused dark theme with a blue-tinted surface (default accent is teal).
        "MAIN_BG": "#0f141c",
        "MAIN_BG_ALT": "#141b26",
        "SIDEBAR_BG": "#101722",
        "SIDEBAR_BORDER": "#223045",
        "CARD_BG": "#161e2a",
        "INPUT_BG": "#1a2331",
        "INPUT_BORDER": "#34445e",
        "INPUT_FOCUS": "#57b8ac",
        "TEXT": "#e6edf6",
        "TEXT_MUTED": "#93a3b8",
        "ACCENT": "#3aa59a",
        "ACCENT_HOVER": "#57c2b5",
        "ACCENT_SOFT": "#1a3533",
        "ITEM_HOVER": "#1f2b3c",
        "ITEM_SELECTED": "#1e3a3a",
        "ITEM_SELECTED_BORDER": "#57c2b5",
        "BUTTON_BG": "#202b3a",
        "BUTTON_HOVER": "#2a3a4d",
        "BUTTON_TEXT": "#e6edf6",
        "MENU_BG": "#141c28",
        "MENU_ITEM_SEL": "#24424a",
        "BORDER_SOFT": "#202b3a",
        "DANGER": "#e06a5a",
        "SUCCESS": "#6fae77",
    },
    "sand-day": {
        # Bright, airy light theme with neutral paper tones + a darker legible accent.
        "MAIN_BG": "#f5f1e8",
        "MAIN_BG_ALT": "#ece6d8",
        "SIDEBAR_BG": "#efe8d9",
        "SIDEBAR_BORDER": "#cfc3a8",
        "CARD_BG": "#fbf8f0",
        "INPUT_BG": "#ffffff",
        "INPUT_BORDER": "#d3c9b0",
        "INPUT_FOCUS": "#8a6d3f",
        "TEXT": "#2c2822",
        "TEXT_MUTED": "#6f675a",
        "ACCENT": "#9a7b52",
        "ACCENT_HOVER": "#ae8d60",
        "ACCENT_SOFT": "#e6dcc8",
        "ITEM_HOVER": "#ece5d3",
        "ITEM_SELECTED": "#e3d7bd",
        "ITEM_SELECTED_BORDER": "#9a7b52",
        "BUTTON_BG": "#f2ecdc",
        "BUTTON_HOVER": "#e6ddc6",
        "BUTTON_TEXT": "#2c2822",
        "MENU_BG": "#faf6ec",
        "MENU_ITEM_SEL": "#e7dcc0",
        "BORDER_SOFT": "#e2dac4",
        "DANGER": "#c05442",
        "SUCCESS": "#6f8f4e",
    },
    "minimal": {
        # Minimal coffee shop: flat latte cream surfaces, hairline mocha borders,
        # espresso ink + a warm café accent. Default theme for new profiles.
        "MAIN_BG": "#faf7f1",
        "MAIN_BG_ALT": "#f4eee3",
        "SIDEBAR_BG": "#f5efe4",
        "SIDEBAR_BORDER": "#e6ddcc",
        "CARD_BG": "#fffdf8",
        "INPUT_BG": "#ffffff",
        "INPUT_BORDER": "#d8cdb8",
        "INPUT_FOCUS": "#6f4c37",
        "TEXT": "#2e271f",
        "TEXT_MUTED": "#8a7a68",
        "ACCENT": "#6f4c37",
        "ACCENT_HOVER": "#8a6448",
        "ACCENT_SOFT": "#f3e9da",
        "ITEM_HOVER": "#f5efe3",
        "ITEM_SELECTED": "#eadfc9",
        "ITEM_SELECTED_BORDER": "#6f4c37",
        "BUTTON_BG": "#f4ede1",
        "BUTTON_HOVER": "#e9ddc8",
        "BUTTON_TEXT": "#2e271f",
        "MENU_BG": "#fffdf8",
        "MENU_ITEM_SEL": "#f2e7d3",
        "BORDER_SOFT": "#e9e0cf",
        "DANGER": "#c0533f",
        "SUCCESS": "#5f7a45",
    },
    "minimal-night": {
        # Reverse coffee shop: roasted espresso, hairline mocha borders, latte accent.
        "MAIN_BG": "#181310",
        "MAIN_BG_ALT": "#231c16",
        "SIDEBAR_BG": "#1c1612",
        "SIDEBAR_BORDER": "#332a20",
        "CARD_BG": "#211a14",
        "INPUT_BG": "#241d17",
        "INPUT_BORDER": "#3d3226",
        "INPUT_FOCUS": "#d6b48a",
        "TEXT": "#f3e9d8",
        "TEXT_MUTED": "#a89682",
        "ACCENT": "#c9a05a",
        "ACCENT_HOVER": "#e0b878",
        "ACCENT_SOFT": "#2d2318",
        "ITEM_HOVER": "#2a2219",
        "ITEM_SELECTED": "#3a2b17",
        "ITEM_SELECTED_BORDER": "#e0b878",
        "BUTTON_BG": "#2a2219",
        "BUTTON_HOVER": "#372b1e",
        "BUTTON_TEXT": "#f4ead8",
        "MENU_BG": "#241e18",
        "MENU_ITEM_SEL": "#453017",
        "BORDER_SOFT": "#332a20",
        "DANGER": "#d97a63",
        "SUCCESS": "#8aa064",
    },
    "forest-night": {
        # Deep woodland dark: pine surfaces, moss borders, spring-green accent.
        "MAIN_BG": "#0e1a14",
        "MAIN_BG_ALT": "#13221b",
        "SIDEBAR_BG": "#101d16",
        "SIDEBAR_BORDER": "#24382d",
        "CARD_BG": "#16241c",
        "INPUT_BG": "#1a2b21",
        "INPUT_BORDER": "#33493a",
        "INPUT_FOCUS": "#7fd6a2",
        "TEXT": "#e8f1ea",
        "TEXT_MUTED": "#9db3a5",
        "ACCENT": "#4fae7b",
        "ACCENT_HOVER": "#72d29b",
        "ACCENT_SOFT": "#1c3327",
        "ITEM_HOVER": "#1e2d25",
        "ITEM_SELECTED": "#1f3b2b",
        "ITEM_SELECTED_BORDER": "#72d29b",
        "BUTTON_BG": "#1e2d25",
        "BUTTON_HOVER": "#283b30",
        "BUTTON_TEXT": "#e8f1ea",
        "MENU_BG": "#15211b",
        "MENU_ITEM_SEL": "#2a4a37",
        "BORDER_SOFT": "#1e2d25",
        "DANGER": "#e0685a",
        "SUCCESS": "#7fbe8d",
    },
    "rose-day": {
        # Soft light rose: warm paper, blush borders, dusty-rose accent.
        "MAIN_BG": "#fbf4f2",
        "MAIN_BG_ALT": "#f3e7e3",
        "SIDEBAR_BG": "#f6ebe7",
        "SIDEBAR_BORDER": "#e2cbc4",
        "CARD_BG": "#fffbfa",
        "INPUT_BG": "#ffffff",
        "INPUT_BORDER": "#e0c9c1",
        "INPUT_FOCUS": "#c2566a",
        "TEXT": "#33222a",
        "TEXT_MUTED": "#93777f",
        "ACCENT": "#b44d63",
        "ACCENT_HOVER": "#d16a80",
        "ACCENT_SOFT": "#f6dde2",
        "ITEM_HOVER": "#f7ece9",
        "ITEM_SELECTED": "#f3dbe0",
        "ITEM_SELECTED_BORDER": "#b44d63",
        "BUTTON_BG": "#f7ece8",
        "BUTTON_HOVER": "#efdcd6",
        "BUTTON_TEXT": "#33222a",
        "MENU_BG": "#fffbfa",
        "MENU_ITEM_SEL": "#f6dfe3",
        "BORDER_SOFT": "#eedcd6",
        "DANGER": "#c2513f",
        "SUCCESS": "#6f8f4e",
    },
    "latte": {
        # Airy modern coffee house: steamed-milk surfaces, gentle mocha lines,
        # a caramel accent. Flat and soft — the calm, creative daytime café.
        "MAIN_BG": "#fdfaf4",
        "MAIN_BG_ALT": "#f6efe3",
        "SIDEBAR_BG": "#f8f1e6",
        "SIDEBAR_BORDER": "#e7dcc7",
        "CARD_BG": "#fffdf9",
        "INPUT_BG": "#ffffff",
        "INPUT_BORDER": "#e0d5c0",
        "INPUT_FOCUS": "#b5793d",
        "TEXT": "#32291f",
        "TEXT_MUTED": "#8f7f6b",
        "ACCENT": "#a9773f",
        "ACCENT_HOVER": "#c08c4e",
        "ACCENT_SOFT": "#f2e6d3",
        "ITEM_HOVER": "#f5eee1",
        "ITEM_SELECTED": "#ecddc4",
        "ITEM_SELECTED_BORDER": "#a9773f",
        "BUTTON_BG": "#f5ede0",
        "BUTTON_HOVER": "#ecdfc9",
        "BUTTON_TEXT": "#32291f",
        "MENU_BG": "#fffdf9",
        "MENU_ITEM_SEL": "#f3e5cd",
        "BORDER_SOFT": "#ece1cf",
        "DANGER": "#c05642",
        "SUCCESS": "#6c8a4e",
    },
}

# Theme shown when a profile has never picked one (and for unknown names).
DEFAULT_THEME = "minimal"

DEFAULTS = {
    "TEXT_DIM": "#8a7a63",
    "RADIUS": "10px",
    "RADIUS_SM": "6px",
    # Kept for API compatibility; actual fallback is applied at app level via
    # QFont.setFamilies in litebrowser.main (QSS font-family cannot fall back).
    "FONT_FAMILY": '"Segoe UI", "Segoe UI Symbol", "Segoe UI Emoji", "Helvetica Neue", Arial, sans-serif',
    "TITLE_FONT": 'Georgia, "Times New Roman", serif',
}

# Accent presets: each is a (base, hover, soft, focus) tuple. The user picks one in
# Settings; it recolors buttons, active states, and focus rings across every theme.
ACCENTS = {
    "brass":     ("#c9a05a", "#e0b878", "#3a2c18", "#d0a55f"),  # default warm cafe brass
    "ember":     ("#d0643a", "#e8895f", "#3c2418", "#e07a4a"),
    "teal":      ("#3aa59a", "#57c2b5", "#17312e", "#45b8ac"),
    "violet":    ("#9678d6", "#b79ae8", "#2c2342", "#a989e0"),
    "sky":       ("#4a8fd6", "#6fb0ec", "#1c2e42", "#5599e0"),
    "rose":      ("#d65a8f", "#ec7fb2", "#3d1f30", "#e06a9f"),
    "slate":     ("#8a97a8", "#aebbcb", "#262c34", "#98a6b8"),
}
_ACCENT_KEYS = ("ACCENT", "ACCENT_HOVER", "ACCENT_SOFT", "INPUT_FOCUS")


def accent_keys():
    """Names of the theme tokens controlled by the selected accent preset."""
    return _ACCENT_KEYS


def _accent_override(accent: str | None) -> dict:
    preset = ACCENTS.get(accent or "") if accent else None
    if not preset:
        return {}
    return dict(zip(_ACCENT_KEYS, preset))


def _is_light_color(value: str) -> bool:
    """Return whether a hex color is bright enough for a light UI surface."""
    try:
        value = value.lstrip("#")
        red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
        return (red * 299 + green * 587 + blue * 114) / 1000 >= 150
    except (TypeError, ValueError):
        return False


def _blend_hex(foreground: str, background: str, amount: float) -> str:
    """Mix ``foreground`` into ``background`` without introducing a dark chip."""
    try:
        foreground = foreground.lstrip("#")
        background = background.lstrip("#")
        source = [int(foreground[index:index + 2], 16) for index in (0, 2, 4)]
        base = [int(background[index:index + 2], 16) for index in (0, 2, 4)]
        mixed = [round(base[index] + (source[index] - base[index]) * amount) for index in range(3)]
        return "#" + "".join(f"{channel:02x}" for channel in mixed)
    except (TypeError, ValueError):
        return foreground if foreground.startswith("#") else f"#{foreground}"


def _palette(mode: str, accent: str | None = None):
    palette = dict(DEFAULTS)
    palette.update(PALETTES.get(mode, PALETTES["cafe-night"]))
    override = _accent_override(accent)
    palette.update(override)
    # Accent presets include a dark soft tone for night themes.  Reusing it on
    # cafe-day creates near-black active buttons, so derive a paper-tinted
    # accent surface for every light theme instead.
    if override and _is_light_color(palette["MAIN_BG"]):
        palette["ACCENT_SOFT"] = _blend_hex(palette["ACCENT"], palette["MAIN_BG"], 0.20)
    return palette


def palette_tokens(mode: str = "minimal", accent: str | None = None) -> dict:
    """Public accessor for the resolved color tokens (theme palette + accent merged).

    Shared by the shell QSS and the local new-tab page so the speed dial follows
    the active theme instead of staying hard-coded dark.
    """
    return _palette(mode, accent)


def palette(mode: str | None = None, accent: str | None = None) -> dict:
    """Resolved tokens for the *stored* profile theme when no mode is given."""
    if mode is None:
        from litebrowser.core import prefs as _prefs

        mode = _prefs.get_shell_theme(_prefs.DEFAULT_BASE_DIR) or DEFAULT_THEME
    return _palette(mode, accent)


def main_qss(mode: str = "cafe-night", accent: str | None = None):
    p = _palette(mode, accent)
    return """
/* ================= Mei 6.3 — modern chrome ================= */

/* ---------- base: flat minimal layers ---------- */
QMainWindow, QWidget {
    background-color: %(MAIN_BG)s;
    color: %(TEXT)s;
    font-size: 13px;
}
#ShellRoot, #MainWidget {
    background-color: %(MAIN_BG)s;
}
#ShellTopBar {
    background-color: %(CARD_BG)s;
    border-bottom: 1px solid %(BORDER_SOFT)s;
    padding: 6px 12px;
}
#ShellBrand { color: %(TEXT)s; letter-spacing: 0.4px; font-weight: 600; }
#BrandGlyph { color: %(ACCENT_HOVER)s; font-size: 26px; }
#BrandName { color: %(TEXT)s; font-size: 16px; font-weight: 800; letter-spacing: 0.3px; }
#BrandSub { color: %(TEXT_MUTED)s; font-size: 10px; letter-spacing: 0.5px; }
#StatusPill {
    background-color: %(ACCENT_SOFT)s; color: %(ACCENT_HOVER)s;
    border: 1px solid %(INPUT_BORDER)s; border-radius: 999px;
    padding: 2px 12px; font-size: 11px; font-weight: 700;
}

/* ---------- inputs & editors ---------- */
#ShellOmnibar, #UrlBar, QLineEdit, QTextEdit, QListWidget, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: %(INPUT_BG)s;
    color: %(TEXT)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: %(RADIUS_SM)s;
    padding: 5px 9px;
    selection-background-color: %(MENU_ITEM_SEL)s;
    selection-color: %(TEXT)s;
}
#ShellOmnibar:hover, #UrlBar:hover, QLineEdit:hover, QTextEdit:hover, QListWidget:hover, QComboBox:hover, QSpinBox:hover {
    border-color: %(ACCENT)s;
}
#ShellOmnibar:focus, #UrlBar:focus, QLineEdit:focus, QTextEdit:focus, QListWidget:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border-color: %(INPUT_FOCUS)s;
    background-color: %(CARD_BG)s;
}
#ShellOmnibar { min-height: 28px; font-size: 12px; padding: 5px 10px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { width: 10px; height: 10px; }
QComboBox QAbstractItemView {
    background-color: %(MENU_BG)s;
    color: %(TEXT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: %(RADIUS_SM)s;
    padding: 4px;
    selection-background-color: %(MENU_ITEM_SEL)s;
    selection-color: %(TEXT)s;
}
QScrollArea#SettingsScroll {
    border: none;
    background-color: %(MAIN_BG)s;
}
QScrollArea#SettingsScroll > QWidget > QWidget { background-color: %(MAIN_BG)s; }

/* ---------- labels ---------- */
QLabel { color: %(TEXT)s; background: transparent; }
#MutedLabel { color: %(TEXT_MUTED)s; font-size: 11px; }
#SectionTitle { color: %(ACCENT_HOVER)s; font-weight: 700; letter-spacing: 0.4px; font-size: 12px; text-transform: uppercase; }
#HeroTitle { color: %(TEXT)s; font-family: %(TITLE_FONT)s; }
#HeroSubtitle { color: %(TEXT_MUTED)s; font-size: 13px; }
#HeroBadge {
    background-color: %(ACCENT_SOFT)s; color: %(ACCENT_HOVER)s;
    border: 1px solid %(INPUT_BORDER)s; border-radius: %(RADIUS_SM)s;
    padding: 3px 10px; font-size: 11px; font-weight: 700;
}

/* ---------- shared components (ui/components.py) ---------- */
#PageHeader { background: transparent; }
#PageGlyph { color: %(ACCENT_HOVER)s; font-size: 20px; }
#PageTitle { color: %(TEXT)s; }
#PageSubtitle { color: %(TEXT_MUTED)s; font-size: 11px; }

#StatRow { background: transparent; }
#StatTile {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: %(RADIUS_SM)s;
}
#StatTile:hover { border-color: %(ACCENT)s; }
#StatValue { color: %(ACCENT_HOVER)s; }
#StatLabel { color: %(TEXT_MUTED)s; font-size: 11px; }

#SectionHeaderRow { background: transparent; }
#EmptyState {
    background-color: %(CARD_BG)s;
    border: 1px dashed %(BORDER_SOFT)s;
    border-radius: %(RADIUS_SM)s;
}
#EmptyGlyph { color: %(ACCENT_SOFT)s; font-size: 26px; }

/* ---------- action tiles (dashboard launchers) ---------- */
#ActionTile {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: %(RADIUS)s;
    padding: 6px;
}
#ActionTile:hover {
    border-color: %(ACCENT)s;
    background-color: %(ITEM_HOVER)s;
}
#ActionTile:pressed { background-color: %(ITEM_SELECTED)s; }
#ActionGlyph { color: %(ACCENT_HOVER)s; font-size: 22px; }
#ActionLabel { color: %(TEXT)s; font-weight: 700; font-size: 13px; }
#ActionHint { color: %(TEXT_MUTED)s; font-size: 10px; }

/* ---------- chips (filter toggles) ---------- */
#Chip {
    background-color: %(MAIN_BG_ALT)s;
    color: %(TEXT_MUTED)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 999px;
    padding: 4px 11px;
    font-size: 11px;
    font-weight: 600;
}
#Chip:hover { border-color: %(ACCENT)s; color: %(TEXT)s; background-color: %(ITEM_HOVER)s; }
#Chip:checked {
    background-color: %(ACCENT_SOFT)s;
    color: %(ACCENT_HOVER)s;
    border-color: %(ACCENT)s;
}

/* ---------- badges ---------- */
#Badge {
    background-color: %(MAIN_BG_ALT)s;
    color: %(TEXT_MUTED)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 700;
}
#BadgeAccent {
    background-color: %(ACCENT_SOFT)s;
    color: %(ACCENT_HOVER)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 800;
}

/* ---------- rail footer / meta chips ---------- */
#RailMeta {
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: %(RADIUS_SM)s;
    padding: 5px 8px;
    font-size: 11px;
    color: %(TEXT_MUTED)s;
}

/* ---------- left rail / nav ---------- */
#LeftRail {
    background-color: %(SIDEBAR_BG)s;
    border-right: 1px solid %(BORDER_SOFT)s;
}
#NavButton {
    text-align: left; padding: 7px 11px; font-weight: 600;
    border: 1px solid transparent; border-radius: %(RADIUS_SM)s;
    color: %(TEXT_MUTED)s; background: transparent;
}
#NavButton:hover { background-color: %(ITEM_HOVER)s; color: %(TEXT)s; }
#NavButton:checked {
    background-color: %(ITEM_SELECTED)s;
    border: 1px solid %(ITEM_SELECTED_BORDER)s;
    color: %(ACCENT_HOVER)s;
}

/* ---------- buttons ---------- */
QPushButton, #CafeButton {
    background-color: %(BUTTON_BG)s;
    color: %(BUTTON_TEXT)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: %(RADIUS_SM)s;
    padding: 5px 10px;
    min-height: 16px;
    font-weight: 600;
}
QPushButton:hover, #CafeButton:hover { background-color: %(BUTTON_HOVER)s; border-color: %(ACCENT)s; }
QPushButton:pressed, #CafeButton:pressed { background-color: %(ITEM_SELECTED)s; }
QPushButton:disabled { color: %(TEXT_DIM)s; background-color: %(MAIN_BG_ALT)s; border-color: %(BORDER_SOFT)s; }
QPushButton#TopAccentButton {
    background-color: %(ACCENT)s;
    color: #141414; border: none; font-weight: 800;
}
QPushButton#TopAccentButton:hover { background-color: %(ACCENT_HOVER)s; }

#StatusStrip {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: %(RADIUS_SM)s;
    padding: 3px 8px;
}

/* ---------- cards / panels: elevated surfaces ---------- */
#InsightPanel, #HeroCard, #SectionCard, #StatCard, #TopBar, #TopBarCluster, #AddressCluster {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: %(RADIUS)s;
}
#InsightPanel { border-left: none; border-radius: 0; border-top-left-radius: 0; border-bottom-left-radius: 0; }
/* WebEngine draws its own surface; avoid rounded card chrome that skews layout perception. */
#WebContainer { background-color: %(MAIN_BG)s; border: none; border-radius: 0; }

#HeroCard {
    background-color: %(CARD_BG)s;
    border: 1px solid %(INPUT_BORDER)s;
}
#StatCard {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
}
#StatCard:hover { border-color: %(ACCENT)s; }
#StatCard QLabel { font-weight: 600; }

/* ---------- top bar (browser chrome) ---------- */
#TopBar { background-color: %(CARD_BG)s; border: 1px solid %(BORDER_SOFT)s; padding: 4px; }
#TopBarCluster, #AddressCluster { background-color: %(MAIN_BG_ALT)s; border: 1px solid %(BORDER_SOFT)s; }
#AddressCluster #UrlBar { background: transparent; border: none; padding: 6px 8px; font-size: 12px; font-weight: 600; }
#AddressHint { color: %(ACCENT_HOVER)s; background: transparent; font-size: 9px; font-weight: 800; letter-spacing: 1px; padding: 0 2px; text-transform: uppercase; }
#TopBar #SearchEngine, #SearchEngine, #WorkspaceCombo {
    min-height: 30px; background-color: %(INPUT_BG)s; color: %(TEXT)s;
    border: 1px solid %(INPUT_BORDER)s; border-radius: %(RADIUS_SM)s; padding: 4px 22px 4px 10px;
    font-size: 11px; font-weight: 600;
}
#SearchEngine::drop-down, #WorkspaceCombo::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 22px; border: none; background: transparent; }
#SearchEngine::down-arrow, #WorkspaceCombo::down-arrow { width: 10px; height: 10px; }

/* ---------- lists ---------- */
#CafeList, #TabList { background-color: transparent; border: none; outline: none; }
#CafeList::item, #TabList::item {
    background-color: transparent; border-radius: %(RADIUS_SM)s;
    padding: 5px 8px; margin: 2px 2px; border-left: 3px solid transparent; color: %(TEXT_MUTED)s;
}
#CafeList::item:hover, #TabList::item:hover { background-color: %(ITEM_HOVER)s; color: %(TEXT)s; }
#CafeList::item:selected, #TabList::item:selected {
    background-color: %(ITEM_SELECTED)s; color: %(TEXT)s; border-left-color: %(ACCENT)s;
}

/* ---------- browser sidebar ---------- */
#Sidebar { background-color: %(SIDEBAR_BG)s; border-right: 1px solid %(BORDER_SOFT)s; }
#AppTitle { color: %(TEXT)s; font-size: 13px; font-weight: 700; }
#TabCounter, #ZoomLabel { color: %(TEXT_MUTED)s; font-size: 11px; }
#NewTabBtn {
    background-color: %(ACCENT_SOFT)s; color: %(ACCENT_HOVER)s; border: 1px solid %(INPUT_BORDER)s;
    border-radius: %(RADIUS_SM)s; padding: 9px 10px; font-weight: 700;
}
#NewTabBtn:hover { background-color: %(ITEM_SELECTED)s; border-color: %(ACCENT)s; }

#SidebarPanelBtn, #TopBar QToolButton {
    background-color: transparent; color: %(TEXT_MUTED)s; border: none;
    border-radius: %(RADIUS_SM)s; padding: 5px 9px; min-width: 28px; min-height: 28px; font-size: 10px; font-weight: 700;
}
#SidebarPanelBtn:hover, #TopBar QToolButton:hover { background-color: %(ITEM_HOVER)s; color: %(TEXT)s; }
#SidebarPanelBtn:checked { color: %(ACCENT_HOVER)s; background-color: %(ITEM_SELECTED)s; border: 1px solid %(ITEM_SELECTED_BORDER)s; }

#TopIconButton {
    background-color: %(BUTTON_BG)s; color: %(TEXT)s; border: 1px solid %(INPUT_BORDER)s;
    border-radius: %(RADIUS_SM)s; min-width: 30px; min-height: 30px; padding: 3px 6px; font-weight: 700; font-size: 10px;
}
#TopIconButton:hover { background-color: %(BUTTON_HOVER)s; border-color: %(ACCENT)s; }

/* ---------- menus ---------- */
QMenu {
    background-color: %(MENU_BG)s; color: %(TEXT)s;
    border: 1px solid %(INPUT_BORDER)s; padding: 5px; border-radius: %(RADIUS_SM)s;
}
QMenu::item { padding: 6px 12px; border-radius: 6px; margin: 1px 0; }
QMenu::item:selected { background-color: %(MENU_ITEM_SEL)s; color: %(TEXT)s; }
QMenu::item:disabled { color: %(TEXT_DIM)s; }
QMenu::separator { height: 1px; background: %(BORDER_SOFT)s; margin: 5px 7px; }

/* ---------- checkboxes / radios ---------- */
QCheckBox, QRadioButton { color: %(TEXT_MUTED)s; spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid %(INPUT_BORDER)s; background: %(INPUT_BG)s;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(ACCENT)s; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: %(ACCENT)s;
    border-color: %(ACCENT)s;
}
QRadioButton::indicator:checked { border: 5px solid %(ACCENT)s; background: %(INPUT_BG)s; }
/* A visible check mark: solid accent fill alone read as a disabled box. */
QCheckBox:checked { color: %(TEXT)s; font-weight: 600; }

/* ---------- progress / slider ---------- */
QProgressBar {
    border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s; background: %(MAIN_BG_ALT)s; text-align: center;
}
QProgressBar::chunk { background-color: %(ACCENT)s; border-radius: %(RADIUS_SM)s; }

/* ---------- splitter / tooltip ---------- */
#ShellTopBar QSplitter::handle, QSplitter::handle { background-color: %(BORDER_SOFT)s; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical { height: 3px; }
QToolTip {
    background-color: %(MENU_BG)s; color: %(TEXT)s;
    border: 1px solid %(ACCENT)s; border-radius: %(RADIUS_SM)s; padding: 6px 10px;
}

/* ---------- header group boxes ---------- */
QGroupBox {
    border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s; margin-top: 10px; padding-top: 8px;
    color: %(TEXT)s; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; color: %(ACCENT_HOVER)s; }

/* ---------- scrollbars: translucent rounded ---------- */
QScrollBar:vertical {
    width: 9px; margin: 2px; background: transparent; border-radius: 4px;
}
QScrollBar::handle:vertical {
    min-height: 26px; background: %(INPUT_BORDER)s; border-radius: 4px; margin: 1px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:press { background: %(ACCENT)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    height: 9px; margin: 2px; background: transparent; border-radius: 4px;
}
QScrollBar::handle:horizontal {
    min-width: 26px; background: %(INPUT_BORDER)s; border-radius: 4px; margin: 1px;
}
QScrollBar::handle:horizontal:hover, QScrollBar::handle:horizontal:press { background: %(ACCENT)s; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ---------- 2026 coffee-house interface refresh ----------
   The rules below deliberately sit at the end of the sheet: a single visual
   language reaches the shell, browser chrome, dashboard, workspaces, and
   standalone windows without making each screen maintain its own palette. */
QMainWindow, QWidget {
    font-family: %(FONT_FAMILY)s;
    background-color: %(MAIN_BG)s;
    color: %(TEXT)s;
}
/* Labels sit directly on their parent surface.  Only named badges/glyphs
   below intentionally paint a background. */
QLabel {
    background-color: transparent;
    border: none;
}

#ShellRoot, #MainWidget, #ContentArea, #HomeDashboard, #SettingsContent,
#AIWorkspace, #PersonalWorkspace, #LibraryWorkspace, #SettingsWorkspace, #HistoryWorkspace {
    background-color: %(MAIN_BG)s;
}

#ShellTopBar {
    min-height: 50px;
    background-color: %(CARD_BG)s;
    border: none;
    border-bottom: 1px solid %(BORDER_SOFT)s;
    padding: 7px 14px;
}
#BrandWrap { background: transparent; }
#BrandGlyph {
    color: %(ACCENT_HOVER)s;
    min-width: 30px;
    min-height: 30px;
    qproperty-alignment: AlignCenter;
    background-color: %(ACCENT_SOFT)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 15px;
    font-size: 17px;
}
#BrandName {
    color: %(TEXT)s;
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.7px;
}
#BrandSub {
    color: %(TEXT_MUTED)s;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.3px;
    text-transform: uppercase;
}
#ShellOmnibar {
    min-height: 34px;
    padding: 6px 12px;
    border-radius: 17px;
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    font-size: 12px;
}
#ShellOmnibar:focus {
    background-color: %(CARD_BG)s;
    border: 1px solid %(ACCENT)s;
}

#LeftRail, #Sidebar {
    background-color: %(SIDEBAR_BG)s;
    border: none;
    border-right: 1px solid %(SIDEBAR_BORDER)s;
}
#RailSectionLabel {
    color: %(TEXT_MUTED)s;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1.35px;
    padding: 12px 10px 2px 10px;
}
#RailMeta {
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 10px;
    color: %(TEXT_MUTED)s;
    font-size: 10px;
    padding: 7px 9px;
}
#NavButton {
    min-height: 34px;
    text-align: left;
    color: %(TEXT_MUTED)s;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 7px 10px;
    font-size: 12px;
    font-weight: 650;
}
#NavButton:hover {
    color: %(TEXT)s;
    background-color: %(ITEM_HOVER)s;
    border-color: %(BORDER_SOFT)s;
}
#NavButton:checked {
    color: %(ACCENT_HOVER)s;
    background-color: %(ACCENT_SOFT)s;
    border-color: %(INPUT_BORDER)s;
}

#StatusStrip {
    min-height: 28px;
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 10px;
    padding: 3px 8px;
}
#StatusPill {
    background-color: %(ACCENT_SOFT)s;
    color: %(ACCENT_HOVER)s;
    border: none;
    border-radius: 9px;
    padding: 4px 9px;
    font-size: 10px;
    font-weight: 800;
}

#InsightPanel {
    margin: 4px 4px 4px 0;
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 16px;
}
#InsightPanel #SectionCard {
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 12px;
}

#PageHeader { background: transparent; }
#PageGlyph {
    min-width: 26px;
    min-height: 26px;
    qproperty-alignment: AlignCenter;
    color: %(ACCENT_HOVER)s;
    background-color: %(ACCENT_SOFT)s;
    border-radius: 13px;
    font-size: 14px;
}
#PageTitle {
    color: %(TEXT)s;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.1px;
}
#PageSubtitle, #MutedLabel { color: %(TEXT_MUTED)s; font-size: 11px; }
#SectionTitle {
    color: %(TEXT)s;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.15px;
    text-transform: none;
}

#HeroCard {
    background-color: %(CARD_BG)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 18px;
}
#HeroTitle {
    color: %(TEXT)s;
    font-family: %(TITLE_FONT)s;
    font-size: 27px;
    font-weight: 700;
}
#HeroSubtitle { color: %(TEXT_MUTED)s; font-size: 12px; }
#HeroBadge, #Badge, #BadgeAccent {
    border-radius: 12px;
    padding: 4px 9px;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.7px;
}
#HeroBadge, #BadgeAccent {
    background-color: %(ACCENT_SOFT)s;
    color: %(ACCENT_HOVER)s;
    border: 1px solid %(INPUT_BORDER)s;
}
#Badge {
    background-color: %(MAIN_BG_ALT)s;
    color: %(TEXT_MUTED)s;
    border: 1px solid %(BORDER_SOFT)s;
}

#SectionCard, #StatCard {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 15px;
}
#SectionCard:hover, #StatCard:hover { border-color: %(INPUT_BORDER)s; }
#StatTile {
    min-height: 68px;
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 14px;
}
#StatTile:hover { border-color: %(ACCENT)s; background-color: %(ITEM_HOVER)s; }
#StatValue { color: %(ACCENT_HOVER)s; font-size: 21px; font-weight: 800; }
#StatLabel { color: %(TEXT_MUTED)s; font-size: 10px; }

#ActionTile {
    min-height: 88px;
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 14px;
    padding: 8px;
}
#ActionTile:hover {
    background-color: %(ACCENT_SOFT)s;
    border-color: %(ACCENT)s;
}
#ActionTile:pressed { background-color: %(ITEM_SELECTED)s; }
#ActionGlyph { color: %(ACCENT_HOVER)s; font-size: 21px; }
#ActionLabel { color: %(TEXT)s; font-size: 12px; font-weight: 800; }
#ActionHint { color: %(TEXT_MUTED)s; font-size: 9px; }

#Chip {
    min-height: 22px;
    background-color: %(MAIN_BG_ALT)s;
    color: %(TEXT_MUTED)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 11px;
    padding: 3px 10px;
    font-size: 10px;
    font-weight: 700;
}
#Chip:hover { color: %(TEXT)s; border-color: %(INPUT_BORDER)s; background-color: %(ITEM_HOVER)s; }
#Chip:checked { color: %(ACCENT_HOVER)s; background-color: %(ACCENT_SOFT)s; border-color: %(ACCENT)s; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    min-height: 24px;
    background-color: %(INPUT_BG)s;
    color: %(TEXT)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 9px;
    padding: 5px 9px;
    selection-background-color: %(ACCENT_SOFT)s;
}
QTextEdit, QPlainTextEdit { padding: 8px; }
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: %(ACCENT)s; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    background-color: %(CARD_BG)s;
    border-color: %(INPUT_FOCUS)s;
}

QPushButton, #CafeButton, #TopIconButton {
    min-height: 24px;
    color: %(BUTTON_TEXT)s;
    background-color: %(BUTTON_BG)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 9px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton:hover, #CafeButton:hover, #TopIconButton:hover {
    background-color: %(BUTTON_HOVER)s;
    border-color: %(ACCENT)s;
}
QPushButton#TopAccentButton {
    min-height: 26px;
    background-color: %(ACCENT)s;
    color: %(MAIN_BG)s;
    border: 1px solid %(ACCENT)s;
    border-radius: 9px;
    font-weight: 800;
}
QPushButton#TopAccentButton:hover { background-color: %(ACCENT_HOVER)s; border-color: %(ACCENT_HOVER)s; }

#CafeList, #TabList, QTreeWidget {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 2px;
}
#CafeList::item, #TabList::item, QTreeWidget::item {
    color: %(TEXT_MUTED)s;
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    margin: 2px;
    padding: 7px 8px;
}
#CafeList::item:hover, #TabList::item:hover, QTreeWidget::item:hover {
    color: %(TEXT)s;
    background-color: %(ITEM_HOVER)s;
    border-color: %(BORDER_SOFT)s;
}
#CafeList::item:selected, #TabList::item:selected, QTreeWidget::item:selected {
    color: %(TEXT)s;
    background-color: %(ACCENT_SOFT)s;
    border-color: %(INPUT_BORDER)s;
}

/* Browser surface: a quiet control deck around the live webpage. */
#Sidebar { background-color: %(SIDEBAR_BG)s; }
#SidebarFooter { background-color: transparent; }
#TabCounter, #ZoomLabel { color: %(TEXT_MUTED)s; font-size: 10px; }
#WorkspaceCombo, #SearchEngine {
    min-height: 28px;
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 9px;
    padding: 4px 22px 4px 9px;
    font-size: 10px;
    font-weight: 700;
}
#NewTabBtn {
    min-height: 30px;
    background-color: %(ACCENT_SOFT)s;
    color: %(ACCENT_HOVER)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 10px;
    padding: 6px 10px;
    font-weight: 800;
}
#NewTabBtn:hover { background-color: %(ITEM_SELECTED)s; border-color: %(ACCENT)s; }
#SidebarPanelBtn, #TopBar QToolButton, #TopIconButton {
    min-width: 28px;
    min-height: 28px;
    background-color: transparent;
    color: %(TEXT_MUTED)s;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 4px 6px;
    font-weight: 800;
}
#SidebarPanelBtn:hover, #TopBar QToolButton:hover, #TopIconButton:hover {
    color: %(TEXT)s;
    background-color: %(ITEM_HOVER)s;
    border-color: %(BORDER_SOFT)s;
}
#SidebarPanelBtn:checked { color: %(ACCENT_HOVER)s; background-color: %(ACCENT_SOFT)s; border-color: %(INPUT_BORDER)s; }
#TopBar {
    min-height: 42px;
    margin: 2px;
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 14px;
    padding: 3px;
}
#AddressHint {
    color: %(ACCENT_HOVER)s;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.8px;
    padding: 0 4px;
}
#UrlBar {
    min-height: 28px;
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 11px;
    padding: 5px 10px;
    font-weight: 600;
}
#UrlBar:focus { background-color: %(INPUT_BG)s; border-color: %(INPUT_FOCUS)s; }
#WebContainer { background-color: %(MAIN_BG)s; border: none; }
#TabFilter {
    min-height: 28px;
    margin: 0 2px 5px 2px;
    background-color: %(MAIN_BG_ALT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 10px;
    padding: 5px 9px;
    font-size: 10px;
}
#DormantTabView {
    background-color: %(MAIN_BG)s;
    border: 1px dashed %(BORDER_SOFT)s;
    border-radius: 14px;
}

QGroupBox {
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 12px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    color: %(TEXT)s;
    font-weight: 700;
}
QGroupBox::title { color: %(ACCENT_HOVER)s; padding: 0 6px; }
QTableView, QTreeView {
    background-color: %(CARD_BG)s;
    color: %(TEXT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 10px;
    gridline-color: %(BORDER_SOFT)s;
}
QHeaderView::section {
    background-color: %(MAIN_BG_ALT)s;
    color: %(TEXT_MUTED)s;
    border: none;
    border-bottom: 1px solid %(BORDER_SOFT)s;
    padding: 6px;
    font-size: 10px;
    font-weight: 800;
}
QMenu {
    background-color: %(MENU_BG)s;
    color: %(TEXT)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 11px;
    padding: 5px;
}
QMenu::item { padding: 7px 20px 7px 10px; border-radius: 7px; }
QMenu::item:selected { background-color: %(ACCENT_SOFT)s; color: %(TEXT)s; }

/* ---------- 5.6 coffee-house refinement: softer radii + gentle focus ---------- */
QPushButton, #CafeButton, #TopIconButton { border-radius: 10px; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { border-radius: 10px; }
#HeroCard { border-radius: 20px; }
#SectionCard, #StatCard, #ActionTile, #StatTile { border-radius: 16px; }
#ShellOmnibar { border-radius: 18px; }
#UrlBar { border-radius: 12px; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus,
#UrlBar:focus, #ShellOmnibar:focus {
    border: 1px solid %(ACCENT)s;
}

/* ---------- 5.7 browser control deck: one calm, unified toolbar ---------- */
#TopIconButton { font-size: 13px; font-weight: 700; }
#SidebarPanelBtn {
    min-width: 34px; min-height: 32px;
    font-size: 15px;
    border-radius: 10px;
}
#SidebarPanelBtn:hover { background-color: %(ITEM_HOVER)s; border-color: %(BORDER_SOFT)s; color: %(TEXT)s; }
#SidebarPanelBtn:checked {
    background-color: %(ACCENT_SOFT)s;
    border-color: %(INPUT_BORDER)s;
    color: %(ACCENT_HOVER)s;
}
#NewTabBtn { min-height: 32px; border-radius: 10px; }
#OptionsBtn {
    min-height: 32px;
    background-color: %(BUTTON_BG)s;
    color: %(TEXT_MUTED)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 10px;
    padding: 5px 12px;
    font-weight: 700;
}
#OptionsBtn:hover { background-color: %(BUTTON_HOVER)s; border-color: %(ACCENT)s; color: %(TEXT)s; }
#TabList::item:selected { border-left: 3px solid %(ACCENT)s; }
#TabCounter { color: %(TEXT_MUTED)s; font-size: 10px; font-weight: 700; letter-spacing: 0.4px; }

/* ---------- 6.5 final visual polish ----------
   Focus rings, hover lifts, dialog buttons and the floating helpers
   (find bar / toast) follow the theme instead of hard-coded colors. */

/* Primary action pop: accent-filled primary buttons stand out on cards. */
QPushButton#TopAccentButton { padding: 6px 14px; }

/* Softer, consistent item selection everywhere (lists, trees, combo popups). */
QListWidget::item:selected, QTreeWidget::item:selected, QComboBox QAbstractItemView::item:selected {
    background-color: %(ITEM_SELECTED)s;
    color: %(TEXT)s;
    border-radius: 8px;
}

/* Tab rows: clearer active state with the accent bar + filled chip. */
#TabList::item:selected {
    background-color: %(ACCENT_SOFT)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-left: 3px solid %(ACCENT)s;
    color: %(TEXT)s;
    font-weight: 700;
}

/* Combo popup rows mirror list rows. */
QComboBox QAbstractItemView { outline: none; }
QComboBox QAbstractItemView::item { min-height: 24px; padding: 4px 8px; border-radius: 6px; }

/* Tooltips: slightly larger padding, softer border. */
QToolTip {
    border: 1px solid %(INPUT_BORDER)s;
    background-color: %(MENU_BG)s;
    color: %(TEXT)s;
    padding: 6px 10px;
    border-radius: 8px;
}

/* Floating helpers styled by the shell, not hard-coded. */
#FindBar {
    background-color: %(CARD_BG)s;
    border: 1px solid %(INPUT_BORDER)s;
    border-radius: 10px;
}
#FindBar QLineEdit {
    background-color: %(INPUT_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 8px;
}
#FindBar QLineEdit:focus { border-color: %(ACCENT)s; }
#ToastLabel {
    background-color: %(MENU_BG)s;
    color: %(TEXT)s;
    border: 1px solid %(ACCENT)s;
    border-radius: 12px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 600;
}
/* Chrome-style thin page-load bar under the toolbar. */
#LoadProgress {
    background: transparent;
    border: none;
    max-height: 3px;
    margin: 0;
}
#LoadProgress::chunk {
    background-color: %(ACCENT)s;
    border-radius: 1px;
}
/* Opera GX-style web panel dock beside the page. */
#WebPanelDock {
    background-color: %(CARD_BG)s;
    border-left: 1px solid %(BORDER_SOFT)s;
}
#WebPanelHeader {
    background-color: %(MAIN_BG_ALT)s;
    border-bottom: 1px solid %(BORDER_SOFT)s;
}
#WebPanelView {
    background-color: %(MAIN_BG)s;
}
/* Chrome-style save-password prompt bar. */
#SavePasswordBar {
    background-color: %(ACCENT_SOFT)s;
    border-top: 1px solid %(ACCENT)s;
}
/* Edge-Copilot-style AI sidebar dock. */
#AISideDock {
    background-color: %(CARD_BG)s;
    border-left: 1px solid %(BORDER_SOFT)s;
}
""" % p


def dialog_qss(mode: str = "cafe-night", accent: str | None = None):
    """Stylesheet shared by all modal dialogs — consistent with the modern main shell."""
    p = _palette(mode, accent)
    return """
    QDialog {
        background-color: %(MAIN_BG)s; color: %(TEXT)s; font-size: 13px;
    }
    QLabel { color: %(TEXT)s; font-size: 13px; }
    QLabel#MutedLabel { color: %(TEXT_MUTED)s; font-size: 11px; }
    QPushButton {
        background-color: %(BUTTON_BG)s; color: %(BUTTON_TEXT)s;
        border: 1px solid %(INPUT_BORDER)s; border-radius: %(RADIUS_SM)s;
        padding: 6px 12px; font-size: 13px; font-weight: 600;
    }
    QPushButton:hover { background-color: %(BUTTON_HOVER)s; border-color: %(ACCENT)s; }
    QPushButton:pressed { background-color: %(ITEM_SELECTED)s; }
    QPushButton:disabled { color: %(TEXT_DIM)s; background-color: %(MAIN_BG_ALT)s; border-color: %(BORDER_SOFT)s; }
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
        background-color: %(INPUT_BG)s; color: %(TEXT)s;
        border: 1px solid %(INPUT_BORDER)s; border-radius: %(RADIUS_SM)s;
        padding: 5px 9px; font-size: 13px; selection-background-color: %(MENU_ITEM_SEL)s;
        selection-color: %(TEXT)s;
    }
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover { border-color: %(ACCENT)s; }
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: %(INPUT_FOCUS)s; }
    QListWidget, QTreeWidget {
        background-color: %(CARD_BG)s; color: %(TEXT)s;
        border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s; padding: 4px; font-size: 13px;
    }
    QListWidget::item, QTreeWidget::item { padding: 6px 7px; border-radius: 6px; }
    QListWidget::item:hover, QTreeWidget::item:hover { background-color: %(ITEM_HOVER)s; border-radius: 6px; }
    QListWidget::item:selected, QTreeWidget::item:selected { background-color: %(MENU_ITEM_SEL)s; color: %(TEXT)s; border-radius: 6px; }
    QCheckBox, QRadioButton { color: %(TEXT_MUTED)s; spacing: 8px; }
    QCheckBox::indicator, QRadioButton::indicator {
        width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid %(INPUT_BORDER)s; background: %(INPUT_BG)s;
    }
    QRadioButton::indicator { border-radius: 8px; }
    QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(ACCENT)s; }
    QCheckBox::indicator:checked { background: %(ACCENT)s; border-color: %(ACCENT)s; }
    QRadioButton::indicator:checked { border: 5px solid %(ACCENT)s; background: %(INPUT_BG)s; }
    QComboBox QAbstractItemView {
        background-color: %(MENU_BG)s; color: %(TEXT)s;
        border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s;
        selection-background-color: %(MENU_ITEM_SEL)s; selection-color: %(TEXT)s;
    }
    QGroupBox {
        border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s; margin-top: 10px; padding-top: 8px;
    }
    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; color: %(ACCENT_HOVER)s; }

    /* shared components */
    #PageHeader { background: transparent; }
    #PageGlyph { color: %(ACCENT_HOVER)s; font-size: 20px; }
    #PageTitle { color: %(TEXT)s; }
    #PageSubtitle { color: %(TEXT_MUTED)s; font-size: 11px; }
    #StatTile { background-color: %(CARD_BG)s; border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s; }
    #StatValue { color: %(ACCENT_HOVER)s; }
    #StatLabel { color: %(TEXT_MUTED)s; font-size: 11px; }
    #SectionHeaderRow { background: transparent; }
    #EmptyState { background-color: %(CARD_BG)s; border: 1px dashed %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s; }
    #EmptyGlyph { color: %(ACCENT_SOFT)s; font-size: 26px; }
    #ActionTile { background-color: %(CARD_BG)s; border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS)s; padding: 6px; }
    #ActionTile:hover { border-color: %(ACCENT)s; background-color: %(ITEM_HOVER)s; }
    #ActionGlyph { color: %(ACCENT_HOVER)s; font-size: 22px; }
    #ActionLabel { color: %(TEXT)s; font-weight: 700; }
    #Chip { background-color: %(MAIN_BG_ALT)s; color: %(TEXT_MUTED)s; border: 1px solid %(BORDER_SOFT)s; border-radius: 999px; padding: 5px 13px; font-size: 11px; font-weight: 600; }
    #Chip:hover { border-color: %(ACCENT)s; color: %(TEXT)s; }
    #Chip:checked { background-color: %(ACCENT_SOFT)s; color: %(ACCENT_HOVER)s; border-color: %(ACCENT)s; }
    #Badge { background-color: %(MAIN_BG_ALT)s; color: %(TEXT_MUTED)s; border: 1px solid %(BORDER_SOFT)s; border-radius: 999px; padding: 2px 10px; font-size: 10px; font-weight: 700; }
    #BadgeAccent { background-color: %(ACCENT_SOFT)s; color: %(ACCENT_HOVER)s; border: 1px solid %(INPUT_BORDER)s; border-radius: 999px; padding: 2px 10px; font-size: 10px; font-weight: 800; }

    /* Dialogs use the same paper-card rhythm as the full workspace. */
    QDialog { background-color: %(MAIN_BG)s; }
    QDialog QWidget { font-family: %(FONT_FAMILY)s; }
    QPushButton { min-height: 25px; border-radius: 9px; padding: 5px 11px; }
    /* The dialog's default action (QMessageBox Yes/OK) pops with the accent. */
    QPushButton:default {
        background-color: %(ACCENT)s;
        color: %(MAIN_BG)s;
        border-color: %(ACCENT)s;
        font-weight: 800;
    }
    QPushButton:default:hover { background-color: %(ACCENT_HOVER)s; border-color: %(ACCENT_HOVER)s; }
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { min-height: 24px; border-radius: 9px; }
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: %(ACCENT)s; }
    QListWidget, QTreeWidget { background-color: %(CARD_BG)s; border: 1px solid %(BORDER_SOFT)s; border-radius: 12px; padding: 3px; }
    QListWidget::item, QTreeWidget::item { border-radius: 8px; padding: 7px; }
    QListWidget::item:selected, QTreeWidget::item:selected {
        background-color: %(ITEM_SELECTED)s; color: %(TEXT)s; border-left: 3px solid %(ACCENT)s;
    }
    QGroupBox { background-color: %(CARD_BG)s; border-radius: 12px; padding: 11px 9px 9px 9px; }
    QToolTip {
        background-color: %(MENU_BG)s; color: %(TEXT)s;
        border: 1px solid %(INPUT_BORDER)s; border-radius: 8px; padding: 6px 10px;
    }
    """ % p


def dynamic_main_widget_css(mode: str, phase: int, accent: str | None = None) -> str:
    """Subtle shifting gradient on #MainWidget when user enables dynamic background."""
    p = _palette(mode, accent)
    a, b = (p["MAIN_BG"], p["MAIN_BG_ALT"]) if (phase % 2) == 0 else (p["MAIN_BG_ALT"], p["MAIN_BG"])
    return (
        "#MainWidget {\n"
        "  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 %(a)s, stop:1 %(b)s);\n"
        "}"
        % {"a": a, "b": b}
    )


def collapse_btn_qss(mode: str = "cafe-night", accent: str | None = None):
    p = _palette(mode, accent)
    return """
    QToolButton {
        background: transparent; color: %(TEXT_MUTED)s; border: none;
        border-radius: 6px; min-width: 26px; min-height: 26px; font-size: 11px;
    }
    QToolButton:hover { color: %(ACCENT_HOVER)s; background: %(ITEM_HOVER)s; }
    """ % p


def animate_entrance(widget, duration: int = 160) -> None:
    """Qt-native micro-transition; QSS has no reliable transition support."""
    if widget is None or not widget.isVisible() or widget.graphicsEffect() is not None:
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)

    def _cleanup():
        # The widget can be destroyed before the 160 ms animation lands
        # (workspace switch/teardown); touching a deleted C++ object would
        # raise inside the signal handler (v6.4 bug).
        try:
            if widget.graphicsEffect() is effect:
                widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    animation.finished.connect(_cleanup)
    widget._cafe_entrance_animation = animation  # retain animation for Qt's async lifetime.
    animation.start()



