"""Banco SQLite do app: conexão, schema versionado e importação do tasks.json antigo."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_FILENAME = "pomodoro.db"
LEGACY_TASKS_FILENAME = "tasks.json"
DEFAULT_GROUP_NAME = "Geral"
DEFAULT_GROUP_COLOR = "#5B5BD6"

# Cada item é uma migração; o índice + 1 é a versão do schema após aplicá-la.
# Nunca altere uma migração já publicada: acrescente uma nova no fim.
MIGRATIONS = [
    """
    CREATE TABLE groups (
        id               TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        color            TEXT NOT NULL DEFAULT '#5B5BD6',
        work_min         INTEGER,
        short_break_min  INTEGER,
        require_estimate INTEGER NOT NULL DEFAULT 0,
        archived         INTEGER NOT NULL DEFAULT 0,
        position         INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL
    );

    CREATE TABLE tasks (
        id              TEXT PRIMARY KEY,
        group_id        TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        title           TEXT NOT NULL,
        notes           TEXT NOT NULL DEFAULT '',
        scheduled_for   TEXT,
        repeat_rule     TEXT,
        energy          TEXT CHECK (energy IN ('low', 'medium', 'high')),
        estimate_min    INTEGER,
        ai_estimate_min INTEGER,
        status          TEXT NOT NULL DEFAULT 'todo'
                        CHECK (status IN ('todo', 'doing', 'done', 'discarded')),
        position        INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL,
        done_at         TEXT,
        postponed_count INTEGER NOT NULL DEFAULT 0,
        difficulty      TEXT CHECK (difficulty IN ('easy', 'ok', 'hard'))
    );
    CREATE INDEX idx_tasks_group ON tasks(group_id);
    CREATE INDEX idx_tasks_scheduled ON tasks(scheduled_for);

    CREATE TABLE subtasks (
        id           TEXT PRIMARY KEY,
        task_id      TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        title        TEXT NOT NULL,
        estimate_min INTEGER,
        done         INTEGER NOT NULL DEFAULT 0,
        position     INTEGER NOT NULL DEFAULT 0,
        done_at      TEXT
    );
    CREATE INDEX idx_subtasks_task ON subtasks(task_id);

    CREATE TABLE sessions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id     TEXT REFERENCES tasks(id) ON DELETE SET NULL,
        subtask_id  TEXT REFERENCES subtasks(id) ON DELETE SET NULL,
        kind        TEXT NOT NULL
                    CHECK (kind IN ('work', 'short_break', 'long_break', 'manual')),
        started_at  TEXT NOT NULL,
        ended_at    TEXT,
        seconds     INTEGER NOT NULL DEFAULT 0,
        interrupted INTEGER NOT NULL DEFAULT 0,
        note        TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_sessions_task ON sessions(task_id);
    CREATE INDEX idx_sessions_started ON sessions(started_at);

    CREATE TABLE distractions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        text       TEXT NOT NULL,
        created_at TEXT NOT NULL,
        session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
        task_id    TEXT REFERENCES tasks(id) ON DELETE SET NULL
    );

    CREATE TABLE day_reviews (
        day          TEXT PRIMARY KEY,
        mood         TEXT CHECK (mood IN ('hard', 'ok', 'good')),
        free_minutes INTEGER,
        confirmed_at TEXT
    );

    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # 2: marca a sessão que terminou um pomodoro/intervalo até o fim (para contar pomodoros).
    "ALTER TABLE sessions ADD COLUMN completed_phase INTEGER NOT NULL DEFAULT 0;",
    # 3: vínculo de uma tarefa com uma issue do Jira. O que vem do Jira fica aqui (somente leitura);
    # título, notas e previsão da tarefa continuam sendo do usuário.
    """
    CREATE TABLE jira_links (
        task_id               TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
        issue_key             TEXT NOT NULL UNIQUE,
        issue_id              TEXT NOT NULL DEFAULT '',
        project_key           TEXT NOT NULL DEFAULT '',
        url                   TEXT NOT NULL DEFAULT '',
        remote_title          TEXT NOT NULL DEFAULT '',
        remote_description    TEXT NOT NULL DEFAULT '',
        remote_status         TEXT NOT NULL DEFAULT '',
        remote_status_category TEXT NOT NULL DEFAULT '',
        remote_estimate_min   INTEGER,
        remote_updated        TEXT NOT NULL DEFAULT '',
        missing               INTEGER NOT NULL DEFAULT 0,
        synced_at             TEXT NOT NULL
    );
    """,
    # 4: registro do que o usuário enviou ao Jira (comentário, status, título/previsão), para ele
    # saber o que já foi e quando. Só guarda envios confirmados por ele.
    """
    CREATE TABLE jira_pushes (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id   TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        issue_key TEXT NOT NULL,
        kind      TEXT NOT NULL CHECK (kind IN ('comment', 'status', 'fields')),
        detail    TEXT NOT NULL DEFAULT '',
        sent_at   TEXT NOT NULL
    );
    CREATE INDEX idx_jira_pushes_task ON jira_pushes(task_id);
    """,
    # 5: worklog e subtarefas no Jira. jira_worklogs lembra quais sessões já foram lançadas (para nunca
    # lançar o mesmo tempo duas vezes); subtasks.jira_key liga uma subtarefa local à sub-task criada no Jira
    # (vazio = só local). O registro de envios passa a aceitar os dois novos tipos.
    """
    ALTER TABLE subtasks ADD COLUMN jira_key TEXT;

    CREATE TABLE jira_worklogs (
        session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
        task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        issue_key  TEXT NOT NULL,
        worklog_id TEXT NOT NULL,
        logged_at  TEXT NOT NULL
    );
    CREATE INDEX idx_jira_worklogs_task ON jira_worklogs(task_id);

    CREATE TABLE jira_pushes_new (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id   TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        issue_key TEXT NOT NULL,
        kind      TEXT NOT NULL CHECK (kind IN ('comment', 'status', 'fields', 'worklog', 'subtasks')),
        detail    TEXT NOT NULL DEFAULT '',
        sent_at   TEXT NOT NULL
    );
    INSERT INTO jira_pushes_new(id, task_id, issue_key, kind, detail, sent_at)
        SELECT id, task_id, issue_key, kind, detail, sent_at FROM jira_pushes;
    DROP TABLE jira_pushes;
    ALTER TABLE jira_pushes_new RENAME TO jira_pushes;
    CREATE INDEX idx_jira_pushes_task ON jira_pushes(task_id);
    """,
    # 6: divergências. Quando o Jira muda o título ou a previsão e o usuário já tinha mudado o dele, o do usuário
    # é mantido e o campo fica anotado aqui ("title", "estimate") até ele escolher.
    "ALTER TABLE jira_links ADD COLUMN conflicts TEXT NOT NULL DEFAULT '';",
]

