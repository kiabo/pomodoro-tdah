"""Regras de importação das issues do Jira para tarefas locais. Sem GTK e sem rede.

Importar só LÊ do Jira. O que o usuário organiza no app (subtarefas, notas, dia, energia) nunca é tocado,
e o título só acompanha o Jira enquanto o usuário não o tiver renomeado aqui.

Hierarquia: cada épico do Jira vira um GRUPO do app e as tarefas dele entram nesse grupo; sub-tarefas do
Jira viram subtarefas locais da tarefa-pai; o resto vai para o grupo do projeto (ou o grupo "Jira").
"""

from dataclasses import dataclass, field

from ..ui.tokens import GROUP_COLORS

JIRA_GROUP_NAME = "Jira"
JIRA_GROUP_COLOR = "#2684FF"

NEW, UPDATE, SAME, GROUP = "new", "update", "same", "group"      # ações; GROUP = criar o grupo de um épico
TASK, EPIC, SUBTASK = "task", "epic", "subtask"                  # o que a issue vira no app


class Plan(list):
    """Lista de ImportItem. complete=False quando a busca parou no limite e faltaram issues."""

    complete = True


@dataclass
class ImportItem:
    issue: dict
    action: str                        # NEW | UPDATE | SAME | GROUP
    kind: str = TASK                   # TASK | EPIC | SUBTASK
    task_id: str | None = None
    group_id: str | None = None        # None = grupo do épico (criado se preciso) ou o grupo "Jira" padrão
    epic: dict | None = None           # {"key", "title"} do épico a que a tarefa pertence
    parent_key: str | None = None      # chave da tarefa-pai, para sub-tarefas
    changes: list = field(default_factory=list)   # o que muda, em português, para a pré-visualização
    selected: bool = True


def _link_fields(issue, epic=None):
    return {
        "issue_id": issue["id"], "project_key": issue["project_key"], "url": issue["url"],
        "remote_title": issue["title"], "remote_description": issue["description"],
        "remote_status": issue["status"], "remote_status_category": issue["status_category"],
        "remote_estimate_min": issue["estimate_min"], "remote_updated": issue["updated"], "missing": 0,
        "issue_type": issue.get("issue_type") or "", "epic_key": (epic or {}).get("key", ""),
    }


def _usable_group(repo, group_id):
    group = repo.get_group(group_id) if group_id else None
    return group["id"] if group and not group["archived"] else None


def _epic_of(issue):
    parent = issue.get("parent")
    return {"key": parent["key"], "title": parent["title"]} if parent and parent["is_epic"] else None


def plan_import(repo, issues, project_groups=None, epic_groups=None):
    """Compara as issues com o que já existe e devolve a lista de ImportItem (nada é gravado)."""
    project_groups, epic_groups = project_groups or {}, epic_groups or {}
    batch = {i["key"] for i in issues if not i.get("is_epic") and not i.get("is_subtask")}
    items, seen = [], set()
    for issue in issues:
        if issue["key"] in seen:            # a mesma issue pode vir repetida entre páginas da busca
            continue
        seen.add(issue["key"])
        link = repo.jira_link_by_key(issue["key"])
        if issue.get("is_epic") and link is None:
            exists = _usable_group(repo, epic_groups.get(issue["key"]))
            items.append(ImportItem(issue, SAME if exists else GROUP, kind=EPIC, group_id=exists,
                                    changes=[] if exists else ["vira um grupo"], selected=not exists))
            continue
        if issue.get("is_subtask") and issue.get("parent") and link is None:
            parent_key = issue["parent"]["key"]
            parent_known = repo.jira_link_by_key(parent_key) is not None or parent_key in batch
            if parent_known:
                already = repo.subtask_by_jira_key(issue["key"]) is not None
                items.append(ImportItem(issue, SAME if already else NEW, kind=SUBTASK, parent_key=parent_key,
                                        changes=[] if already else [f"subtarefa de {parent_key}"],
                                        selected=not already))
                continue
        epic = _epic_of(issue)
        if link is None:
            group_id = (_usable_group(repo, epic_groups.get(epic["key"])) if epic
                        else _usable_group(repo, project_groups.get(issue["project_key"])))
            note = f"nova tarefa no grupo do épico {epic['title']}" if epic else "nova tarefa"
            items.append(ImportItem(issue, NEW, group_id=group_id, epic=epic, changes=[note]))
            continue
        task = repo.get_task(link["task_id"])
        changes = []
        if issue["title"] != link["remote_title"] and task and task["title"] == link["remote_title"]:
            changes.append("título")
        conflicts = _conflicts(task, link, issue)
        if "title" in conflicts:
            changes.append("título mudou no Jira (o seu foi mantido)")
        if "estimate" in conflicts:
            changes.append("previsão mudou no Jira (a sua foi mantida)")
        if ",".join(sorted(conflicts)) != ",".join(sorted(filter(None, (link["conflicts"] or "").split(",")))):
            if not conflicts or conflicts < set(filter(None, (link["conflicts"] or "").split(","))):
                changes.append("divergência resolvida")
        if issue["status"] != link["remote_status"]:
            changes.append(f"status no Jira: {issue['status']}")
        if issue["estimate_min"] != link["remote_estimate_min"]:
            changes.append("previsão no Jira")
        if issue["description"] != link["remote_description"]:
            changes.append("descrição no Jira")
        if link["missing"]:
            changes.append("voltou para a sua lista")
        if (issue.get("issue_type") or "") != link["issue_type"] or (epic or {}).get("key", "") != link["epic_key"]:
            changes.append("tipo ou épico")
        items.append(ImportItem(issue, UPDATE if changes else SAME, task_id=link["task_id"], epic=epic,
                                group_id=task["group_id"] if task else None, changes=changes,
                                selected=bool(changes)))
    return items


