from PyQt5.QtCore import QEasingCurve, QPropertyAnimation
from PyQt5.QtWidgets import QGraphicsOpacityEffect

PALETTES = {
    # ============================ LIGHT — day café ============================
    "minimal": {
        # Latte Cream (default): warm paper white, espresso ink, rich caramel.
        # The calm all-day café — bright but never clinical.
        "MAIN_BG": "#FAF6EF",
        "MAIN_BG_ALT": "#F2EBDD",
        "SIDEBAR_BG": "#F4EEE2",
        "SIDEBAR_BORDER": "#E3D8C4",
        "CARD_BG": "#FFFDF8",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#D9CBB2",
        "INPUT_FOCUS": "#B0793F",
        "TEXT": "#292016",
        "TEXT_MUTED": "#7A6952",
        "ACCENT": "#A66A2E",
        "ACCENT_HOVER": "#C07E3C",
        "ACCENT_SOFT": "#F5E5CE",
        "ITEM_HOVER": "#F4EBDB",
        "ITEM_SELECTED": "#EEDFC3",
        "ITEM_SELECTED_BORDER": "#A66A2E",
        "BUTTON_BG": "#F3EADC",
        "BUTTON_HOVER": "#EADCC6",
        "BUTTON_TEXT": "#292016",
        "MENU_BG": "#FFFDF8",
        "MENU_ITEM_SEL": "#F0E1C6",
        "BORDER_SOFT": "#EAE0CC",
        "DANGER": "#C04A36",
        "SUCCESS": "#57803E",
    },
    "latte": {
        # Honey Crème: golden, sunlit honey tones — a warmer, sweeter café.
        "MAIN_BG": "#FCF7EC",
        "MAIN_BG_ALT": "#F5EBD6",
        "SIDEBAR_BG": "#F8F0DE",
        "SIDEBAR_BORDER": "#E7D8B8",
        "CARD_BG": "#FFFEF8",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#DECFA8",
        "INPUT_FOCUS": "#A87B2A",
        "TEXT": "#2F2513",
        "TEXT_MUTED": "#7E6B48",
        "ACCENT": "#B4832A",
        "ACCENT_HOVER": "#CC9938",
        "ACCENT_SOFT": "#F7E9C8",
        "ITEM_HOVER": "#F6EDD8",
        "ITEM_SELECTED": "#F0E2BC",
        "ITEM_SELECTED_BORDER": "#B4832A",
        "BUTTON_BG": "#F5ECD6",
        "BUTTON_HOVER": "#ECDFC2",
        "BUTTON_TEXT": "#2F2513",
        "MENU_BG": "#FFFEF8",
        "MENU_ITEM_SEL": "#F1E3C0",
        "BORDER_SOFT": "#EDE1C6",
        "DANGER": "#BF4E33",
        "SUCCESS": "#6A8434",
    },
    "rose-day": {
        # Sakura Café: rose-latte pinks — soft, airy, a little playful.
        "MAIN_BG": "#FCF5F4",
        "MAIN_BG_ALT": "#F5E7E6",
        "SIDEBAR_BG": "#F8EDEC",
        "SIDEBAR_BORDER": "#E7CBCA",
        "CARD_BG": "#FFFCFC",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#E5C8C6",
        "INPUT_FOCUS": "#C14E5E",
        "TEXT": "#331F24",
        "TEXT_MUTED": "#8A6570",
        "ACCENT": "#C14E5E",
        "ACCENT_HOVER": "#DB6577",
        "ACCENT_SOFT": "#F9E0E2",
        "ITEM_HOVER": "#F8ECEB",
        "ITEM_SELECTED": "#F4DCDD",
        "ITEM_SELECTED_BORDER": "#C14E5E",
        "BUTTON_BG": "#F8ECEA",
        "BUTTON_HOVER": "#F1DEDB",
        "BUTTON_TEXT": "#331F24",
        "MENU_BG": "#FFFCFC",
        "MENU_ITEM_SEL": "#F5DEDF",
        "BORDER_SOFT": "#EFD9D7",
        "DANGER": "#B93A4A",
        "SUCCESS": "#5F8A50",
    },
    "dawn": {
        # Café Dawn: peachy first-light — terracotta warmth on cream porcelain.
        "MAIN_BG": "#FDF6EF",
        "MAIN_BG_ALT": "#F9ECDF",
        "SIDEBAR_BG": "#FBF0E4",
        "SIDEBAR_BORDER": "#EFD6BE",
        "CARD_BG": "#FFFDFA",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#E8CDB2",
        "INPUT_FOCUS": "#C56A3A",
        "TEXT": "#33241A",
        "TEXT_MUTED": "#83644E",
        "ACCENT": "#C76B35",
        "ACCENT_HOVER": "#E08148",
        "ACCENT_SOFT": "#FBE7D2",
        "ITEM_HOVER": "#F9EEE0",
        "ITEM_SELECTED": "#F4DFC6",
        "ITEM_SELECTED_BORDER": "#C76B35",
        "BUTTON_BG": "#F8EFE2",
        "BUTTON_HOVER": "#F1E3CF",
        "BUTTON_TEXT": "#33241A",
        "MENU_BG": "#FFFDFA",
        "MENU_ITEM_SEL": "#F4E2CC",
        "BORDER_SOFT": "#F0E2CE",
        "DANGER": "#BC4436",
        "SUCCESS": "#5F8A4E",
    },
    "matcha-day": {
        # Matcha Latte: whisked-green freshness over rice-paper cream.
        "MAIN_BG": "#F8F9F0",
        "MAIN_BG_ALT": "#EFF2E2",
        "SIDEBAR_BG": "#F2F5E7",
        "SIDEBAR_BORDER": "#D9E0C2",
        "CARD_BG": "#FCFDF7",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#D2D9B8",
        "INPUT_FOCUS": "#5E7F3E",
        "TEXT": "#262A1B",
        "TEXT_MUTED": "#61694C",
        "ACCENT": "#6E9440",
        "ACCENT_HOVER": "#86AC52",
        "ACCENT_SOFT": "#E7EFCE",
        "ITEM_HOVER": "#EFF3E0",
        "ITEM_SELECTED": "#E3EBC8",
        "ITEM_SELECTED_BORDER": "#6E9440",
        "BUTTON_BG": "#F0F4E2",
        "BUTTON_HOVER": "#E5ECCE",
        "BUTTON_TEXT": "#262A1B",
        "MENU_BG": "#FCFDF7",
        "MENU_ITEM_SEL": "#E9F0D2",
        "BORDER_SOFT": "#E3E8D0",
        "DANGER": "#B8503E",
        "SUCCESS": "#55803C",
    },
    "sand-day": {
        # Morning Crème: cool porcelain cream with a slate-mocha accent — the
        # most neutral, office-friendly light theme.
        "MAIN_BG": "#F6F3EC",
        "MAIN_BG_ALT": "#ECE7DC",
        "SIDEBAR_BG": "#EFEAE0",
        "SIDEBAR_BORDER": "#D4CBB6",
        "CARD_BG": "#FCFAF4",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#D6CCB6",
        "INPUT_FOCUS": "#7A6248",
        "TEXT": "#2B2620",
        "TEXT_MUTED": "#726A5B",
        "ACCENT": "#8C6D46",
        "ACCENT_HOVER": "#A58052",
        "ACCENT_SOFT": "#EDE4D0",
        "ITEM_HOVER": "#EFE9DB",
        "ITEM_SELECTED": "#E7DCC4",
        "ITEM_SELECTED_BORDER": "#8C6D46",
        "BUTTON_BG": "#F1EBDD",
        "BUTTON_HOVER": "#E5DCCA",
        "BUTTON_TEXT": "#2B2620",
        "MENU_BG": "#FCFAF4",
        "MENU_ITEM_SEL": "#EDE3CC",
        "BORDER_SOFT": "#E6DECB",
        "DANGER": "#BC4A38",
        "SUCCESS": "#5F8348",
    },
    # ============================ DARK — night café ===========================
    "cafe-night": {
        # Espresso House: deep roasted espresso wood, glowing amber lamps.
        "MAIN_BG": "#14100B",
        "MAIN_BG_ALT": "#1B150D",
        "SIDEBAR_BG": "#171208",
        "SIDEBAR_BORDER": "#332614",
        "CARD_BG": "#1F1810",
        "INPUT_BG": "#241C11",
        "INPUT_BORDER": "#4A3820",
        "INPUT_FOCUS": "#E5B763",
        "TEXT": "#F7EDD9",
        "TEXT_MUTED": "#BCA988",
        "ACCENT": "#D9A94F",
        "ACCENT_HOVER": "#F0C168",
        "ACCENT_SOFT": "#43301A",
        "ITEM_HOVER": "#2B2113",
        "ITEM_SELECTED": "#46331A",
        "ITEM_SELECTED_BORDER": "#F0C168",
        "BUTTON_BG": "#2E2314",
        "BUTTON_HOVER": "#3B2C19",
        "BUTTON_TEXT": "#F7EDD9",
        "MENU_BG": "#1F1810",
        "MENU_ITEM_SEL": "#51391C",
        "BORDER_SOFT": "#2B2010",
        "DANGER": "#E57463",
        "SUCCESS": "#97AE6C",
    },
    "minimal-night": {
        # Midnight Mocha: chocolate-dark surfaces, latte-foam gold accents —
        # the night sibling of the default latte theme.
        "MAIN_BG": "#1A1411",
        "MAIN_BG_ALT": "#241C17",
        "SIDEBAR_BG": "#1E1713",
        "SIDEBAR_BORDER": "#382C22",
        "CARD_BG": "#231B15",
        "INPUT_BG": "#272018",
        "INPUT_BORDER": "#443527",
        "INPUT_FOCUS": "#E2BE93",
        "TEXT": "#F6ECDC",
        "TEXT_MUTED": "#B09C85",
        "ACCENT": "#D4A96C",
        "ACCENT_HOVER": "#EAC282",
        "ACCENT_SOFT": "#33261A",
        "ITEM_HOVER": "#2C231A",
        "ITEM_SELECTED": "#42301C",
        "ITEM_SELECTED_BORDER": "#EAC282",
        "BUTTON_BG": "#2C231A",
        "BUTTON_HOVER": "#392D20",
        "BUTTON_TEXT": "#F6ECDC",
        "MENU_BG": "#241D16",
        "MENU_ITEM_SEL": "#4B3520",
        "BORDER_SOFT": "#382C22",
        "DANGER": "#E07E67",
        "SUCCESS": "#97AE6C",
    },
    "ocean-night": {
        # Café Azul: deep blue-slate night with a luminous teal counter.
        "MAIN_BG": "#0D1219",
        "MAIN_BG_ALT": "#131B26",
        "SIDEBAR_BG": "#101721",
        "SIDEBAR_BORDER": "#24344A",
        "CARD_BG": "#17212E",
        "INPUT_BG": "#1B2634",
        "INPUT_BORDER": "#384A64",
        "INPUT_FOCUS": "#5CC9B9",
        "TEXT": "#EAF1F9",
        "TEXT_MUTED": "#9AAEC3",
        "ACCENT": "#42B8A9",
        "ACCENT_HOVER": "#63D4C4",
        "ACCENT_SOFT": "#173B39",
        "ITEM_HOVER": "#202E3F",
        "ITEM_SELECTED": "#1E4140",
        "ITEM_SELECTED_BORDER": "#63D4C4",
        "BUTTON_BG": "#223041",
        "BUTTON_HOVER": "#2D3F53",
        "BUTTON_TEXT": "#EAF1F9",
        "MENU_BG": "#151E2A",
        "MENU_ITEM_SEL": "#274A4C",
        "BORDER_SOFT": "#223041",
        "DANGER": "#E87464",
        "SUCCESS": "#74C284",
    },
    "forest-night": {
        # Matcha Night: pine-dark walls, moss trim, spring matcha glow.
        "MAIN_BG": "#0F1712",
        "MAIN_BG_ALT": "#14201A",
        "SIDEBAR_BG": "#111B15",
        "SIDEBAR_BORDER": "#29402F",
        "CARD_BG": "#18251D",
        "INPUT_BG": "#1C2B21",
        "INPUT_BORDER": "#37523F",
        "INPUT_FOCUS": "#8ADDA9",
        "TEXT": "#ECF3EC",
        "TEXT_MUTED": "#A3B8A8",
        "ACCENT": "#57BD80",
        "ACCENT_HOVER": "#7BDBA2",
        "ACCENT_SOFT": "#1D3826",
        "ITEM_HOVER": "#202F25",
        "ITEM_SELECTED": "#214230",
        "ITEM_SELECTED_BORDER": "#7BDBA2",
        "BUTTON_BG": "#223127",
        "BUTTON_HOVER": "#2C4030",
        "BUTTON_TEXT": "#ECF3EC",
        "MENU_BG": "#17231C",
        "MENU_ITEM_SEL": "#2E5039",
        "BORDER_SOFT": "#202F25",
        "DANGER": "#E87464",
        "SUCCESS": "#85C893",
    },
    "midnight-ember": {
        # Ember Night: a café lit by the fireplace — charcoal-rose walls and a
        # warm ember-orange glow. The coziest late-night theme.
        "MAIN_BG": "#151011",
        "MAIN_BG_ALT": "#1E1516",
        "SIDEBAR_BG": "#191213",
        "SIDEBAR_BORDER": "#38241F",
        "CARD_BG": "#211718",
        "INPUT_BG": "#261A1B",
        "INPUT_BORDER": "#4A2E28",
        "INPUT_FOCUS": "#F0956B",
        "TEXT": "#F8ECE4",
        "TEXT_MUTED": "#BCA196",
        "ACCENT": "#E2784A",
        "ACCENT_HOVER": "#F5926A",
        "ACCENT_SOFT": "#3B221A",
        "ITEM_HOVER": "#2C1F1E",
        "ITEM_SELECTED": "#46291F",
        "ITEM_SELECTED_BORDER": "#F5926A",
        "BUTTON_BG": "#2E211F",
        "BUTTON_HOVER": "#3C2B27",
        "BUTTON_TEXT": "#F8ECE4",
        "MENU_BG": "#201718",
        "MENU_ITEM_SEL": "#543024",
        "BORDER_SOFT": "#2C1F1E",
        "DANGER": "#E87464",
        "SUCCESS": "#8FB072",
    },
    "lavender-day": {
        # Lavender Latte: soft violet over steamed milk — calm and creative.
        "MAIN_BG": "#FAF7FC",
        "MAIN_BG_ALT": "#F2ECF7",
        "SIDEBAR_BG": "#F5EFF8",
        "SIDEBAR_BORDER": "#DFD2EA",
        "CARD_BG": "#FFFDFF",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#D5C5E4",
        "INPUT_FOCUS": "#7C5FB8",
        "TEXT": "#2A2135",
        "TEXT_MUTED": "#75688C",
        "ACCENT": "#8265C4",
        "ACCENT_HOVER": "#9C7FDC",
        "ACCENT_SOFT": "#ECE3F8",
        "ITEM_HOVER": "#F3EDF8",
        "ITEM_SELECTED": "#E7DCF4",
        "ITEM_SELECTED_BORDER": "#8265C4",
        "BUTTON_BG": "#F4EDF9",
        "BUTTON_HOVER": "#EADFF5",
        "BUTTON_TEXT": "#2A2135",
        "MENU_BG": "#FFFDFF",
        "MENU_ITEM_SEL": "#EDE2F6",
        "BORDER_SOFT": "#EBE1F2",
        "DANGER": "#B84A58",
        "SUCCESS": "#567F56",
    },
    "cocoa-day": {
        # Hot Cocoa: whipped chocolate-milk warmth with a roasted nib accent.
        "MAIN_BG": "#FAF4EE",
        "MAIN_BG_ALT": "#F1E5D8",
        "SIDEBAR_BG": "#F4EADF",
        "SIDEBAR_BORDER": "#E0CCB8",
        "CARD_BG": "#FFFCF8",
        "INPUT_BG": "#FFFFFF",
        "INPUT_BORDER": "#D6BFA8",
        "INPUT_FOCUS": "#8A5A34",
        "TEXT": "#2C2016",
        "TEXT_MUTED": "#7D6450",
        "ACCENT": "#8F5E32",
        "ACCENT_HOVER": "#A97242",
        "ACCENT_SOFT": "#F2E1CE",
        "ITEM_HOVER": "#F3E9DC",
        "ITEM_SELECTED": "#ECDBC2",
        "ITEM_SELECTED_BORDER": "#8F5E32",
        "BUTTON_BG": "#F4EADD",
        "BUTTON_HOVER": "#EADCC8",
        "BUTTON_TEXT": "#2C2016",
        "MENU_BG": "#FFFCF8",
        "MENU_ITEM_SEL": "#EFDFC8",
        "BORDER_SOFT": "#EADCC9",
        "DANGER": "#B84A38",
        "SUCCESS": "#5E7F3C",
    },
    "lavender-night": {
        # Lavender Dusk: violet-dark walls, luminous lilac glow.
        "MAIN_BG": "#14101A",
        "MAIN_BG_ALT": "#1B1524",
        "SIDEBAR_BG": "#171220",
        "SIDEBAR_BORDER": "#332748",
        "CARD_BG": "#1D1626",
        "INPUT_BG": "#221A2C",
        "INPUT_BORDER": "#423256",
        "INPUT_FOCUS": "#C3A8F2",
        "TEXT": "#F2EBFA",
        "TEXT_MUTED": "#AC9CC2",
        "ACCENT": "#A98BE0",
        "ACCENT_HOVER": "#C2A6F0",
        "ACCENT_SOFT": "#2E2344",
        "ITEM_HOVER": "#251C30",
        "ITEM_SELECTED": "#362850",
        "ITEM_SELECTED_BORDER": "#C2A6F0",
        "BUTTON_BG": "#271E33",
        "BUTTON_HOVER": "#332744",
        "BUTTON_TEXT": "#F2EBFA",
        "MENU_BG": "#1C1626",
        "MENU_ITEM_SEL": "#403061",
        "BORDER_SOFT": "#251C30",
        "DANGER": "#E57A85",
        "SUCCESS": "#8FBE93",
    },
    "blueberry-night": {
        # Blueberry Night: deep blue-violet with an iris glow — moody and cool.
        "MAIN_BG": "#12101C",
        "MAIN_BG_ALT": "#191627",
        "SIDEBAR_BG": "#151223",
        "SIDEBAR_BORDER": "#2E2848",
        "CARD_BG": "#1A1729",
        "INPUT_BG": "#1F1B30",
        "INPUT_BORDER": "#3B3458",
        "INPUT_FOCUS": "#9FA8F2",
        "TEXT": "#EEEBF8",
        "TEXT_MUTED": "#A5A0C2",
        "ACCENT": "#8B90E0",
        "ACCENT_HOVER": "#A8ACEE",
        "ACCENT_SOFT": "#292747",
        "ITEM_HOVER": "#221E33",
        "ITEM_SELECTED": "#322D55",
        "ITEM_SELECTED_BORDER": "#A8ACEE",
        "BUTTON_BG": "#252040",
        "BUTTON_HOVER": "#302A52",
        "BUTTON_TEXT": "#EEEBF8",
        "MENU_BG": "#1A1729",
        "MENU_ITEM_SEL": "#3A3468",
        "BORDER_SOFT": "#221E33",
        "DANGER": "#E57A85",
        "SUCCESS": "#85B89B",
    },
    "mocha-mint": {
        # Mint Mocha: dark chocolate walls with a fresh mint counter — the
        # after-dinner drink of the theme family.
        "MAIN_BG": "#101614",
        "MAIN_BG_ALT": "#15201C",
        "SIDEBAR_BG": "#121917",
        "SIDEBAR_BORDER": "#263C34",
        "CARD_BG": "#17221E",
        "INPUT_BG": "#1B2723",
        "INPUT_BORDER": "#31493F",
        "INPUT_FOCUS": "#7FD6B8",
        "TEXT": "#EAF4EE",
        "TEXT_MUTED": "#9DB8AC",
        "ACCENT": "#4FC49A",
        "ACCENT_HOVER": "#72DDB5",
        "ACCENT_SOFT": "#17382D",
        "ITEM_HOVER": "#1E2C26",
        "ITEM_SELECTED": "#1E4237",
        "ITEM_SELECTED_BORDER": "#72DDB5",
        "BUTTON_BG": "#21312A",
        "BUTTON_HOVER": "#2B4036",
        "BUTTON_TEXT": "#EAF4EE",
        "MENU_BG": "#17221E",
        "MENU_ITEM_SEL": "#285043",
        "BORDER_SOFT": "#1E2C26",
        "DANGER": "#E57A75",
        "SUCCESS": "#85C8A8",
    },
}

