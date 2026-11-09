import unittest

from tests_gtk._support import find, near, pump, render, require_gtk

require_gtk()

from gi.repository import Gdk, Gtk  # noqa: E402

from pomodoro.ui.chart_math import bar_layout  # noqa: E402
from pomodoro.ui.theme import COLORS  # noqa: E402
from pomodoro.ui.widgets import (BarChart, ChoiceGroup, GroupDot, ProgressRing, StatusPill,  # noqa: E402
                                 TimeStepper, make_bar, make_toggle)


class ChoiceGroupTest(unittest.TestCase):
    ITEMS = [("today", "Hoje"), ("tomorrow", "Amanhã"), ("date", "Data…")]

    def test_initial_value_and_default(self):
        self.assertEqual(ChoiceGroup(self.ITEMS, "tomorrow").value, "tomorrow")
        self.assertEqual(ChoiceGroup(self.ITEMS).value, "today")

    def test_user_click_changes_value_and_emits_once(self):
        group = ChoiceGroup(self.ITEMS, "today")
        seen = []
        group.connect("changed", lambda _g, value: seen.append(value))
        group._buttons["date"].set_active(True)
        self.assertEqual((group.value, seen), ("date", ["date"]))
        self.assertFalse(group._buttons["today"].get_active())
        self.assertEqual(sum(b.get_active() for b in group._buttons.values()), 1)

    def test_clicking_the_selected_option_keeps_it_selected(self):
        group = ChoiceGroup(self.ITEMS, "today")
        seen = []
        group.connect("changed", lambda _g, value: seen.append(value))
        group._buttons["today"].set_active(False)
        self.assertTrue(group._buttons["today"].get_active())
        self.assertEqual(seen, [])

    def test_programmatic_set_is_silent_unless_asked(self):
        group = ChoiceGroup(self.ITEMS, "today")
        seen = []
        group.connect("changed", lambda _g, value: seen.append(value))
        group.set_value("tomorrow")
        self.assertEqual(seen, [])
        group.set_value("date", emit=True)
        self.assertEqual(seen, ["date"])
        with self.assertRaises(ValueError):
            group.set_value("ontem")

    def test_styles(self):
        segmented = ChoiceGroup(self.ITEMS, style_name="segmented")
        self.assertTrue(segmented.get_style_context().has_class("segmented"))
        chips = ChoiceGroup(self.ITEMS, style_name="chips-pill")
        button = chips._buttons["today"].get_style_context()
        self.assertTrue(button.has_class("chip") and button.has_class("chip-pill"))
        with self.assertRaises(ValueError):
            ChoiceGroup(self.ITEMS, style_name="outro")


class TimeStepperTest(unittest.TestCase):
    def make(self, minutes=90, **kwargs):
        stepper = TimeStepper(minutes, **kwargs)
        self.seen = []
        stepper.connect("value-changed", lambda _s, value: self.seen.append(value))
        return stepper

    def test_shows_formatted_value(self):
        self.assertEqual(self.make(90)._entry.get_text(), "1h 30m")

    def test_buttons_step_and_emit(self):
        stepper = self.make(90, step=5)
        stepper._plus.clicked()
        stepper._plus.clicked()
        stepper._minus.clicked()
        self.assertEqual((stepper.minutes, self.seen), (95, [95, 100, 95]))
        self.assertEqual(stepper._entry.get_text(), "1h 35m")

    def test_limits_disable_buttons(self):
        stepper = self.make(5, step=5, minimum=0, maximum=10)
        stepper._minus.clicked()
        self.assertFalse(stepper._minus.get_sensitive())
        stepper._plus.clicked()
        stepper._plus.clicked()
        self.assertFalse(stepper._plus.get_sensitive())
        self.assertEqual(stepper.minutes, 10)
        stepper._plus.clicked()                      # já no máximo: nada muda
        self.assertEqual(self.seen, [0, 5, 10])

    def test_typed_text_is_parsed_and_clamped(self):
        stepper = self.make(60, maximum=240)
        stepper._entry.set_text("1h45")
        stepper._entry.activate()
        self.assertEqual((stepper.minutes, stepper._entry.get_text()), (105, "1h 45m"))
        stepper._entry.set_text("10h")
        stepper._entry.activate()
        self.assertEqual(stepper.minutes, 240)
        self.assertEqual(self.seen, [105, 240])

    def test_invalid_text_reverts(self):
        stepper = self.make(60)
        stepper._entry.set_text("abc")
        stepper._entry.activate()
        self.assertEqual((stepper.minutes, stepper._entry.get_text(), self.seen), (60, "1h", []))

    def test_set_minutes_is_silent_by_default(self):
        stepper = self.make(60)
        stepper.set_minutes(45)
        self.assertEqual((stepper.minutes, self.seen), (45, []))

    def test_arrow_keys(self):
        stepper = self.make(60, step=5)
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.KEY_Up
        self.assertTrue(stepper._on_key(stepper._entry, event))
        event.keyval = Gdk.KEY_Down
        stepper._on_key(stepper._entry, event)
        self.assertEqual(self.seen, [65, 60])


