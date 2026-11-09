"""Ajuda para os testes de IA: cria tarefas concluídas com previsto e real no histórico."""

import tempfile
from datetime import datetime
from pathlib import Path

from pomodoro import db
from pomodoro.repository import Repository

from .test_repository import FakeClock


class Seed:
    def __init__(self, today=datetime(2026, 11, 9, 14, 0, 0)):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock(today)
        self.conn = db.open_database(Path(self._tmp.name), self.clock())
        self.repo = Repository(self.conn, now=self.clock)
        self.work = self.repo.create_group("Trabalho", color="#5B5BD6")
        self.home = self.repo.create_group("Casa", color="#3DAA7D")

    def close(self):
        self.conn.close()
        self._tmp.cleanup()

    def done(self, group, title, estimate, real, day="2026-11-05", hour=10, subtasks=(), interrupted=0,
             use_subtask_estimate=False):
        """Tarefa concluída em `day` com previsto/real em minutos. subtasks: [(título, previsto)]."""
        task = self.repo.create_task(group["id"], title, estimate_min=None if use_subtask_estimate else estimate,
                                     scheduled_for=day)
        for sub_title, sub_estimate in subtasks:
            self.repo.add_subtask(task["id"], sub_title, sub_estimate)
        started = datetime.fromisoformat(f"{day}T{hour:02d}:00:00")
        session = self.repo.start_session("work", task_id=task["id"], started_at=started)
        self.repo.end_session(session, int(real * 60), completed_phase=True, ended_at=started)
        for index in range(interrupted):
            extra = self.repo.start_session("work", task_id=task["id"], started_at=started.replace(minute=30 + index))
            self.repo.end_session(extra, 120, interrupted=True, ended_at=started)
        self.repo.set_task_status(task["id"], "done")
        self.conn.execute("UPDATE tasks SET done_at = ? WHERE id = ?", (f"{day}T18:00:00", task["id"]))
        return task

    def todo(self, group, title, estimate=None, day="2026-11-09"):
        return self.repo.create_task(group["id"], title, estimate_min=estimate, scheduled_for=day)
