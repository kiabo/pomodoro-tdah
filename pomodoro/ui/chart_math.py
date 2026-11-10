"""Geometria dos desenhos (anel do timer, gráfico de barras). Sem GTK, para poder testar."""

import math

RING_START = -math.pi / 2  # 12 horas


def ring_arc(fraction):
    """Ângulos (início, fim) em radianos do arco de progresso, no sentido horário."""
    fraction = min(max(fraction, 0.0), 1.0)
    return RING_START, RING_START + 2 * math.pi * fraction


def bar_layout(days, width, height, label_height=22, bar_width=22, pair_gap=4, side_pad=12):
    """Posiciona as barras previsto × real de cada dia.

    days: [{"label": "Seg", "planned": minutos, "real": minutos}, ...]
    Devolve uma lista com, por dia: label, label_x (centro), pair_x0/pair_x1 e as barras
    [{"kind": "planned"|"real_ok"|"real_over", "x", "y", "w", "h", "value"}]. A barra "real"
    fica vermelha (real_over) quando passa do previsto. Com muitos dias as barras afinam.
    """
    count = len(days)
    if count == 0:
        return []
    plot_h = max(height - label_height, 1)
    peak = max([max(d["planned"], d["real"]) for d in days] + [1])
    scale = plot_h / peak

    avail = max(width - 2 * side_pad, 1)
    bar_w = max(2.0, min(bar_width, (avail / count - pair_gap - 4) / 2))
    pair_w = 2 * bar_w + pair_gap
    step = (avail - pair_w) / (count - 1) if count > 1 else 0

    layout = []
    for i, day in enumerate(days):
        x0 = side_pad + (i * step if count > 1 else (avail - pair_w) / 2)
        bars = []
        for j, (kind, value) in enumerate((
            ("planned", day["planned"]),
            ("real_over" if day["planned"] and day["real"] > day["planned"] else "real_ok", day["real"]),
        )):
            h = 0.0 if value <= 0 else max(value * scale, 2.0)
            bars.append({
                "kind": kind, "x": x0 + j * (bar_w + pair_gap), "y": plot_h - h,
                "w": bar_w, "h": h, "value": value,
            })
        layout.append({
            "label": day["label"], "label_x": x0 + pair_w / 2,
            "pair_x0": x0, "pair_x1": x0 + pair_w, "bars": bars,
        })
    return layout


def cycle_segments(work_min, short_min, long_min, cycles):
    """Sequência de um ciclo completo: [{"kind": "work"|"short"|"long", "minutes": n}, ...]."""
    segments = []
    for index in range(max(cycles, 1)):
        segments.append({"kind": "work", "minutes": work_min})
        last = index == max(cycles, 1) - 1
        segments.append({"kind": "long" if last else "short", "minutes": long_min if last else short_min})
    return segments


def cycle_bar_layout(segments, width, gap=3, min_width=3):
    """Posiciona os segmentos do ciclo numa barra, proporcionais à duração: [{kind, minutes, x, w}]."""
    if not segments:
        return []
    total = sum(max(s["minutes"], 0) for s in segments) or 1
    usable = max(width - gap * (len(segments) - 1), len(segments) * min_width)
    layout, x = [], 0.0
    for segment in segments:
        w = max(usable * max(segment["minutes"], 0) / total, min_width)
        layout.append({"kind": segment["kind"], "minutes": segment["minutes"], "x": x, "w": w})
        x += w + gap
    return layout


def capacity_widths(width, planned_fraction, ai_fraction):
    """Larguras da barra de capacidade do dia: (previsto, extra que a IA acrescenta). Cabem em `width`."""
    planned = min(max(planned_fraction, 0.0), 1.0)
    total = min(max(ai_fraction, planned), 1.0)
    return width * planned, width * (total - planned)
