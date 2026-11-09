import unittest

from datetime import date, datetime

from pomodoro.ui.format import (delta_text, format_clock, format_date_eyebrow, format_minutes,
                                describe_day, estimate_note, format_real, interval_text, parse_duration, parse_signed_minutes,
                                phase_eyebrow, pomodoros_estimate, progress_note, session_line)
from pomodoro.timer import Phase


class FormatTest(unittest.TestCase):
    def test_format_minutes_matches_the_design(self):
        cases = {0: "0m", 5: "5m", 45: "45m", 60: "1h", 65: "1h 05m", 80: "1h 20m",
                 90: "1h 30m", 130: "2h 10m", 270: "4h 30m", 1440: "24h"}
        for minutes, expected in cases.items():
            self.assertEqual(format_minutes(minutes), expected, minutes)

    def test_format_minutes_rounds_and_clamps(self):
        self.assertEqual(format_minutes(44.6), "45m")
        self.assertEqual(format_minutes(-5), "0m")

    def test_format_real(self):
        self.assertEqual(format_real(0), "—")
        self.assertEqual(format_real(None), "—")
        self.assertEqual(format_real(20), "<1m")
        self.assertEqual(format_real(90), "2m")
        self.assertEqual(format_real(50 * 60), "50m")
        self.assertEqual(format_real(3905 * 1), "1h 05m")

    def test_format_clock(self):
        self.assertEqual(format_clock(932), "15:32")
        self.assertEqual(format_clock(0), "00:00")
        self.assertEqual(format_clock(25 * 60), "25:00")
        self.assertEqual(format_clock(5400), "1:30:00")
        self.assertEqual(format_clock(-130), "+02:10")

    def test_delta_text(self):
        self.assertEqual(delta_text(15 * 60, 20), ("↓5m", "under"))
        self.assertEqual(delta_text(62 * 60, 50), ("↑12m", "over"))
        self.assertEqual(delta_text(20 * 60, 20), ("", "even"))
        self.assertEqual(delta_text(0, 20), ("", "even"))
        self.assertEqual(delta_text(600, None), ("", "even"))
        self.assertEqual(delta_text(95 * 60, 30), ("↑1h 05m", "over"))

    def test_pomodoros_estimate(self):
        self.assertEqual(pomodoros_estimate(90), 4)
        self.assertEqual(pomodoros_estimate(45), 2)
        self.assertEqual(pomodoros_estimate(25), 1)
        self.assertEqual(pomodoros_estimate(26), 2)
        self.assertEqual(pomodoros_estimate(0), 0)
        self.assertEqual(pomodoros_estimate(None), 0)
        self.assertEqual(pomodoros_estimate(100, work_min=50), 2)


class DateTest(unittest.TestCase):
    def test_eyebrow(self):
        self.assertEqual(format_date_eyebrow(date(2026, 11, 9)), "SEGUNDA, 9 DE NOVEMBRO")
        self.assertEqual(format_date_eyebrow(date(2026, 11, 10)), "TERÇA, 10 DE NOVEMBRO")
        self.assertEqual(format_date_eyebrow(date(2026, 3, 1)), "DOMINGO, 1 DE MARÇO")
        self.assertEqual(format_date_eyebrow(date(2026, 12, 25)), "SEXTA, 25 DE DEZEMBRO")


class TimerTextTest(unittest.TestCase):
    def test_eyebrow_for_work(self):
        self.assertEqual(phase_eyebrow(Phase.WORK, True, True, 3, 4), "EM FOCO · POMODORO 3 DE 4")
        self.assertEqual(phase_eyebrow(Phase.WORK, True, True, 3, 4, compact=True), "EM FOCO · POMODORO 3/4")
        self.assertEqual(phase_eyebrow(Phase.WORK, False, True, 3, 4), "PAUSADO · POMODORO 3 DE 4")
        self.assertEqual(phase_eyebrow(Phase.WORK, False, False, 1, 4), "PRONTO PARA FOCAR · POMODORO 1 DE 4")
        self.assertEqual(phase_eyebrow(Phase.WORK, True, True, 2, 4, overtime=True), "TEMPO EXTRA · POMODORO 2 DE 4")

    def test_eyebrow_for_breaks(self):
        self.assertEqual(phase_eyebrow(Phase.SHORT_BREAK, True, True, 1, 4), "PAUSA CURTA")
        self.assertEqual(phase_eyebrow(Phase.LONG_BREAK, False, False, 1, 4), "PAUSA LONGA · PRONTA")
        self.assertEqual(phase_eyebrow(Phase.SHORT_BREAK, False, True, 1, 4), "PAUSA CURTA · PAUSADA")

    def test_progress_note(self):
        now = datetime(2026, 11, 9, 15, 0)
        text, fraction, kind = progress_note(50 * 60, 90, True, now)
        self.assertEqual((kind, round(fraction, 3)), ("ok", 0.556))
        self.assertEqual(text, "Faltam ~40m do previsto. Se mantiver o ritmo, termina por volta de 15:40.")
        self.assertEqual(progress_note(50 * 60, 90, False, now)[0], "Faltam ~40m do previsto.")
        text, fraction, kind = progress_note(102 * 60, 90, True, now)
        self.assertEqual((text, fraction, kind), ("Passou 12m do previsto.", 1.0, "over"))
        self.assertEqual(progress_note(0, None, True, now)[2], "none")
        self.assertEqual(progress_note(90 * 60 + 10, 90, True, now)[0], "Passou 1m do previsto.")
        self.assertEqual(progress_note(89 * 60 + 40, 90, False, now)[0], "Faltam ~1m do previsto.")

    def test_interval_text(self):
        item = {"label": "Pausa curta", "seconds": 300, "start": datetime(2026, 11, 9, 15, 48)}
        self.assertEqual(interval_text(item), "Pausa curta de 5 min às 15:48")