SCHEMA_VERSION = len(MIGRATIONS)


def new_id():
    return uuid.uuid4().hex[:12]


def timestamp(dt=None):
    return (dt or datetime.now()).isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn):
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Banco na versão {current}, mais nova que a suportada ({SCHEMA_VERSION})."
        )
    for version in range(current, SCHEMA_VERSION):
        # executescript faz COMMIT implícito; a versão só sobe se o script inteiro rodar.
        conn.executescript(MIGRATIONS[version])
        conn.execute(f"PRAGMA user_version = {version + 1}")
        conn.commit()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def ensure_default_group(conn, now=None):
    """Retorna o id do grupo padrão, criando-o se ainda não houver grupo algum."""
    group_id = get_meta(conn, "default_group_id")
    if group_id and conn.execute("SELECT 1 FROM groups WHERE id = ?", (group_id,)).fetchone():
        return group_id
    row = conn.execute(
        "SELECT id FROM groups WHERE archived = 0 ORDER BY position, created_at LIMIT 1"
    ).fetchone()
    if row:
        group_id = row["id"]
    else:
        group_id = new_id()
        conn.execute(
            "INSERT INTO groups(id, name, color, position, created_at) VALUES (?, ?, ?, 0, ?)",
            (group_id, DEFAULT_GROUP_NAME, DEFAULT_GROUP_COLOR, timestamp(now)),
        )
    set_meta(conn, "default_group_id", group_id)
    conn.commit()
    return group_id


def import_legacy_tasks(conn, legacy_path, now=None):
    """Importa o tasks.json do app antigo uma única vez.

    Formato antigo: [{"id": "...", "title": "...", "done": bool}, ...].
    As tarefas vão para o grupo padrão, sem data. O arquivo é renomeado para
    tasks.json.bak para não ser importado de novo. Retorna quantas tarefas entraram.
    """
    legacy_path = Path(legacy_path)
    if get_meta(conn, "legacy_imported") or not legacy_path.exists():
        return 0
    try:
        data = json.loads(legacy_path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        data = None
    if not isinstance(data, list):
        # Arquivo ilegível: preserva-o intacto e não tenta de novo.
        set_meta(conn, "legacy_imported", "unreadable")
        conn.commit()
        return 0

    group_id = ensure_default_group(conn, now)
    created = timestamp(now)
    imported = 0
    with conn:
        for position, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            task_id = str(item.get("id") or new_id())
            if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
                task_id = new_id()
            done = bool(item.get("done"))
            conn.execute(
                "INSERT INTO tasks(id, group_id, title, status, position, created_at, done_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, group_id, title, "done" if done else "todo", position,
                 created, created if done else None),
            )
            imported += 1
        set_meta(conn, "legacy_imported", created)

    backup = legacy_path.with_name(legacy_path.name + ".bak")
    try:
        legacy_path.replace(backup)
    except OSError:
        pass
    return imported


def open_database(data_dir, now=None):
    """Abre (ou cria) o banco em data_dir, aplica migrações e importa dados antigos."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(data_dir / DB_FILENAME)
    migrate(conn)
    import_legacy_tasks(conn, data_dir / LEGACY_TASKS_FILENAME, now)
    ensure_default_group(conn, now)
    return conn
