"""Regras de importação das issues do Jira para tarefas locais. Sem GTK e sem rede.

Importar só LÊ do Jira. O que o usuário organiza no app (subtarefas, notas, dia, energia) nunca é tocado,
e o título só acompanha o Jira enquanto o usuário não o tiver renomeado aqui.
"""

from dataclasses import dataclass, field

JIRA_GROUP_NAME = "Jira"
JIRA_GROUP_COLOR = "#2684FF"

NEW, UPDATE, SAME = "new", "update", "same"


@dataclass
class ImportItem:
    issue: dict
    action: str                        # NEW | UPDATE | SAME
    task_id: str | None = None
    group_id: str | None = None        # None = o grupo "Jira" padrão
    changes: list = field(default_factory=list)   # o que muda, em português, para a pré-visualização
    selected: bool = True


def _link_fields(issue):
    return {
        "issue_id": issue["id"], "project_key": issue["project_key"], "url": issue["url"],
        "remote_title": issue["title"], "remote_description": issue["description"],
        "remote_status": issue["status"], "remote_status_category": issue["status_category"],
        "remote_estimate_min": issue["estimate_min"], "remote_updated": issue["updated"], "missing": 0,
    }


def _usable_group(repo, group_id):
    group = repo.get_group(group_id) if group_id else None
    return group["id"] if group and not group["archived"] else None


def plan_import(repo, issues, project_groups=None):
    """Compara as issues com o que já existe e devolve a lista de ImportItem (nada é gravado)."""
    project_groups = project_groups or {}
    items = []
    for issue in issues:
        link = repo.jira_link_by_key(issue["key"])
        if link is None:
            group_id = _usable_group(repo, project_groups.get(issue["project_key"]))
            items.append(ImportItem(issue, NEW, group_id=group_id, changes=["nova tarefa"]))
            continue
        task = repo.get_task(link["task_id"])
        changes = []
        if issue["title"] != link["remote_title"] and task and task["title"] == link["remote_title"]:
            changes.append("título")
        if issue["status"] != link["remote_status"]:
            changes.append(f"status no Jira: {issue['status']}")
        if issue["estimate_min"] != link["remote_estimate_min"]:
            changes.append("previsão no Jira")
        if issue["description"] != link["remote_description"]:
            changes.append("descrição no Jira")
        if link["missing"]:
            changes.append("voltou para a sua lista")
        items.append(ImportItem(issue, UPDATE if changes else SAME, task_id=link["task_id"],
                                group_id=task["group_id"] if task else None, changes=changes,
                                selected=bool(changes)))
    return items


def ensure_jira_group(repo):
    """Id do grupo "Jira", criando-o na primeira vez."""
    from .. import db
    group_id = _usable_group(repo, db.get_meta(repo.conn, "jira_group_id"))
    if group_id:
        return group_id
    group_id = repo.create_group(JIRA_GROUP_NAME, JIRA_GROUP_COLOR)["id"]
    with repo.conn:
        db.set_meta(repo.conn, "jira_group_id", group_id)
    return group_id


def apply_import(repo, items, all_keys=None):
    """Grava os itens marcados. Devolve {"created", "updated", "skipped": [(chave, motivo)]}.

    all_keys: todas as chaves que vieram na busca. Os vínculos fora dela ficam marcados como
    "fora do resultado" (a tarefa continua; só ganha um aviso).
    """
    result = {"created": 0, "updated": 0, "skipped": []}
    for item in items:
        if not item.selected or item.action == SAME:
            continue
        issue = item.issue
        if item.action == NEW:
            group_id = _usable_group(repo, item.group_id) or ensure_jira_group(repo)
            try:
                task = repo.create_task(group_id, issue["title"], estimate_min=issue["estimate_min"])
            except ValueError:
                result["skipped"].append((issue["key"], "o grupo exige previsão e a issue não tem"))
                continue
            repo.save_jira_link(task["id"], issue["key"], **_link_fields(issue))
            result["created"] += 1
        else:
            link = repo.jira_link_by_key(issue["key"])
            task = repo.get_task(link["task_id"]) if link else None
            if task is None:
                continue
            if task["title"] == link["remote_title"] and issue["title"] != link["remote_title"]:
                repo.update_task(task["id"], title=issue["title"])
            repo.save_jira_link(task["id"], issue["key"], **_link_fields(issue))
            result["updated"] += 1
    if all_keys is not None:
        repo.mark_jira_missing(all_keys)
    return result