class SmallWidgetsTest(unittest.TestCase):
    def test_status_pill(self):
        pill = StatusPill("done")
        context = pill.get_style_context()
        self.assertEqual((pill.get_text(), context.has_class("pill-done")), ("Concluída", True))
        pill.set_status("doing")
        self.assertEqual(pill.get_text(), "● Em foco")
        self.assertTrue(context.has_class("pill-doing") and not context.has_class("pill-done"))
        with self.assertRaises(ValueError):
            pill.set_status("feito")

    def test_toggle_callback(self):
        seen = []
        toggle = make_toggle(False, seen.append)
        toggle.set_active(True)
        toggle.set_active(False)
        self.assertEqual(seen, [True, False])
        self.assertTrue(toggle.get_style_context().has_class("toggle"))

    def test_bar_clamps_and_validates(self):
        bar = make_bar(1.7, "green")
        self.assertEqual(bar.get_fraction(), 1.0)
        self.assertTrue(bar.get_style_context().has_class("bar-green"))
        self.assertEqual(make_bar(-3).get_fraction(), 0.0)
        with self.assertRaises(ValueError):
            make_bar(0.5, "roxo")

    def test_group_dot_color(self):
        dot = GroupDot("#3DAA7D")
        self.assertEqual(dot.color, "#3DAA7D")
        dot.set_color("#E879A6")
        self.assertEqual(dot.color, "#E879A6")
        pixel = render(GroupDot("#E879A6", size=10), 10, 10)
        self.assertTrue(near(pixel(5, 5), "#E879A6"))


class RingDrawingTest(unittest.TestCase):
    def render_ring(self, fraction, **kwargs):
        ring = ProgressRing(size=200, thickness=10, **kwargs)
        ring.set_fraction(fraction)
        return render(ring, 200, 200)

    def test_half_ring_is_colored_on_the_right_only(self):
        pixel = self.render_ring(0.5)
        # raio do centro da faixa = (200 - 10) / 2 = 95; centro em (100, 100)
        self.assertTrue(near(pixel(100 + 95, 100), COLORS["focus"]))        # 3h: dentro do arco
        self.assertTrue(near(pixel(100, 100 + 95), COLORS["focus"]))        # 6h: fim do arco
        self.assertTrue(near(pixel(100 - 95, 100), COLORS["dark_track"]))   # 9h: só trilho
        self.assertTrue(near(pixel(100, 100 - 95), COLORS["focus"]))        # 12h: início do arco

    def test_zero_fraction_is_only_the_track(self):
        pixel = self.render_ring(0.0)
        for x, y in ((195, 100), (100, 195), (5, 100)):
            self.assertTrue(near(pixel(x, y), COLORS["dark_track"]), (x, y))

    def test_full_ring_and_light_track(self):
        pixel = self.render_ring(1.0)
        for x, y in ((195, 100), (5, 100), (100, 5)):
            self.assertTrue(near(pixel(x, y), COLORS["focus"]), (x, y))
        light = self.render_ring(0.0, dark=False)
        self.assertTrue(near(light(195, 100), COLORS["chip"]))

    def test_fraction_is_clamped_and_color_changes(self):
        ring = ProgressRing()
        ring.set_fraction(3)
        self.assertEqual(ring.fraction, 1.0)
        ring.set_fraction(-1)
        self.assertEqual(ring.fraction, 0.0)
        ring.set_fraction(1.0)
        ring.set_color(COLORS["green"])
        self.assertTrue(near(render(ring, 200, 200)(195, 100), COLORS["green"]))

    def test_texts(self):
        ring = ProgressRing()
        ring.set_time("15:32")
        ring.set_caption("de 25:00")
        self.assertEqual((ring.time_label.get_text(), ring.caption_label.get_text()), ("15:32", "de 25:00"))


