"""Acesso aos dados: grupos, tarefas, subtarefas, sessões, distrações e revisões do dia.

Todas as funções devolvem dicts simples (não sqlite3.Row), para a UI não depender do banco.
Tempo real de uma tarefa = soma dos segundos das sessões 'work' e 'manual' ligadas a ela
(sessões de subtarefa também guardam o task_id, então a tarefa soma as subtarefas).
"""

import re
from datetime import date, datetime

from . import db, recurrence

TASK_STATUSES = ("todo", "doing", "done", "discarded")
ENERGY_LEVELS = ("low", "medium", "high")
DIFFICULTIES = ("easy", "ok", "hard")
MOODS = ("hard", "ok", "good")
SESSION_KINDS = ("work", "short_break", "long_break", "manual")
REAL_TIME_KINDS = ("work", "manual")

GROUP_FIELDS = {"name", "color", "work_min", "short_break_min", "require_estimate", "archived", "position"}
TASK_FIELDS = {
    "group_id", "title", "notes", "scheduled_for", "repeat_rule", "energy",
    "estimate_min", "ai_estimate_min", "status", "position", "postponed_count", "difficulty",
}
SUBTASK_FIELDS = {"title", "estimate_min", "done", "position"}


def _row(row):
    return dict(row) if row is not None else None


def _rows(rows):
    return [dict(r) for r in rows]


def _day(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"data inválida: {value!r}")


def _check_minutes(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} deve ser um inteiro de minutos >= 0")
    return value


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _check_color(color):
    if not isinstance(color, str) or not _HEX_COLOR.match(color):
        raise ValueError(f"cor inválida: {color!r} (use #RRGGBB)")
    return color.upper()


def _check_title(title):
    title = (title or "").strip()
    if not title:
        raise ValueError("o título não pode ficar vazio")
    return title


