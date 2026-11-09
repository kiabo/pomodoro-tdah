"""Onde posicionar a janela compacta. Funções puras (sem GTK)."""

MARGIN = 24
MIN_VISIBLE = 48


def default_position(monitor, size, margin=MARGIN):
    """Canto superior direito do monitor. monitor = (x, y, largura, altura); size = (largura, altura)."""
    mx, my, mw, _mh = monitor
    return mx + mw - size[0] - margin, my + margin


def valid_position(saved, monitors, size, min_visible=MIN_VISIBLE):
    """Posição salva se a janela ainda aparece em algum monitor; senão o canto do primeiro monitor.

    Cobre o caso de um monitor externo desligado ou da resolução ter mudado.
    """
    if not monitors:
        return saved if saved else (MARGIN, MARGIN)
    if saved and len(saved) == 2:
        x, y = saved
        for mx, my, mw, mh in monitors:
            visible_w = min(x + size[0], mx + mw) - max(x, mx)
            visible_h = min(y + size[1], my + mh) - max(y, my)
            if visible_w >= min_visible and visible_h >= min_visible:
                return x, y
    return default_position(monitors[0], size)