def _conflicts(task, link, issue):
    """Campos que o Jira mudou e o usuário também tinha mudado aqui: {"title", "estimate"} ⊆ resultado.

    Nesses casos o valor do usuário é mantido; o campo só fica anotado para ele decidir.
    """
    found = set(filter(None, (link["conflicts"] or "").split(",")))
    if task is not None:
        if issue["title"] != link["remote_title"] and task["title"] != link["remote_title"]:
            found.add("title")
        local_estimate = task["estimate_min"]
        if (issue["estimate_min"] != link["remote_estimate_min"] and local_estimate is not None
                and local_estimate != link["remote_estimate_min"]):
            found.add("estimate")
        if task["title"] == issue["title"]:
            found.discard("title")                       # já estão iguais: não há o que decidir
        if local_estimate == issue["estimate_min"]:
            found.discard("estimate")
    return found


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


def ensure_epic_group(repo, epic, mapping):
    """Id do grupo do épico (criado com o nome dele na primeira vez; depois o nome é do usuário)."""
    group_id = _usable_group(repo, mapping.get(epic["key"]))
    if group_id is None:
        color = GROUP_COLORS[len(repo.list_groups(include_archived=True)) % len(GROUP_COLORS)]
        group_id = repo.create_group(epic["title"], color)["id"]
    mapping[epic["key"]] = group_id
    return group_id


def apply_import(repo, items, all_keys=None, epic_groups=None):
    """Grava os itens marcados. Devolve {"created", "updated", "groups", "subtasks", "skipped", "epic_groups"}.

    epic_groups: o mapa {chave do épico: id do grupo} já conhecido; o resultado traz o mapa atualizado.
    all_keys: todas as chaves que vieram na busca. Os vínculos fora dela ficam marcados como
    "fora do resultado" (a tarefa continua; só ganha um aviso).
    """
    mapping = dict(epic_groups or {})
    result = {"created": 0, "updated": 0, "groups": 0, "subtasks": 0, "skipped": [], "epic_groups": mapping}
    chosen = [i for i in items if i.selected and i.action != SAME]
    task_ids = {}                                   # chave -> id da tarefa criada/atualizada neste lote

    for item in (i for i in chosen if i.kind == EPIC):
        known = len(mapping)
        ensure_epic_group(repo, {"key": item.issue["key"], "title": item.issue["title"]}, mapping)
        result["groups"] += int(len(mapping) > known)

    for item in (i for i in chosen if i.kind == TASK):
        issue = item.issue
        if item.action == NEW:
            if repo.jira_link_by_key(issue["key"]):
                continue
            if item.epic:
                known = len(mapping)
                group_id = ensure_epic_group(repo, item.epic, mapping)
                result["groups"] += int(len(mapping) > known)
            else:
                group_id = _usable_group(repo, item.group_id) or ensure_jira_group(repo)
            try:
                task = repo.create_task(group_id, issue["title"], estimate_min=issue["estimate_min"])
            except ValueError:
                result["skipped"].append((issue["key"], "o grupo exige previsão e a issue não tem"))
                continue
            repo.save_jira_link(task["id"], issue["key"], **_link_fields(issue, item.epic))
            task_ids[issue["key"]] = task["id"]
            result["created"] += 1
        else:
            link = repo.jira_link_by_key(issue["key"])
            task = repo.get_task(link["task_id"]) if link else None
            if task is None:
                continue
            conflicts = _conflicts(task, link, issue)
            if task["title"] == link["remote_title"] and issue["title"] != link["remote_title"]:
                repo.update_task(task["id"], title=issue["title"])
            repo.save_jira_link(task["id"], issue["key"], conflicts=",".join(sorted(conflicts)),
                                **_link_fields(issue, item.epic))
            result["updated"] += 1

    for item in (i for i in chosen if i.kind == SUBTASK):          # por último: a tarefa-pai já existe
        issue = item.issue
        parent_link = repo.jira_link_by_key(item.parent_key)
        parent_id = task_ids.get(item.parent_key) or (parent_link["task_id"] if parent_link else None)
        if parent_id is None or repo.subtask_by_jira_key(issue["key"]):
            continue
        sub = repo.add_subtask(parent_id, issue["title"], issue["estimate_min"])
        repo.set_subtask_jira_key(sub["id"], issue["key"])
        result["subtasks"] += 1

    if all_keys is not None:
        repo.mark_jira_missing(all_keys)
    return result
