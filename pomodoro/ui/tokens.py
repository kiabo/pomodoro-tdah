"""Tokens de design (cores) extraídos do Figma. Sem dependência de GTK.

theme.css usa estes mesmos valores; tests/test_theme_tokens.py garante que o CSS
não usa nenhuma cor fora desta lista.
"""

COLORS = {
    # Superfícies e texto
    "bg": "#FAF7F2",
    "sidebar": "#F3EFE7",
    "titlebar": "#EFEAE1",
    "surface": "#FFFFFF",
    "ink": "#1F2430",
    "text2": "#4B5060",
    "gray": "#6B7280",
    "muted": "#8A857C",
    "faint": "#A39E94",
    "line": "#EAE5DB",
    "line_input": "#E2DCD1",
    "line_dashed": "#C9C3B8",
    "chip": "#F1EDE4",
    "toggle_off": "#D9D4C9",
    # Primária (índigo)
    "primary": "#5B5BD6",
    "primary_tint": "#F1F0FD",
    "primary_tint2": "#ECEBFB",
    "primary_soft": "#C9C8F2",
    "primary_soft2": "#A9A8E8",
    # Foco (tomate) e perigo
    "focus": "#F26B4E",
    "focus_tint": "#FDECE7",
    "danger": "#C2412D",
    "danger_border": "#F5C2B5",
    # Concluído (verde)
    "green": "#3DAA7D",
    "green_tint": "#E3F5EC",
    "green_tint2": "#F3FBF7",
    "green_text": "#2F855A",
    "green_border": "#BFE6D2",
    "mint": "#6EE7B7",
    # IA (âmbar)
    "amber": "#F2B33D",
    "amber_tint": "#FFF6E0",
    "amber_border": "#F2D58A",
    "amber_text": "#B7791F",
    "amber_dark": "#7A5414",
    "amber_track": "#F2E2B8",
    # Extras da paleta de grupos
    "pink": "#E879A6",
    "cyan": "#38B2C9",
    # Painéis escuros (timer, modo compacto)
    "dark": "#1F2430",
    "dark2": "#2C3242",
    "dark_track": "#3A4050",
    "dark_dashed": "#4A5166",
    "dark_muted": "#9AA0AE",
    # Pausa no modo compacto
    "break_bg": "#17392C",
    "break_bg2": "#22503D",
    "break_text": "#CDEFE0",
    "break_muted": "#9CC9B6",
    # Sombras
    "black": "#000000",
}

# Paleta de cores de grupo (a ordem é a do seletor no design).
GROUP_COLORS = [
    COLORS["primary"], COLORS["green"], COLORS["amber"], COLORS["pink"],
    COLORS["focus"], COLORS["cyan"], COLORS["muted"],
]


def hex_to_rgb(color):
    """'#5B5BD6' -> (0.357, 0.357, 0.839), em 0..1 como o cairo espera."""
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"cor inválida: #{color}")
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
