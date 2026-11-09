import enum

from gi.repository import GLib


class Phase(enum.Enum):
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


PHASE_LABELS = {
    Phase.WORK: "Foco",
    Phase.SHORT_BREAK: "Pausa curta",
    Phase.LONG_BREAK: "Pausa longa",
}


class PomodoroTimer:
    def __init__(self, settings, on_tick, on_phase_change):
        self.settings = settings
        self.on_tick = on_tick
        self.on_phase_change = on_phase_change
        self.phase = Phase.WORK
        self.cycle = 1
        self.remaining = self._phase_duration(self.phase)
        self.running = False
        self._source_id = None

    def _phase_duration(self, phase):
        if phase == Phase.WORK:
            return self.settings["work_min"] * 60
        if phase == Phase.SHORT_BREAK:
            return self.settings["short_break_min"] * 60
        return self.settings["long_break_min"] * 60

    def start(self):
        if self.running:
            return
        self.running = True
        self._source_id = GLib.timeout_add_seconds(1, self._tick)
        self.on_tick()

    def pause(self):
        if not self.running:
            return
        self.running = False
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None
        self.on_tick()

    def toggle(self):
        if self.running:
            self.pause()
        else:
            self.start()

    def _tick(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self._advance_phase(auto=True)
        else:
            self.on_tick()
        return self.running

    def _advance_phase(self, auto):
        if self.phase == Phase.WORK:
            if self.cycle >= self.settings["cycles_before_long_break"]:
                self.phase = Phase.LONG_BREAK
                self.cycle = 1
            else:
                self.phase = Phase.SHORT_BREAK
        else:
            if self.phase == Phase.SHORT_BREAK:
                self.cycle += 1
            self.phase = Phase.WORK
        self.remaining = self._phase_duration(self.phase)
        self.on_phase_change(auto)
        self.on_tick()

    def skip(self):
        self._advance_phase(auto=False)

    def reset_phase(self):
        self.pause()
        self.remaining = self._phase_duration(self.phase)
        self.on_tick()

    def restart_all(self):
        self.pause()
        self.phase = Phase.WORK
        self.cycle = 1
        self.remaining = self._phase_duration(self.phase)
        self.on_tick()

    def update_settings(self, settings):
        self.settings = settings
        if not self.running:
            self.remaining = self._phase_duration(self.phase)
            self.on_tick()