class BarChartDrawingTest(unittest.TestCase):
    DAYS = [
        {"label": "Seg", "planned": 100, "real": 120},
        {"label": "Ter", "planned": 150, "real": 140},
    ]

    def test_bars_are_drawn_where_the_layout_says(self):
        width, height = 300, 200
        chart = BarChart(self.DAYS, height=height)
        pixel = render(chart, width, height)
        layout = bar_layout(self.DAYS, width, height)
        expected = [("planned", COLORS["primary_soft"]), ("real_over", COLORS["focus"])]
        for (kind, color), bar in zip(expected, layout[0]["bars"]):
            self.assertEqual(bar["kind"], kind)
            self.assertTrue(near(pixel(int(bar["x"] + bar["w"] / 2), int(bar["y"] + bar["h"] - 3)), color), kind)
        ter_real = layout[1]["bars"][1]
        self.assertEqual(ter_real["kind"], "real_ok")
        self.assertTrue(near(pixel(int(ter_real["x"] + ter_real["w"] / 2), int(ter_real["y"] + ter_real["h"] - 3)),
                             COLORS["primary"]))
        self.assertTrue(near(pixel(2, 2), COLORS["bg"]))                      # fora das barras: fundo

    def test_set_days_validates_and_copies(self):
        chart = BarChart()
        with self.assertRaises(ValueError):
            chart.set_days([{"label": "Seg", "planned": 1}])
        source = [{"label": "Seg", "planned": 10, "real": 20}]
        chart.set_days(source)
        source[0]["real"] = 999
        self.assertEqual(chart.days[0]["real"], 20)

    def test_tooltip_text(self):
        chart = BarChart(self.DAYS, height=200)
        render(chart, 300, 200)

        class Tip:
            text = None

            def set_text(self, text):
                self.text = text

        tip = Tip()
        layout = bar_layout(self.DAYS, 300, 200)
        x = int((layout[1]["pair_x0"] + layout[1]["pair_x1"]) / 2)
        self.assertTrue(chart._on_tooltip(chart, x, 50, False, tip))
        self.assertEqual(tip.text, "Ter: previsto 2h 30m · real 2h 20m")
        self.assertFalse(chart._on_tooltip(chart, 1, 50, False, Tip()))


if __name__ == "__main__":
    unittest.main()


from datetime import date  # noqa: E402

from pomodoro.ui.widgets import DatePicker, Select  # noqa: E402


class ChoiceGroupEmptyTest(unittest.TestCase):
    ITEMS = [(15, "15m"), (45, "45m")]

    def test_can_start_and_become_empty(self):
        group = ChoiceGroup(self.ITEMS, None, "chips", allow_empty=True)
        self.assertIsNone(group.value)
        self.assertFalse(any(b.get_active() for b in group._buttons.values()))
        seen = []
        group.connect("changed", lambda _g, value: seen.append(value))
        group._buttons[45].set_active(True)
        self.assertEqual((group.value, seen), (45, [45]))
        group.set_value(None)
        self.assertIsNone(group.value)
        self.assertFalse(any(b.get_active() for b in group._buttons.values()))
        self.assertEqual(seen, [45])                                      # programático: silencioso

    def test_strict_group_still_refuses_none(self):
        group = ChoiceGroup(self.ITEMS, 15, "chips")
        with self.assertRaises(ValueError):
            group.set_value(None)


