import tempfile
import unittest
from datetime import date

from tests_gtk._support import labels, make_controller, pump, require_gtk, with_class

require_gtk()

from pomodoro import planning  # noqa: E402
from pomodoro.ui.pages.plan_tomorrow import PlanTomorrowPage, capacity_caption, leftover_subtitle, short_date  # noqa: E402


class PlanPageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.controller = make_controller(self._tmp.name, end_of_day_reminder="")
        self.repo = self.controller.repo
        self.work = self.repo.update_group(self.repo.default_group_id(), name="Trabalho", color="#5B5BD6")
        self.home = self.repo.create_group("Casa", color="#3DAA7D")
        self.page = PlanTomorrowPage(self.controller)
        self.page.show_all()
        self.page.refresh()                 # os cartões "escondidos" só se ajustam depois de mostrar

    def tearDown(self):
        self.page.destroy()
        self.controller.shutdown()
        self._tmp.cleanup()

    def texts(self):
        return labels(self.page)

    def step_texts(self):
        return [w.get_text() for w in with_class(self.page, "step")]

    def test_pure_helpers(self):
        self.assertEqual(short_date(date(2026, 11, 14)), "Sáb, 14")
        cap = planning.capacity([planning.PlanItem("1", "g", "a", "#000000", 245, 285, False)], 360)
        self.assertEqual(capacity_caption(cap),
                         "Você previu 4h 05m · ✦ IA estima 4h 45m realista · sobra 1h 15m para pausas")
        over = planning.capacity([planning.PlanItem("1", "g", "a", "#000000", 400, 400, False)], 360)
        self.assertEqual(capacity_caption(over), "Você previu 6h 40m · passa 40m do tempo livre")
        self.assertEqual(capacity_caption(planning.capacity([], 360)), "Nada planejado para amanhã ainda.")
        item = planning.Leftover("1", "T", "Trabalho", "#000000", "Escrever relatório", 35, 1, True)
        self.assertEqual(leftover_subtitle(item), "Trabalho › Escrever relatório · prev 35m · adiada 1×")

    def test_empty_day(self):
        self.assertTrue(self.page.empty_card.get_visible())
        self.assertFalse(self.page.leftover_box.get_visible())
        self.assertFalse(self.page.suggestion_card.get_visible())
        self.assertTrue(self.page.confirm_button.get_sensitive())
        self.assertEqual(self.step_texts(), ["✓ 1 Revisar", "2 Reanotar", "3 Confirmar"])
        self.assertIn("Amanhã, terça 10", self.texts())
        self.assertIn("Hoje, segunda", self.texts())
        self.assertIn("Tempo livre: 6h ✎", self.texts())

    def build_day(self):
        done = self.controller.add_task("Responder e-mails", 20, self.work["id"])
        session = self.repo.start_session("work", task_id=done["id"])
        self.repo.end_session(session, 18 * 60, completed_phase=True)
        self.controller.set_task_done(done["id"], True)
        a = self.controller.add_task("Revisar texto e enviar", 35, self.work["id"])
        b = self.controller.add_task("Preparar apresentação", 80, self.work["id"])
        self.repo.postpone_task(b["id"], "2026-11-09")
        c = self.controller.add_task("Lavar roupa", 30, self.home["id"])
        return a, b, c

    def test_review_card_and_leftovers(self):
        a, b, c = self.build_day()
        self.page.refresh()
        texts = self.texts()
        self.assertIn("1 de 4", texts)
        self.assertIn("2h 45m → 18m", texts)
        self.assertIn("Trabalho · prev 35m", texts)
        self.assertIn("Trabalho · prev 1h 20m · adiada 1×", texts)
        self.assertEqual(len(self.page._leftover_rows), 3)
        self.assertEqual(self.page.destinations, {a["id"]: "2026-11-10", b["id"]: "2026-11-10", c["id"]: "2026-11-10"})
        for row in self.page._leftover_rows.values():
            self.assertTrue(row.tomorrow_button.get_style_context().has_class("btn-primary"))
            self.assertFalse(row.discard_button.get_style_context().has_class("btn-primary"))
        self.assertTrue(self.page.suggestion_card.get_visible())
        self.assertIn("“Preparar apresentação” já foi adiada 1 vez", self.page.suggestion_text.get_text())

    def test_choosing_destinations_updates_buttons_and_suggestion(self):
        a, b, c = self.build_day()
        self.page.refresh()
        self.page.on_destination(b["id"], planning.DISCARD)
        self.page.on_destination(c["id"], "2026-11-14")
        rows = self.page._leftover_rows
        self.assertTrue(rows[b["id"]].discard_button.get_style_context().has_class("btn-primary"))
        self.assertFalse(rows[b["id"]].tomorrow_button.get_style_context().has_class("btn-primary"))
        self.assertTrue(rows[c["id"]].other_button.get_style_context().has_class("btn-primary"))
        self.assertEqual(rows[c["id"]].other_text.get_text(), "Sáb, 14")
        self.assertFalse(self.page.suggestion_card.get_visible())           # a adiada foi descartada
        self.page.on_destination(c["id"], "2026-11-09")                      # hoje não vale
        self.assertEqual(self.page.destinations[c["id"]], "2026-11-14")
        self.assertIn("depois de hoje", self.page.notice_label.get_text())

    def test_calendar_selection_chooses_the_date(self):
        _a, _b, c = self.build_day()
        self.page.refresh()
        row = self.page._leftover_rows[c["id"]]
        row.calendar.select_day(12)
        pump()
        self.assertEqual(self.page.destinations[c["id"]], "2026-11-12")

    def test_confirm_requires_a_destination_for_each(self):
        a, b, c = self.build_day()
        self.controller.apply_settings({"carry_over_unfinished": False})
        self.page.destinations = {}
        self.page.refresh()
        self.assertFalse(self.page.on_confirm())
        self.assertIn("Escolha o destino de “Revisar texto e enviar” e mais 2", self.page.notice_label.get_text())
        self.assertIsNone(self.repo.get_day_review("2026-11-09"))

    def test_confirm_applies_everything(self):
        a, b, c = self.build_day()
        self.page.refresh()
        self.page.on_destination(b["id"], planning.DISCARD)
        self.page.on_destination(c["id"], "2026-11-14")
        self.assertTrue(self.page.on_confirm())
        self.assertEqual(self.repo.get_task(a["id"])["scheduled_for"], "2026-11-10")
        self.assertEqual(self.repo.get_task(b["id"])["status"], "discarded")
        self.assertEqual(self.repo.get_task(c["id"])["scheduled_for"], "2026-11-14")
        self.assertTrue(self.page.confirmed_card.get_visible())
        self.assertFalse(self.page.confirm_button.get_sensitive())
        self.assertEqual(self.page.confirm_button.get_label(), "✓ Plano confirmado")
        self.assertEqual(self.step_texts(), ["✓ 1 Revisar", "✓ 2 Reanotar", "✓ 3 Confirmar"])
        self.assertIn("Revisar texto e enviar", self.texts())                   # já está na lista de amanhã
        self.assertEqual(len(self.page._leftover_rows), 0)

    def test_mood_is_saved(self):
        self.page.mood.set_value("good", emit=True)
        self.assertEqual(self.repo.get_day_review("2026-11-09")["mood"], "good")

    def test_tomorrow_list_capacity_and_quick_add(self):
        self.controller.add_to_tomorrow("Caminhada", 30, self.home["id"])
        self.page.refresh()
        self.assertIn("Caminhada", self.texts())
        self.assertIn("30m", self.texts())
        self.assertEqual(self.page.capacity_text.get_text(), "Você previu 30m · sobra 5h 30m para pausas")
        self.page.quick.title_entry.set_text("Estudar capítulo 4")
        self.page.quick.time_entry.set_text("1h")
        self.assertTrue(self.page.quick.submit())
        self.assertIn("Estudar capítulo 4", self.texts())
        self.assertEqual(self.page.quick.title_entry.get_text(), "")
        self.assertIn("Você previu 1h 30m", self.page.capacity_text.get_text())

    def test_free_time_edit(self):
        self.page.free_entry.set_text("4h30")
        self.page._on_free_time()
        self.assertIn("Tempo livre: 4h 30m ✎", self.texts())
        self.page.free_entry.set_text("abc")
        self.page._on_free_time()
        self.assertIn("Não entendi o tempo livre", self.page.notice_label.get_text())
        self.assertEqual(self.controller.tomorrow_plan()["free_min"], 270)

    def test_over_capacity_is_flagged(self):
        self.controller.set_tomorrow_free_minutes(60)
        self.controller.add_to_tomorrow("Grande", 120)
        self.page.refresh()
        self.assertIn("passa 1h do tempo livre", self.page.capacity_text.get_text())
        self.assertTrue(self.page.capacity_text.get_style_context().has_class("text-focus"))

    def test_drop_reorders_within_group_only(self):
        a = self.controller.add_to_tomorrow("A", 10, self.work["id"])
        b = self.controller.add_to_tomorrow("B", 10, self.work["id"])
        c = self.controller.add_to_tomorrow("C", 10, self.home["id"])
        self.page.refresh()
        self.page.on_row_dropped(b["id"], a["id"], False)
        self.assertEqual([i.title for i in self.controller.tomorrow_plan()["items"]], ["B", "A", "C"])
        self.page.refresh()
        self.page.on_row_dropped(c["id"], a["id"], False)                       # outro grupo: avisa e não muda
        self.assertIn("mesmo grupo", self.page.notice_label.get_text())
        self.assertEqual([i.title for i in self.controller.tomorrow_plan()["items"]], ["B", "A", "C"])

    def test_open_task_signal(self):
        a, b, c = self.build_day()
        self.page.refresh()
        seen = []
        self.page.connect("open-task", lambda _p, task_id: seen.append(task_id))
        self.page.suggestion_button.clicked()
        self.assertEqual(seen, [b["id"]])
        done = []
        self.page.connect("done", lambda *_: done.append(True))
        self.page.today_button.clicked()
        self.assertEqual(done, [True])

    def test_ai_estimates_shown_next_to_user_estimates(self):
        for index in range(4):
            task = self.controller.add_task(f"Escrever relatório {index}", 30, self.work["id"], day="2026-11-02")
            session = self.repo.start_session("work", task_id=task["id"])
            self.repo.end_session(session, 60 * 60, completed_phase=True)
            self.repo.set_task_status(task["id"], "done")
        self.controller.add_to_tomorrow("Escrever relatório novo", 30, self.work["id"])
        self.page.refresh()
        self.assertIn("✦ 1h", self.texts())
        self.assertIn("IA estima 1h realista", self.page.capacity_text.get_text())


if __name__ == "__main__":
    unittest.main()