# Theme shown when a profile has never picked one (and for unknown names).
DEFAULT_THEME = "minimal"

# Display names for the picker: the keys stay stable IDs, the labels tell the
# story ("Sakura Café" beats "rose-day" in a menu).
THEME_LABELS = {
    "minimal": "Latte Cream · all-day default",
    "latte": "Honey Crème · golden & warm",
    "rose-day": "Sakura Café · soft rose",
    "dawn": "Café Dawn · peachy first light",
    "matcha-day": "Matcha Latte · green & fresh",
    "sand-day": "Morning Crème · neutral office",
    "lavender-day": "Lavender Latte · violet calm",
    "cocoa-day": "Hot Cocoa · chocolate warmth",
    "cafe-night": "Espresso House · amber lamps",
    "minimal-night": "Midnight Mocha · latte-foam gold",
    "ocean-night": "Café Azul · deep teal night",
    "forest-night": "Matcha Night · pine & moss",
    "midnight-ember": "Ember Night · fireplace glow",
    "lavender-night": "Lavender Dusk · lilac glow",
    "blueberry-night": "Blueberry Night · iris mood",
    "mocha-mint": "Mint Mocha · chocolate & mint",
}


def theme_display_name(mode: str) -> str:
    return THEME_LABELS.get(mode, mode)


