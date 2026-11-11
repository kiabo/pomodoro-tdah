"""Envio ao Jira: monta a PRÉ-VISUALIZAÇÃO do que iria e executa exatamente o que foi confirmado. Sem GTK.

Nada aqui roda sozinho: cada envio nasce de um pedido do usuário, passa por uma janela que mostra o
conteúdo e só é executado com preview["confirmed"] = True (marcado pela janela ao clicar em Enviar).
"""

COMMENT, STATUS, FIELDS = "comment", "status", "fields"


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
    chosen = {c["field"]: c["value"] for c in selected_changes(preview)}
    client.update_fields(key, title=chosen.get("title"), estimate_min=chosen.get("estimate"))
    return {"detail": ", ".join(c["label"].lower() for c in selected_changes(preview)), "fields": chosen}
