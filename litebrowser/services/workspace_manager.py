from litebrowser.core import prefs

WORKSPACE_ROLE = 2  # Qt.UserRole + 2 for workspace_id on tab item

PRIMARY_WORKSPACE_ID = "ws1"
SECONDARY_WORKSPACE_ID = "ws2"
DEFAULT_WORKSPACES = [
    {"id": PRIMARY_WORKSPACE_ID, "name": "Workspace 1"},
    {"id": SECONDARY_WORKSPACE_ID, "name": "Workspace 2"},
]


def load(base_dir):
    return ensure_dual_workspaces(base_dir)


def save(base_dir, data):
    prefs.save_workspaces(base_dir, data)


def get_workspaces_list(base_dir):
    data = load(base_dir)
    return data.get("workspaces", list(DEFAULT_WORKSPACES))


def get_current_id(base_dir):
    data = load(base_dir)
    current_id = data.get("current_id", PRIMARY_WORKSPACE_ID)
    valid_ids = {item["id"] for item in get_workspaces_list(base_dir)}
    return current_id if current_id in valid_ids else PRIMARY_WORKSPACE_ID


def set_current_id(base_dir, workspace_id):
    data = load(base_dir)
    valid_ids = {item["id"] for item in data.get("workspaces", []) if isinstance(item, dict) and item.get("id")}
    data["current_id"] = workspace_id if workspace_id in valid_ids else PRIMARY_WORKSPACE_ID
    save(base_dir, data)


def add_workspace(base_dir, name):
    data = load(base_dir)
    workspaces = data.get("workspaces", [])
    import uuid
    wid = "w_" + uuid.uuid4().hex[:8]
    workspaces.append({"id": wid, "name": name or "Workspace"})
    data["workspaces"] = workspaces
    save(base_dir, data)
    return wid


def remove_workspace(base_dir, workspace_id):
    if workspace_id in (PRIMARY_WORKSPACE_ID, SECONDARY_WORKSPACE_ID, "default"):
        return False
    data = load(base_dir)
    workspaces = [w for w in data.get("workspaces", []) if w.get("id") != workspace_id]
    data["workspaces"] = workspaces
    if data.get("current_id") == workspace_id:
        data["current_id"] = PRIMARY_WORKSPACE_ID if any(w.get("id") == PRIMARY_WORKSPACE_ID for w in workspaces) else workspaces[0]["id"]
    save(base_dir, data)
    return True


def rename_workspace(base_dir, workspace_id, new_name):
    data = load(base_dir)
    for w in data.get("workspaces", []):
        if w.get("id") == workspace_id:
            w["name"] = new_name or w.get("name", "Workspace")
            save(base_dir, data)
            return True
    return False


def ensure_dual_workspaces(base_dir):
    data = prefs.load_workspaces(base_dir)
    workspaces = data.get("workspaces", [])
    existing = {}
    for item in workspaces:
        if not isinstance(item, dict):
            continue
        wid = str(item.get("id") or "").strip()
        if not wid:
            continue
        if wid == "default":
            wid = PRIMARY_WORKSPACE_ID
        existing[wid] = {"id": wid, "name": item.get("name") or ("Workspace 1" if wid == PRIMARY_WORKSPACE_ID else wid)}

    for item in DEFAULT_WORKSPACES:
        existing.setdefault(item["id"], dict(item))

    ordered_ids = [PRIMARY_WORKSPACE_ID, SECONDARY_WORKSPACE_ID] + [wid for wid in existing if wid not in (PRIMARY_WORKSPACE_ID, SECONDARY_WORKSPACE_ID)]
    normalized = [existing[wid] for wid in ordered_ids]
    current_id = data.get("current_id", PRIMARY_WORKSPACE_ID)
    if current_id == "default" or current_id not in {item["id"] for item in normalized}:
        current_id = PRIMARY_WORKSPACE_ID

    payload = {"workspaces": normalized, "current_id": current_id}
    if payload != data:
        save(base_dir, payload)
    return payload