class SelectTest(unittest.TestCase):
    ITEMS = [("a", "Trabalho"), ("b", "Casa"), (None, "Nenhum")]

    def test_value_text_and_changes(self):
        select = Select(self.ITEMS, "b")
        seen = []
        select.connect("changed", lambda _s, value: seen.append(value))
        self.assertEqual((select.value, select.get_text()), ("b", "Casa"))
        select._buttons["a"].clicked()
        self.assertEqual((select.value, select.get_text(), seen), ("a", "Trabalho", ["a"]))
        select._buttons[None].clicked()                                    # None também é um valor válido
        self.assertEqual((select.value, seen), (None, ["a", None]))
        select.set_value("b")
        self.assertEqual(seen, ["a", None])                                # silencioso por padrão
        self.assertTrue(select._buttons["b"].get_active() and not select._buttons["a"].get_active())

    def test_default_first_and_invalid(self):
        self.assertEqual(Select(self.ITEMS).value, "a")
        with self.assertRaises(ValueError):
            Select(self.ITEMS).set_value("x")

    def test_set_items_replaces_options(self):
        select = Select(self.ITEMS, "b")
        select.set_items([("x", "Novo")], "x")
        self.assertEqual((select.items, select.value, select.get_text()), ([("x", "Novo")], "x", "Novo"))


class DatePickerTest(unittest.TestCase):
    TODAY = date(2026, 11, 9)

    def make(self, day=None):
        picker = DatePicker(day, today=lambda: self.TODAY)
        self.seen = []
        picker.connect("changed", lambda _p, value: self.seen.append(value))
        return picker

    def test_labels(self):
        self.assertEqual(self.make(self.TODAY).get_text(), "Hoje, 9 nov")
        self.assertEqual(self.make(date(2026, 11, 10)).get_text(), "Amanhã, 10 nov")
        self.assertEqual(self.make(None).get_text(), "Sem data")

    def test_shortcut_buttons(self):
        picker = self.make(None)
        buttons = {b.get_label(): b for b in find(picker.popover, lambda w: isinstance(w, Gtk.Button))}
        buttons["Amanhã"].clicked()
        self.assertEqual((picker.date, picker.get_text()), (date(2026, 11, 10), "Amanhã, 10 nov"))
        buttons["Hoje"].clicked()
        buttons["Sem data"].clicked()
        self.assertEqual(self.seen, [date(2026, 11, 10), self.TODAY, None])

    def test_calendar_click_selects_but_month_navigation_does_not(self):
        picker = self.make(self.TODAY)
        picker._calendar.select_day(12)
        self.assertEqual((picker.date, self.seen), (date(2026, 11, 12), [date(2026, 11, 12)]))
        picker._calendar.select_month(11, 2026)                           # navegar para dezembro
        pump()
        self.assertEqual(picker.date, date(2026, 11, 12))
        self.assertEqual(len(self.seen), 1)
        picker._calendar.select_day(24)
        self.assertEqual(picker.date, date(2026, 12, 24))

    def test_without_none_option(self):
        picker = DatePicker(self.TODAY, today=lambda: self.TODAY, allow_none=False)
        labels_ = [b.get_label() for b in find(picker.popover, lambda w: isinstance(w, Gtk.Button))]
        self.assertNotIn("Sem data", labels_)

    def test_set_date_is_silent_by_default(self):
        picker = self.make(None)
        picker.set_date(self.TODAY)
        self.assertEqual(self.seen, [])
        picker.set_date(date(2026, 11, 11), emit=True)
        self.assertEqual(self.seen, [date(2026, 11, 11)])
