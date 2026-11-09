"""Máquina de fases do Pomodoro (foco, pausa curta, pausa longa).

O timer não conhece tarefas nem banco de dados: ele só conta o tempo e avisa o que acontece
por eventos (ver add_listener). Quem registra sessões é o tracking.Tracker.

Eventos (nome, dados):
  started / paused        o usuário (ou a regra de início automático) iniciou/pausou
  second                  passou 1 segundo com o timer rodando
  warning                 faltam `warn_before_end_min` minutos para o fim do foco
  overtime                o foco chegou a zero e segue contando (count_overtime)
  phase_ended             uma fase acabou: phase, completed, auto, reason, seconds, overtime_seconds
  phase_started           a nova fase começou: phase (timer.running já está no estado final)
"""

import enum
import logging
from datetime import datetime, timedelta

from .settings import DEFAULT_SETTINGS

log = logging.getLogger(__name__)


class Phase(enum.Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


PHASE_LABELS = {
    Phase.WORK: "Foco",
    Phase.SHORT_BREAK: "Pausa curta",
    Phase.LONG_BREAK: "Pausa longa",
}

BREAK_PHASES = (Phase.SHORT_BREAK, Phase.LONG_BREAK)


class GLibScheduler:
    """Dispara um callback a cada segundo no laço principal do GTK."""

    def add(self, callback):
        from gi.repository import GLib
        return GLib.timeout_add_seconds(1, callback)

    def remove(self, source_id):
        from gi.repository import GLib
        GLib.source_remove(source_id)


class PomodoroTimer:
    def __init__(self, settings, on_tick, on_phase_change, on_event=None, scheduler=None):
        self.settings = settings
        self.on_tick = on_tick
        self.on_phase_change = on_phase_change
        self._scheduler = scheduler or GLibScheduler()
        self._listeners = [on_event] if on_event else []
        self.overrides = {"work_min": None, "short_break_min": None}

        self.phase = Phase.WORK
        self.cycle = 1
        self.remaining = self._phase_duration(self.phase)
        self.running = False
        self.phase_elapsed = 0      # segundos contados na fase atual (inclui o tempo extra)
        self._overtime = False
        self._source_id = None
        self._generation = 0
        self._in_timeout = False

    # ---- configuração ---------------------------------------------------

    def _opt(self, key):
        return self.settings.get(key, DEFAULT_SETTINGS.get(key))

    def _phase_duration(self, phase):
        if phase == Phase.WORK:
            minutes = self.overrides["work_min"] or self._opt("work_min")
        elif phase == Phase.SHORT_BREAK:
            minutes = self.overrides["short_break_min"] or self._opt("short_break_min")
        else:
            minutes = self._opt("long_break_min")
        return minutes * 60

    @property
    def phase_total(self):
        """Duração total da fase atual, em segundos."""
        return self._phase_duration(self.phase)

    @property
    def started(self):
        """Já contou algum segundo nesta fase (ou seja, não está intacta)."""
        return self.phase_elapsed > 0

    @property
    def in_overtime(self):
        return self._overtime

    @property
    def overtime_seconds(self):
        return max(-self.remaining, 0) if self._overtime else 0

    def _is_pristine(self):
        """Fase ainda inteira, parada e sem nada contado: dá para trocar a duração à vontade."""
        return not self.running and not self._overtime and self.phase_elapsed == 0

    def set_overrides(self, work_min=None, short_break_min=None):
        """Duração própria do grupo da tarefa ativa (None = usar a configuração geral)."""
        pristine = self._is_pristine()
        new = {"work_min": work_min or None, "short_break_min": short_break_min or None}
        if new == self.overrides:
            return
        self.overrides = new
        if pristine:
            self.remaining = self._phase_duration(self.phase)
            self.on_tick()

    def update_settings(self, settings):
        pristine = self._is_pristine()
        self.settings = settings
        if pristine:
            self.remaining = self._phase_duration(self.phase)
            self.on_tick()

    # ---- eventos --------------------------------------------------------

    def add_listener(self, listener):
        self._listeners.append(listener)

    def _emit(self, name, **data):
        for listener in list(self._listeners):
            try:
                listener(name, **data)
            except Exception:  # um ouvinte com defeito não pode parar o relógio
                log.exception("erro no ouvinte do timer ao tratar %r", name)

    # ---- agendamento do segundo -----------------------------------------

    def _schedule(self):
        self.running = True
        self._generation += 1
        generation = self._generation
        self._source_id = self._scheduler.add(lambda: self._on_timeout(generation))

    def _unschedule(self):
        self.running = False
        self._generation += 1  # invalida qualquer callback pendente
        if self._source_id is not None:
            # Dentro do próprio callback a fonte morre quando ele devolve False.
            if not self._in_timeout:
                self._scheduler.remove(self._source_id)
            self._source_id = None

    def _on_timeout(self, generation):
        if generation != self._generation or not self.running:
            return False
        self._in_timeout = True
        try:
            self.tick()
        finally:
            self._in_timeout = False
        return generation == self._generation and self.running

    # ---- controles ------------------------------------------------------

    def start(self):
        if self.running:
            return
        self._schedule()
        self._emit("started")
        self.on_tick()

    def pause(self):
        if not self.running:
            return
        self._unschedule()
        self._emit("paused")
        self.on_tick()

    def toggle(self):
        if self.running:
            self.pause()
        else:
            self.start()

    def tick(self):
        """Avança 1 segundo. Chamado pelo agendador; público para os testes."""
        if not self.running:
            return
        self.phase_elapsed += 1
        self.remaining -= 1
        self._emit("second")

        if self.phase == Phase.WORK:
            warn = self._opt("warn_before_end_min") * 60
            if 0 < warn < self._phase_duration(Phase.WORK) and self.remaining == warn:
                self._emit("warning", remaining=warn)

        if self.remaining <= 0:
            if self.phase == Phase.WORK and self._opt("count_overtime"):
                if not self._overtime:
                    self._overtime = True
                    self._emit("overtime")
                self.on_tick()
                return
            self._advance_phase(auto=True)
            return
        self.on_tick()

    # ---- fases ----------------------------------------------------------

    def _next(self, phase, cycle):
        """Próxima fase e ciclo, sem alterar o estado (usado também para prever o dia)."""
        if phase == Phase.WORK:
            if cycle >= self._opt("cycles_before_long_break"):
                return Phase.LONG_BREAK, 1
            return Phase.SHORT_BREAK, cycle
        if phase == Phase.SHORT_BREAK:
            return Phase.WORK, cycle + 1
        return Phase.WORK, cycle

    def _end_phase_event(self, auto, reason):
        completed = self.remaining <= 0
        self._emit(
            "phase_ended", phase=self.phase, completed=completed, auto=auto,
            reason="auto" if auto else reason, seconds=self.phase_elapsed,
            overtime_seconds=self.overtime_seconds,
        )
        return completed

    def _advance_phase(self, auto, reason="skip"):
        self._end_phase_event(auto, reason)
        was_running = self.running
        self.phase, self.cycle = self._next(self.phase, self.cycle)
        self._overtime = False
        self.phase_elapsed = 0
        self.remaining = self._phase_duration(self.phase)

        if auto:
            key = "auto_start_breaks" if self.phase in BREAK_PHASES else "auto_start_work"
            should_run = bool(self._opt(key))
        else:
            should_run = was_running
        if should_run and not self.running:
            self._schedule()
        elif not should_run and self.running:
            self._unschedule()

        self.on_phase_change(auto)
        self._emit("phase_started", phase=self.phase)
        self.on_tick()

    def skip(self):
        self._advance_phase(auto=False)

    def _restart_phase(self, phase, cycle, reason):
        self._end_phase_event(auto=False, reason=reason)
        was_running = self.running
        if was_running:
            self._unschedule()
        self.phase, self.cycle = phase, cycle
        self._overtime = False
        self.phase_elapsed = 0
        self.remaining = self._phase_duration(self.phase)
        if was_running:
            self._emit("paused")
        self.on_tick()

    def reset_phase(self):
        self._restart_phase(self.phase, self.cycle, "reset")

    def restart_all(self):
        self._restart_phase(Phase.WORK, 1, "restart")

    def extend(self, seconds):
        """Soma tempo à fase atual (ex.: "+1 min" na pausa). Valores negativos não deixam passar de zero."""
        if seconds == 0:
            return
        self.remaining = max(self.remaining + seconds, 1) if seconds < 0 else self.remaining + seconds
        self.on_tick()

    # ---- previsão -------------------------------------------------------

    def next_intervals(self, now=None, count=3):
        """Próximas fases com horário de início/fim, supondo que o timer siga rodando."""
        start = (now or datetime.now()) + timedelta(seconds=max(self.remaining, 0))
        phase, cycle = self.phase, self.cycle
        result = []
        for _ in range(count):
            phase, cycle = self._next(phase, cycle)
            seconds = self._phase_duration(phase)
            end = start + timedelta(seconds=seconds)
            result.append({
                "phase": phase, "label": PHASE_LABELS[phase],
                "seconds": seconds, "start": start, "end": end,
            })
            start = end
        return result