def accent_display_name(accent: str) -> str:
    return accent.capitalize()

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
# Soft tokens are dark-tinted; _palette() re-blends them for light themes.
ACCENTS = {
    "brass":     ("#D9A94F", "#F0C168", "#43301A", "#E5B763"),  # glowing café brass (default)
    "caramel":   ("#C08A3E", "#DAA654", "#3D2A12", "#D4974C"),  # spun sugar caramel
    "ember":     ("#E2784A", "#F5926A", "#3B221A", "#F0956B"),  # fireplace ember
    "teal":      ("#3AB5A4", "#5FD2C2", "#12332F", "#4CC4B4"),  # mint-tea counter
    "violet":    ("#9B7FE0", "#B9A2EE", "#2B2347", "#A98FE6"),  # ube latte
    "sky":       ("#4E96DE", "#74B4EE", "#1B2E45", "#5CA2E6"),  # morning window sky
    "rose":      ("#DD6292", "#F083B0", "#3D1F30", "#E8739F"),  # strawberry glaze
    "matcha":    ("#6E9440", "#8CBB54", "#223316", "#7EA64B"),  # whisked matcha
    "slate":     ("#94A1B2", "#B0BDCE", "#272E37", "#A4B1C2"),  # quiet stone
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
    # Unknown names fall back to the documented default theme, not a random one
    # (v6.5 audit: a typo'd theme silently rendered the whole app dark).
    palette.update(PALETTES.get(mode, PALETTES[DEFAULT_THEME]))
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
QScrollArea#HomeScroll {
    border: none;
    background-color: %(MAIN_BG)s;
}
QScrollArea#HomeScroll > QWidget > QWidget { background-color: %(MAIN_BG)s; }

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
#ActionGlyph { color: %(ACCENT_HOVER)s; font-size: 25px; font-weight: 700; }
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
#SidebarCollapse {
    background-color: %(MAIN_BG_ALT)s; color: %(TEXT)s;
    border: 1px solid %(BORDER_SOFT)s; border-radius: %(RADIUS_SM)s;
    min-width: 22px; min-height: 22px; padding: 0 4px; font-size: 13px; font-weight: 700;
}
#SidebarCollapse:hover { background-color: %(ITEM_HOVER)s; border-color: %(ACCENT)s; color: %(ACCENT_HOVER)s; }

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
    min-height: 56px;
    background-color: %(CARD_BG)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 14px;
}
#StatTile:hover { border-color: %(ACCENT)s; background-color: %(ITEM_HOVER)s; }
#StatValue { color: %(ACCENT_HOVER)s; font-size: 19px; font-weight: 800; }
#StatLabel { color: %(TEXT_MUTED)s; font-size: 9px; }

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
#ActionGlyph { color: %(ACCENT_HOVER)s; font-size: 24px; font-weight: 700; }
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
#SidebarCollapse {
    min-width: 22px;
    min-height: 22px;
    background-color: %(MAIN_BG_ALT)s;
    color: %(TEXT)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 8px;
    padding: 0 4px;
    font-size: 13px;
    font-weight: 700;
}
#SidebarCollapse:hover {
    color: %(ACCENT_HOVER)s;
    background-color: %(ITEM_HOVER)s;
    border-color: %(ACCENT)s;
}
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
/* Vivaldi/Arc-style split view dock (left side). */
#SplitDock {
    background-color: %(CARD_BG)s;
    border-right: 1px solid %(BORDER_SOFT)s;
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
/* Slim right dock rail (panel + AI toggles). */
#DockRail {
    background-color: %(SIDEBAR_BG)s;
    border-left: 1px solid %(BORDER_SOFT)s;
}
/* Chrome-style link-hover target strip. */
#LinkPreview {
    background-color: %(CARD_BG)s;
    color: %(TEXT_MUTED)s;
    border: 1px solid %(BORDER_SOFT)s;
    border-radius: 6px;
    padding: 3px 10px;
    font-size: 11px;
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
        background: transparent; color: %(TEXT_MUTED)s; border: 1px solid transparent;
        border-radius: 8px; min-width: 32px; min-height: 32px; font-size: 14px;
        font-weight: 700; padding: 0;
    }
    QToolButton:hover { color: %(ACCENT_HOVER)s; background: %(ITEM_HOVER)s; border-color: %(BORDER_SOFT)s; }
    QToolButton[collapsed="true"] {
        background: %(ACCENT_SOFT)s; color: %(ACCENT_HOVER)s;
        border: 2px solid %(ACCENT)s; border-radius: 10px;
    }
    QToolButton[collapsed="true"]:hover {
        background: %(ITEM_SELECTED)s; color: %(ACCENT_HOVER)s; border-color: %(ACCENT_HOVER)s;
    }
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



