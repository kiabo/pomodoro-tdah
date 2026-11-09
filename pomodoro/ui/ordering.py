"""Reordenação por arrastar e soltar. Função pura."""


def reorder_ids(ids, dragged, target, after):
    """Nova ordem depois de soltar `dragged` antes (after=False) ou depois (after=True) de `target`."""
    ids = list(ids)
    if dragged == target or dragged not in ids or target not in ids:
        return ids
    rest = [item for item in ids if item != dragged]
    rest.insert(rest.index(target) + (1 if after else 0), dragged)
    return rest
