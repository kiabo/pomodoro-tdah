"""Envio ao Jira: monta a PRÉ-VISUALIZAÇÃO do que iria e executa exatamente o que foi confirmado. Sem GTK.

Nada aqui roda sozinho: cada envio nasce de um pedido do usuário, passa por uma janela que mostra o
conteúdo e só é executado com preview["confirmed"] = True (marcado pela janela ao clicar em Enviar).
"""

from datetime import datetime

from .client import JiraError

COMMENT, STATUS, FIELDS, WORKLOG, SUBTASKS = "comment", "status", "fields", "worklog", "subtasks"
MIN_WORKLOG_SECONDS = 60
WORKLOG_COMMENT = "Pomodoro TDAH"


def _minutes_text(minutes):
    if not minutes:
        return "sem previsão"
    hours, rest = divmod(minutes, 60)
    return (f"{hours}h" if hours else "") + (f" {rest}min" if rest and hours else (f"{rest}min" if rest else ""))


def comment_preview(task, link):
    text = (task["notes"] or "").strip()
    if not text:
        raise ValueError("Esta tarefa não tem notas para enviar.")
    return {"kind": COMMENT, "task_id": task["id"], "issue_key": link["issue_key"], "text": text,
            "confirmed": False}


def fields_preview(task, link):
    """Diferenças entre a tarefa e a issue (título e previsão), cada uma marcável. ValueError se não há nenhuma."""
    changes = []
    if task["title"].strip() != (link["remote_title"] or "").strip():
        changes.append({"field": "title", "label": "Título", "before": link["remote_title"],
                        "after": task["title"].strip(), "value": task["title"].strip(), "selected": True})
    local, remote = task["estimate_min"], link["remote_estimate_min"]
    if local and local != remote:
        changes.append({"field": "estimate", "label": "Previsão", "before": _minutes_text(remote),
                        "after": _minutes_text(local), "value": local, "selected": True})
    if not changes:
        raise ValueError("O título e a previsão já são iguais aos do Jira.")
    return {"kind": FIELDS, "task_id": task["id"], "issue_key": link["issue_key"], "changes": changes,
            "confirmed": False}


def status_preview(task, link, transitions):
    if not transitions:
        raise ValueError("O Jira não oferece mudança de status para esta issue agora.")
    return {"kind": STATUS, "task_id": task["id"], "issue_key": link["issue_key"],
            "current": link["remote_status"], "options": transitions, "transition_id": None, "confirmed": False}


def jira_started(iso):
    """'2026-11-11T14:00:00' (hora local) -> '2026-11-11T14:00:00.000-0300', como o Jira pede."""
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%dT%H:%M:%S.000%z")


def worklog_preview(task, link, sessions):
    """Agrupa as sessões ainda não lançadas por dia (um lançamento por dia). ValueError se não há nada a lançar.

    O tempo do dia é a soma das sessões (ajustes manuais negativos descontam). Dias com menos de 1 minuto
    não entram, porque o Jira não aceita.
    """
    by_day = {}
    for session in sessions:
        by_day.setdefault(session["started_at"][:10], []).append(session)
    days, skipped = [], 0
    for day, items in sorted(by_day.items()):
        seconds = sum(i["seconds"] for i in items)
        if seconds < MIN_WORKLOG_SECONDS:
            skipped += max(seconds, 0)
            continue
        first = min(items, key=lambda i: i["started_at"])
        days.append({"day": day, "seconds": seconds, "sessions": len(items), "started": jira_started(first["started_at"]),
                     "session_ids": [i["id"] for i in items], "selected": True})
    if not days:
        raise ValueError("Não há tempo novo para lançar no Jira." if not skipped
                         else "O tempo que sobrou é menor que 1 minuto, e o Jira não aceita.")
    return {"kind": WORKLOG, "task_id": task["id"], "issue_key": link["issue_key"], "days": days,
            "skipped_seconds": skipped, "confirmed": False}


def subtasks_preview(task, link, subtasks, types):
    """Subtarefas locais (ainda sem ligação) que poderiam virar sub-tarefas da issue."""
    items = [{"subtask_id": s["id"], "title": s["title"], "estimate_min": s["estimate_min"], "selected": True}
             for s in subtasks if not s.get("jira_key")]
    if not items:
        raise ValueError("Todas as subtarefas já estão no Jira, ou não há subtarefas.")
    return {"kind": SUBTASKS, "task_id": task["id"], "issue_key": link["issue_key"],
            "project_key": link["project_key"], "items": items, "types": types, "type_id": types[0]["id"],
            "confirmed": False}


def selected_changes(preview):
    return [c for c in preview["changes"] if c["selected"]]


def validate(preview):
    """Levanta ValueError se o envio não foi confirmado ou está incompleto."""
    if not preview.get("confirmed"):
        raise ValueError("Envio não confirmado.")
    kind = preview["kind"]
    if kind == FIELDS and not selected_changes(preview):
        raise ValueError("Marque ao menos uma alteração.")
    if kind == STATUS and preview.get("transition_id") not in {o["id"] for o in preview["options"]}:
        raise ValueError("Escolha o novo status.")
    if kind == COMMENT and not preview["text"].strip():
        raise ValueError("O comentário está vazio.")
    if kind == WORKLOG and not [d for d in preview["days"] if d["selected"]]:
        raise ValueError("Marque ao menos um dia.")
    if kind == SUBTASKS:
        if not [i for i in preview["items"] if i["selected"]]:
            raise ValueError("Marque ao menos uma subtarefa.")
        if preview.get("type_id") not in {t["id"] for t in preview["types"]}:
            raise ValueError("Escolha o tipo de sub-tarefa.")


def execute(client, preview):
    """Faz a chamada ao Jira (em thread). Devolve o que mudou, para o app registrar quando voltar."""
    validate(preview)
    key, kind = preview["issue_key"], preview["kind"]
    if kind == COMMENT:
        client.add_comment(key, preview["text"])
        return {"detail": "comentário com as notas"}
    if kind == STATUS:
        option = next(o for o in preview["options"] if o["id"] == preview["transition_id"])
        client.transition(key, option["id"])
        return {"detail": f"status: {option['to_status']}", "option": option}
    if kind == WORKLOG:
        return _send_each(preview["days"], "worklogs", lambda day: {
            "day": day["day"], "session_ids": day["session_ids"],
            "worklog_id": client.add_worklog(key, day["seconds"], day["started"], WORKLOG_COMMENT)},
            lambda done: f"tempo de {len(done)} dia(s)")
    if kind == SUBTASKS:
        return _send_each(preview["items"], "created", lambda item: {
            "subtask_id": item["subtask_id"],
            "key": client.create_subtask(key, preview["project_key"], item["title"], preview["type_id"],
                                         item["estimate_min"])},
            lambda done: f"{len(done)} subtarefa(s)")
    chosen = {c["field"]: c["value"] for c in selected_changes(preview)}
    client.update_fields(key, title=chosen.get("title"), estimate_min=chosen.get("estimate"))
    return {"detail": ", ".join(c["label"].lower() for c in selected_changes(preview)), "fields": chosen}


def _send_each(entries, name, send, detail):
    """Envia um por um os marcados. Se um falhar depois de outros terem dado certo, devolve o que já foi
    (para o app registrar) junto com o erro, em vez de perder o rastro do que já está no Jira."""
    done, planned = [], [e for e in entries if e["selected"]]
    for entry in planned:
        try:
            done.append(send(entry))
        except JiraError as error:
            if not done:
                raise
            return {"detail": detail(done), name: done, "error": str(error), "planned": len(planned)}
    return {"detail": detail(done), name: done, "planned": len(planned)}
