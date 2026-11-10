"""Atalhos de teclado da janela principal: decide a ação de uma tecla. Função pura, sem GTK.

Ctrl K busca · Ctrl N nova tarefa · Espaço pausa/retoma · Esc volta para Hoje.
Espaço e Esc só valem quando o foco não está num campo de texto (ali pertencem ao campo) e,
no caso do Espaço, num botão ou interruptor (ali ele aciona o próprio controle).
"""


def key_action(key, ctrl=False, typing=False, activatable=False, page="today"):
    """key: nome da tecla (Gdk.keyval_name). Devolve "search", "new-task", "toggle-timer", "back" ou None."""
    name = (key or "").lower()
    if ctrl:
        return {"k": "search", "n": "new-task"}.get(name)
    if typing:
        return None
    if name == "space" and not activatable:
        return "toggle-timer"
    if name == "escape" and page != "today":
        return "back"
    return None
