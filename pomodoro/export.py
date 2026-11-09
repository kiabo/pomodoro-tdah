"""Exportação dos dados do usuário em JSON. Nunca inclui as configurações (que guardam a chave da API)."""

import json
from datetime import datetime
from pathlib import Path

EXPORT_VERSION = 1
TABLES = ("groups", "tasks", "subtasks", "sessions", "distractions", "day_reviews")


def export_data(conn, now=datetime.now):
    data = {"version": EXPORT_VERSION, "exported_at": now().isoformat(timespec="seconds")}
    for table in TABLES:
        data[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    return data


def write_export(conn, path, now=datetime.now):
    """Grava o JSON em `path` (escrita atômica). Devolve quantas linhas foram exportadas."""
    data = export_data(conn, now)
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)
    return sum(len(data[table]) for table in TABLES)