class Repository:
    def __init__(self, conn, now=datetime.now):
        self.conn = conn
        self.now = now

    def _ts(self):
        return db.timestamp(self.now())

    def _update(self, table, allowed, row_id, fields):
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"campos desconhecidos para {table}: {sorted(unknown)}")
        if not fields:
            return
        cols = ", ".join(f"{name} = ?" for name in fields)
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE {table} SET {cols} WHERE id = ?", (*fields.values(), row_id)
            )
        if cur.rowcount == 0:
            raise KeyError(f"{table} {row_id} não existe")

    def _next_position(self, table, where, params):
        row = self.conn.execute(
            f"SELECT COALESCE(MAX(position), -1) + 1 FROM {table} WHERE {where}", params
        ).fetchone()
        return row[0]

    def _reorder(self, table, ids, where, params):
        existing = {r[0] for r in self.conn.execute(f"SELECT id FROM {table} WHERE {where}", params)}
        if set(ids) != existing or len(ids) != len(existing):
            raise ValueError(f"a nova ordem de {table} precisa conter exatamente os mesmos itens")
        with self.conn:
            for position, row_id in enumerate(ids):
                self.conn.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (position, row_id))

    # ---- grupos ---------------------------------------------------------

    def default_group_id(self):
        return db.ensure_default_group(self.conn, self.now())

    def list_groups(self, include_archived=False):
        sql = "SELECT * FROM groups"
        if not include_archived:
            sql += " WHERE archived = 0"
        return _rows(self.conn.execute(sql + " ORDER BY position, created_at"))

    def get_group(self, group_id):
        return _row(self.conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone())

    def create_group(self, name, color=db.DEFAULT_GROUP_COLOR, work_min=None,
                     short_break_min=None, require_estimate=False):
        group_id = db.new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO groups(id, name, color, work_min, short_break_min, require_estimate,"
                " position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (group_id, _check_title(name), _check_color(color),
                 _check_minutes(work_min, "work_min"),
                 _check_minutes(short_break_min, "short_break_min"),
                 int(bool(require_estimate)),
                 self._next_position("groups", "1", ()), self._ts()),
            )
        return self.get_group(group_id)

    def update_group(self, group_id, **fields):
        if "name" in fields:
            fields["name"] = _check_title(fields["name"])
        if "color" in fields:
            fields["color"] = _check_color(fields["color"])
        for key in ("work_min", "short_break_min"):
            if key in fields:
                _check_minutes(fields[key], key)
        for key in ("require_estimate", "archived"):
            if key in fields:
                fields[key] = int(bool(fields[key]))
        self._update("groups", GROUP_FIELDS, group_id, fields)
        return self.get_group(group_id)

    def archive_group(self, group_id, archived=True):
        return self.update_group(group_id, archived=archived)

    def delete_group(self, group_id):
        """Apaga o grupo e todas as suas tarefas. O grupo padrão é recriado se preciso."""
        with self.conn:
            self.conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            if db.get_meta(self.conn, "default_group_id") == group_id:
                self.conn.execute("DELETE FROM meta WHERE key = 'default_group_id'")

    def reorder_groups(self, ids):
        self._reorder("groups", list(ids), "archived = 0", ())

    # ---- tarefas --------------------------------------------------------

    def list_tasks(self, group_id=None, scheduled_for=..., statuses=None):
        """Lista tarefas. scheduled_for=None filtra as sem data; omitido não filtra."""
        clauses, params = [], []
        if group_id is not None:
            clauses.append("group_id = ?")
            params.append(group_id)
        if scheduled_for is None:
            clauses.append("scheduled_for IS NULL")
        elif scheduled_for is not ...:
            clauses.append("scheduled_for = ?")
            params.append(_day(scheduled_for))
        if statuses:
            clauses.append(f"status IN ({', '.join('?' * len(statuses))})")
            params.extend(statuses)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return _rows(self.conn.execute(
            f"SELECT * FROM tasks{where} ORDER BY position, created_at", params
        ))

    def list_for_day(self, day):
        """Tarefas da visão "Hoje" de `day`, na ordem de grupos e posições.

        Entram: pendentes sem data, agendadas para o dia ou atrasadas (ainda não levadas para
        outro dia), e concluídas naquele dia. Ficam de fora: descartadas e grupos arquivados.
        """
        day = _day(day)
        return _rows(self.conn.execute(
            "SELECT t.* FROM tasks t JOIN groups g ON g.id = t.group_id WHERE g.archived = 0 AND ("
            " (t.status IN ('todo', 'doing') AND (t.scheduled_for IS NULL OR t.scheduled_for <= ?))"
            " OR (t.status = 'done' AND (substr(t.done_at, 1, 10) = ? OR t.scheduled_for = ?)))"
            " ORDER BY g.position, g.created_at, t.position, t.created_at",
            (day, day, day),
        ))

    def get_task(self, task_id):
        return _row(self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def create_task(self, group_id, title, estimate_min=None, scheduled_for=None, notes="",
                    repeat_rule=None, energy=None):
        if energy is not None and energy not in ENERGY_LEVELS:
            raise ValueError(f"energia inválida: {energy}")
        if not recurrence.is_valid(repeat_rule):
            raise ValueError(f"regra de repetição inválida: {repeat_rule!r}")
        group = self.get_group(group_id)
        if group is None:
            raise KeyError(f"grupo {group_id} não existe")
        if group["require_estimate"] and estimate_min is None:
            raise ValueError("este grupo exige a previsão de tempo")
        task_id = db.new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO tasks(id, group_id, title, notes, scheduled_for, repeat_rule, energy,"
                " estimate_min, position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, group_id, _check_title(title), notes or "", _day(scheduled_for),
                 repeat_rule, energy, _check_minutes(estimate_min, "estimate_min"),
                 self._next_position("tasks", "group_id = ?", (group_id,)), self._ts()),
            )
        return self.get_task(task_id)

    def update_task(self, task_id, **fields):
        if "title" in fields:
            fields["title"] = _check_title(fields["title"])
        if "scheduled_for" in fields:
            fields["scheduled_for"] = _day(fields["scheduled_for"])
        for key in ("estimate_min", "ai_estimate_min"):
            if key in fields:
                _check_minutes(fields[key], key)
        if fields.get("energy") is not None and fields["energy"] not in ENERGY_LEVELS:
            raise ValueError(f"energia inválida: {fields['energy']}")
        if "repeat_rule" in fields and not recurrence.is_valid(fields["repeat_rule"]):
            raise ValueError(f"regra de repetição inválida: {fields['repeat_rule']!r}")
        if fields.get("difficulty") is not None and fields["difficulty"] not in DIFFICULTIES:
            raise ValueError(f"dificuldade inválida: {fields['difficulty']}")
        if "status" in fields:
            # Status passa por set_task_status para manter done_at coerente.
            status = fields.pop("status")
            self._update("tasks", TASK_FIELDS, task_id, fields)
            return self.set_task_status(task_id, status)
        self._update("tasks", TASK_FIELDS, task_id, fields)
        return self.get_task(task_id)

    def set_task_status(self, task_id, status):
        if status not in TASK_STATUSES:
            raise ValueError(f"status inválido: {status}")
        done_at = self._ts() if status == "done" else None
        with self.conn:
            cur = self.conn.execute(
                "UPDATE tasks SET status = ?, done_at = ? WHERE id = ?", (status, done_at, task_id)
            )
        if cur.rowcount == 0:
            raise KeyError(f"tarefa {task_id} não existe")
        return self.get_task(task_id)

    def delete_task(self, task_id):
        with self.conn:
            self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def move_task(self, task_id, group_id):
        if self.get_group(group_id) is None:
            raise KeyError(f"grupo {group_id} não existe")
        position = self._next_position("tasks", "group_id = ?", (group_id,))
        return self.update_task(task_id, group_id=group_id, position=position)

    def reorder_tasks(self, group_id, ids):
        self._reorder("tasks", list(ids), "group_id = ?", (group_id,))

    def postpone_task(self, task_id, new_day):
        """Reagenda a tarefa (ex.: levar para amanhã) e conta o adiamento."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"tarefa {task_id} não existe")
        return self.update_task(
            task_id, scheduled_for=new_day, postponed_count=task["postponed_count"] + 1
        )

    def duplicate_task(self, task_id, scheduled_for=None, repeat_rule=None):
        """Copia a tarefa e suas subtarefas como novas (a fazer), sem histórico de tempo."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"tarefa {task_id} não existe")
        copy = self.create_task(
            task["group_id"], task["title"], estimate_min=task["estimate_min"],
            scheduled_for=scheduled_for, notes=task["notes"], energy=task["energy"],
            repeat_rule=repeat_rule,
        )
        for sub in self.list_subtasks(task_id):
            self.add_subtask(copy["id"], sub["title"], sub["estimate_min"])
        return copy

    # ---- subtarefas -----------------------------------------------------

    def list_subtasks(self, task_id):
        return _rows(self.conn.execute(
            "SELECT * FROM subtasks WHERE task_id = ? ORDER BY position", (task_id,)
        ))

    def get_subtask(self, subtask_id):
        return _row(self.conn.execute("SELECT * FROM subtasks WHERE id = ?", (subtask_id,)).fetchone())

    def add_subtask(self, task_id, title, estimate_min=None):
        if self.get_task(task_id) is None:
            raise KeyError(f"tarefa {task_id} não existe")
        subtask_id = db.new_id()
        with self.conn:
            self.conn.execute(
                "INSERT INTO subtasks(id, task_id, title, estimate_min, position) VALUES (?, ?, ?, ?, ?)",
                (subtask_id, task_id, _check_title(title), _check_minutes(estimate_min, "estimate_min"),
                 self._next_position("subtasks", "task_id = ?", (task_id,))),
            )
        return self.get_subtask(subtask_id)

    def update_subtask(self, subtask_id, **fields):
        if "title" in fields:
            fields["title"] = _check_title(fields["title"])
        if "estimate_min" in fields:
            _check_minutes(fields["estimate_min"], "estimate_min")
        if "done" in fields:
            return self._update_subtask_done(subtask_id, fields)
        self._update("subtasks", SUBTASK_FIELDS, subtask_id, fields)
        return self.get_subtask(subtask_id)

    def _update_subtask_done(self, subtask_id, fields):
        done = bool(fields.pop("done"))
        self._update("subtasks", SUBTASK_FIELDS, subtask_id, fields)
        with self.conn:
            cur = self.conn.execute(
                "UPDATE subtasks SET done = ?, done_at = ? WHERE id = ?",
                (int(done), self._ts() if done else None, subtask_id),
            )
        if cur.rowcount == 0:
            raise KeyError(f"subtarefa {subtask_id} não existe")
        return self.get_subtask(subtask_id)

    def set_subtask_done(self, subtask_id, done=True):
        return self.update_subtask(subtask_id, done=done)

    def delete_subtask(self, subtask_id):
        with self.conn:
            self.conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))

    def reorder_subtasks(self, task_id, ids):
        self._reorder("subtasks", list(ids), "task_id = ?", (task_id,))

    def subtasks_by_task(self, task_ids):
        """Subtarefas de várias tarefas de uma vez: {task_id: [subtarefa, ...]} em ordem."""
        task_ids = list(task_ids)
        result = {task_id: [] for task_id in task_ids}
        if not task_ids:
            return result
        rows = self.conn.execute(
            f"SELECT * FROM subtasks WHERE task_id IN ({', '.join('?' * len(task_ids))})"
            " ORDER BY task_id, position", task_ids,
        )
        for row in rows:
            result[row["task_id"]].append(dict(row))
        return result

    def subtasks_estimate_sum(self, task_id):
        """Soma das previsões das subtarefas (None se nenhuma tiver previsão)."""
        row = self.conn.execute(
            "SELECT SUM(estimate_min) FROM subtasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0]

    # ---- sessões e tempo real -------------------------------------------

    def start_session(self, kind, task_id=None, subtask_id=None, started_at=None):
        if kind not in SESSION_KINDS:
            raise ValueError(f"tipo de sessão inválido: {kind}")
        if subtask_id is not None and task_id is None:
            sub = self.get_subtask(subtask_id)
            if sub is None:
                raise KeyError(f"subtarefa {subtask_id} não existe")
            task_id = sub["task_id"]
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions(task_id, subtask_id, kind, started_at) VALUES (?, ?, ?, ?)",
                (task_id, subtask_id, kind, db.timestamp(started_at or self.now())),
            )
        return cur.lastrowid

    def end_session(self, session_id, seconds, interrupted=False, ended_at=None, note=None,
                    completed_phase=False):
        """Fecha a sessão. completed_phase marca a que levou o pomodoro/intervalo até o fim."""
        if seconds < 0:
            raise ValueError("uma sessão não pode ter duração negativa")
        sets = "ended_at = ?, seconds = ?, interrupted = ?, completed_phase = ?"
        params = [db.timestamp(ended_at or self.now()), int(seconds), int(bool(interrupted)),
                  int(bool(completed_phase))]
        if note is not None:
            sets += ", note = ?"
            params.append(note)
        with self.conn:
            cur = self.conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?", (*params, session_id))
        if cur.rowcount == 0:
            raise KeyError(f"sessão {session_id} não existe")
        return self.get_session(session_id)

    def update_session_seconds(self, session_id, seconds):
        """Checkpoint de uma sessão ainda aberta (protege o tempo contra queda do app)."""
        if seconds < 0:
            raise ValueError("uma sessão não pode ter duração negativa")
        with self.conn:
            cur = self.conn.execute("UPDATE sessions SET seconds = ? WHERE id = ?", (int(seconds), session_id))
        if cur.rowcount == 0:
            raise KeyError(f"sessão {session_id} não existe")

    def open_sessions(self):
        return _rows(self.conn.execute("SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id"))

    def delete_session(self, session_id):
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def get_session(self, session_id):
        return _row(self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())

    def add_manual_adjustment(self, task_id, seconds, subtask_id=None, note="Ajuste manual"):
        """Corrige o tempo real (positivo ou negativo) sem inventar uma sessão de foco."""
        if self.get_task(task_id) is None:
            raise KeyError(f"tarefa {task_id} não existe")
        ts = self._ts()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions(task_id, subtask_id, kind, started_at, ended_at, seconds, note)"
                " VALUES (?, ?, 'manual', ?, ?, ?, ?)",
                (task_id, subtask_id, ts, ts, int(seconds), note),
            )
        return cur.lastrowid

    def list_sessions(self, task_id=None, since=None, until=None, kinds=None):
        clauses, params = [], []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if since is not None:
            clauses.append("started_at >= ?")
            params.append(db.timestamp(since) if isinstance(since, datetime) else since)
        if until is not None:
            clauses.append("started_at < ?")
            params.append(db.timestamp(until) if isinstance(until, datetime) else until)
        if kinds:
            clauses.append(f"kind IN ({', '.join('?' * len(kinds))})")
            params.extend(kinds)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return _rows(self.conn.execute(f"SELECT * FROM sessions{where} ORDER BY started_at, id", params))

    def real_seconds(self, task_id):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) FROM sessions WHERE task_id = ? AND kind IN ('work', 'manual')",
            (task_id,),
        ).fetchone()
        return max(row[0], 0)

    def real_seconds_subtask(self, subtask_id):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) FROM sessions WHERE subtask_id = ? AND kind IN ('work', 'manual')",
            (subtask_id,),
        ).fetchone()
        return max(row[0], 0)

    def real_seconds_map(self):
        """Tempo real de todas as tarefas e subtarefas: ({task_id: s}, {subtask_id: s})."""
        by_task, by_subtask = {}, {}
        rows = self.conn.execute(
            "SELECT task_id, subtask_id, SUM(seconds) AS total FROM sessions"
            " WHERE kind IN ('work', 'manual') AND task_id IS NOT NULL GROUP BY task_id, subtask_id"
        )
        for row in rows:
            by_task[row["task_id"]] = by_task.get(row["task_id"], 0) + row["total"]
            if row["subtask_id"]:
                by_subtask[row["subtask_id"]] = row["total"]
        return ({k: max(v, 0) for k, v in by_task.items()},
                {k: max(v, 0) for k, v in by_subtask.items()})

    def count_work_sessions(self, since=None, until=None):
        """Quantos pomodoros foram levados até o fim (uma fase pode ter várias sessões)."""
        sessions = self.list_sessions(since=since, until=until, kinds=("work",))
        return sum(1 for s in sessions if s["completed_phase"])

    # ---- distrações -----------------------------------------------------

    def add_distraction(self, text, session_id=None, task_id=None):
        text = _check_title(text)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO distractions(text, created_at, session_id, task_id) VALUES (?, ?, ?, ?)",
                (text, self._ts(), session_id, task_id),
            )
        return cur.lastrowid

    def list_distractions(self, since=None, task_id=None):
        clauses, params = [], []
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(db.timestamp(since) if isinstance(since, datetime) else since)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return _rows(self.conn.execute(f"SELECT * FROM distractions{where} ORDER BY created_at, id", params))

    def delete_distraction(self, distraction_id):
        with self.conn:
            self.conn.execute("DELETE FROM distractions WHERE id = ?", (distraction_id,))

    # ---- revisão do dia -------------------------------------------------

    def get_day_review(self, day):
        return _row(self.conn.execute("SELECT * FROM day_reviews WHERE day = ?", (_day(day),)).fetchone())

    def save_day_review(self, day, mood=None, free_minutes=None, confirmed=False):
        if mood is not None and mood not in MOODS:
            raise ValueError(f"humor inválido: {mood}")
        _check_minutes(free_minutes, "free_minutes")
        day = _day(day)
        current = self.get_day_review(day) or {}
        mood = mood if mood is not None else current.get("mood")
        free_minutes = free_minutes if free_minutes is not None else current.get("free_minutes")
        confirmed_at = self._ts() if confirmed else current.get("confirmed_at")
        with self.conn:
            self.conn.execute(
                "INSERT INTO day_reviews(day, mood, free_minutes, confirmed_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(day) DO UPDATE SET mood = excluded.mood,"
                " free_minutes = excluded.free_minutes, confirmed_at = excluded.confirmed_at",
                (day, mood, free_minutes, confirmed_at),
            )
        return self.get_day_review(day)