class DescribeDayTest(unittest.TestCase):
    def test_labels(self):
        today = date(2026, 11, 9)
        self.assertEqual(describe_day(today, today), "Hoje, 9 nov")
        self.assertEqual(describe_day(date(2026, 11, 10), today), "Amanhã, 10 nov")
        self.assertEqual(describe_day(date(2026, 11, 12), today), "qui, 12 nov")
        self.assertEqual(describe_day(date(2026, 11, 8), today), "dom, 8 nov")
        self.assertEqual(describe_day(date(2026, 12, 1), today), "ter, 1 dez")
        self.assertEqual(describe_day(None, today), "Sem data")


class EstimateNoteTest(unittest.TestCase):
    def test_notes(self):
        self.assertEqual(estimate_note(90, 90), ("≈ 4 pomodoros · soma das subtarefas: 1h 30m ✓", True))
        self.assertEqual(estimate_note(90, 80), ("≈ 4 pomodoros · ⚠ as subtarefas somam 1h 20m", False))
        self.assertEqual(estimate_note(25, None), ("≈ 1 pomodoro", True))
        self.assertEqual(estimate_note(None, 55), ("Sem previsão própria · as subtarefas somam 55m", True))
        self.assertTrue(estimate_note(0, None)[0].startswith("Sem previsão ainda"))
        self.assertEqual(estimate_note(100, None, work_min=50), ("≈ 2 pomodoros", True))


class SignedMinutesTest(unittest.TestCase):
    def test_parse(self):
        cases = {"+10": 10, "10": 10, "-5m": -5, "- 5": -5, "1h": 60, "-1h30": -90, " +1:30 ": 90}
        for text, expected in cases.items():
            self.assertEqual(parse_signed_minutes(text), expected, text)
        for text in ("", "0", "-0", "abc", "+", "--5", None):
            self.assertIsNone(parse_signed_minutes(text), repr(text))


class SessionLineTest(unittest.TestCase):
    def line(self, **kwargs):
        session = {"kind": "work", "started_at": "2026-11-09T14:05:00", "ended_at": "2026-11-09T14:30:00",
                   "seconds": 1500, "interrupted": 0, "subtask_title": None, "note": ""}
        session.update(kwargs)
        return session_line(session)

    def test_kinds(self):
        self.assertEqual(self.line(subtask_title="Levantar números"),
                         ("14:05–14:30", "Levantar números · 25m", "normal"))
        self.assertEqual(self.line(), ("14:05–14:30", "25m", "normal"))
        self.assertEqual(self.line(interrupted=1, seconds=300, ended_at="2026-11-09T14:10:00"),
                         ("14:05–14:10", "5m  ⚠ interrompido", "interrupted"))
        self.assertEqual(self.line(ended_at=None, subtask_title="Gráficos"),
                         ("14:05–agora", "Gráficos · em andamento", "open"))
        self.assertEqual(self.line(kind="manual", seconds=-300, note="Ajuste manual"),
                         ("09/11 14:05", "Ajuste manual · −5m", "manual"))
        self.assertEqual(self.line(kind="manual", seconds=600, note="")[1], "Ajuste manual · +10m")


class ParseDurationTest(unittest.TestCase):
    def test_accepted_formats(self):
        cases = {
            "90": 90, "45m": 45, "45 min": 45, "1h30": 90, "1h 30m": 90, "1H30M": 90,
            "1:30": 90, "0:45": 45, "2h": 120, "2 horas": 120, "1,5h": 90, "1.5h": 90,
            "  25  ": 25, "0": 0, "1h 5": 65,
        }
        for text, expected in cases.items():
            self.assertEqual(parse_duration(text), expected, text)

    def test_rejected(self):
        for text in ("", "   ", None, "abc", "h", "1:75", "-5", "1h30x", "um"):
            self.assertIsNone(parse_duration(text), repr(text))

    def test_round_trip_with_format(self):
        for minutes in (5, 45, 60, 65, 90, 270):
            self.assertEqual(parse_duration(format_minutes(minutes)), minutes)


if __name__ == "__main__":
    unittest.main()
