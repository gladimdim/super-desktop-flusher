"""Flusher: a SUPER DESKTOP plugin. See AGENTS.md before changing it.

The panel lists every git repository under the configured folders that has
uncommitted changes, all ticked. Untick what should stay; "Files" shows what
changed. "Flush" starts the chosen agent in a new card with a prompt to commit
the ticked repositories meaningfully and push each one's current branch. The
agent works in a visible card: the person sees it and answers its questions.

This plugin itself never commits, pushes or changes a file: it only reads
`git status`.
"""
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sd_plugin import Plugin, RpcError

plugin = Plugin()
VIEW = "flusher.panel"
BUTTON = "flusher.button"
AGENTS = {"claude": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "gemini": "Gemini CLI"}
SKIP = {"node_modules", "target", "vendor", "dist", "build", "__pycache__", "venv", ".venv"}
MAX_REPOS = 300
MAX_DIRS = 20000
MAX_FILES_SHOWN = 200
RESCAN_AFTER = 60  # seconds between background rescans when the overlay shows

state = {"handle": None, "repos": [], "selected": set(), "open_files": set(), "scanned_at": 0.0}
lock = threading.Lock()


# ---- finding repositories ---------------------------------------------------
def find_repos(roots, depth):
    """Git work trees under `roots`, at most `depth` levels down; a repository's
    own sub-folders are not searched. Hidden folders and build output are skipped."""
    found, seen, visited = [], set(), 0
    queue = [(os.path.realpath(os.path.expanduser(r)), 0) for r in roots if r]
    while queue and len(found) < MAX_REPOS and visited < MAX_DIRS:
        path, level = queue.pop(0)
        if path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        visited += 1
        if os.path.exists(os.path.join(path, ".git")):
            found.append(path)
            continue
        if level >= depth:
            continue
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or entry.name in SKIP:
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    queue.append((entry.path, level + 1))
            except OSError:
                pass
    return sorted(found)


def git(repo, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=30, env=env)


def status(repo, include_untracked):
    """Branch, upstream and change counts; `blocked` when an agent should not
    be sent in (merge in progress, conflicts, detached HEAD)."""
    info = {"path": repo, "name": os.path.basename(repo), "branch": "?", "upstream": None,
            "changed": 0, "new": 0, "blocked": None}
    proc = git(repo, "status", "--porcelain=v2", "--branch", "-unormal" if include_untracked else "-uno")
    if proc.returncode != 0:
        info["blocked"] = (proc.stderr.strip().splitlines() or ["git status failed"])[0][:160]
        return info
    conflicts = 0
    for line in proc.stdout.splitlines():
        if line.startswith("# branch.head "):
            info["branch"] = line[len("# branch.head "):]
        elif line.startswith("# branch.upstream "):
            info["upstream"] = line[len("# branch.upstream "):]
        elif line.startswith(("1 ", "2 ")):
            info["changed"] += 1
        elif line.startswith("u "):
            conflicts += 1
        elif line.startswith("? "):
            info["new"] += 1
    if info["branch"] == "(detached)":
        info["blocked"] = "detached HEAD: no branch to push"
    elif conflicts:
        info["blocked"] = f"{conflicts} conflicted file(s)"
    else:
        for marker, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"), ("CHERRY_PICK_HEAD", "a cherry-pick")):
            path = git(repo, "rev-parse", "--git-path", marker).stdout.strip()
            if path and os.path.exists(path if os.path.isabs(path) else os.path.join(repo, path)):
                info["blocked"] = f"in the middle of {what}"
    info["dirty"] = info["changed"] + info["new"] + conflicts > 0
    return info


def changed_files(repo, include_untracked):
    out = git(repo, "status", "--short", "-unormal" if include_untracked else "-uno").stdout.rstrip().splitlines()
    more = len(out) - MAX_FILES_SHOWN
    return "\n".join(out[:MAX_FILES_SHOWN]) + (f"\n… and {more} more" if more > 0 else "")


def scan():
    values = plugin.call("settings.get")
    roots = values.get("folders") or []
    include = values.get("includeUntracked", True)
    repos = find_repos(roots, int(values.get("depth", 4)))
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda r: status(r, include), repos))
    dirty = [i for i in infos if i.get("dirty") or i["blocked"]]
    # Same-named repositories get their parent folder for a name.
    names = [i["name"] for i in dirty]
    for info in dirty:
        if names.count(info["name"]) > 1:
            info["name"] = os.path.join(os.path.basename(os.path.dirname(info["path"])), info["name"])
    state["scanned_at"] = time.time()
    return dirty, values, roots


def update_badge(repos):
    count = sum(1 for r in repos if not r["blocked"])
    plugin.call("contrib.update", id=BUTTON, badge=str(count) if count else None)


# ---- the panel ----------------------------------------------------------------
def describe(repo):
    where = repo["branch"] + (f" → {repo['upstream']}" if repo["upstream"] else " (no upstream yet)")
    counts = []
    if repo["changed"]:
        counts.append(f"{repo['changed']} changed")
    if repo["new"]:
        counts.append(f"{repo['new']} new")
    return f"{where} · {', '.join(counts) or 'no changes'}"


def row(i, repo):
    blocked = repo["blocked"]
    return {"type": "column", "id": f"repo:{i}", "gap": 4, "children": [
        {"type": "row", "id": f"head:{i}", "gap": 10, "children": [
            {"type": "checkbox", "id": f"sel:{i}", "label": repo["name"], "value": not blocked, "enabled": not blocked},
            {"type": "label", "id": f"where:{i}", "text": describe(repo), "style": "muted"},
            {"type": "button", "id": f"files:{i}", "label": "Files"},
        ]},
        {"type": "label", "id": f"path:{i}", "text": repo["path"], "style": "mono"},
        {"type": "label", "id": f"note:{i}", "text": f"Not flushed: {blocked}" if blocked else "", "style": "error", "visible": bool(blocked)},
        {"type": "code", "id": f"list:{i}", "text": "", "visible": False},
    ]}


def flush_label():
    n = len(state["selected"])
    return f"Flush {n} project" + ("" if n == 1 else "s")


def model(repos, values, roots):
    agent = AGENTS.get(values.get("agent", "claude"), values.get("agent", "claude"))
    if not roots:
        body = [{"type": "label", "id": "empty", "style": "muted", "wrap": True,
                 "text": "No folders to scan yet. Add them in Settings → Plugins → Flusher, then press Refresh."}]
    elif not repos:
        body = [{"type": "label", "id": "empty", "style": "muted", "wrap": True,
                 "text": "Every repository in your folders is clean."}]
    else:
        body = [{"type": "scroll", "id": "rows-scroll", "maxHeight": 380, "children": [
            {"type": "list", "id": "rows", "gap": 12, "children": [row(i, r) for i, r in enumerate(repos)]}]}]
    count = len(repos)
    return {"type": "column", "id": "root", "gap": 12, "children": [
        {"type": "row", "id": "top", "gap": 10, "children": [
            {"type": "label", "id": "summary", "style": "title",
             "text": f"{count} project{'' if count == 1 else 's'} with changes" if roots else "Flusher"},
            {"type": "button", "id": "refresh", "label": "Refresh"},
        ]},
        *body,
        {"type": "row", "id": "bottom", "gap": 10, "children": [
            {"type": "label", "id": "agent", "style": "muted", "text": f"Agent: {agent} · change it in Settings → Plugins → Flusher"},
            {"type": "button", "id": "flush", "label": flush_label(), "tone": "primary", "enabled": bool(state["selected"])},
        ]},
        {"type": "label", "id": "status", "text": "", "visible": False, "wrap": True},
    ]}


def patch(*ops):
    if state["handle"]:
        try:
            plugin.call("ui.patch", handle=state["handle"], ops=list(ops))
        except RpcError as error:
            plugin.log(f"ui.patch failed: {error}", "warn")


def set_props(node, **props):
    return {"op": "set", "id": node, "props": props}


@plugin.command("flusher.open")
def open_panel(_context):
    repos, values, roots = scan()
    with lock:
        state.update(repos=repos, open_files=set(), selected={i for i, r in enumerate(repos) if not r["blocked"]})
    update_badge(repos)
    state["handle"] = plugin.call("ui.open", view=VIEW, model=model(repos, values, roots), anchor=BUTTON)["handle"]


@plugin.view(VIEW)
def on_view(handle, node, event, value):
    if node.startswith("sel:") and event == "change":
        i = int(node[4:])
        (state["selected"].add if value else state["selected"].discard)(i)
        patch(set_props("flush", label=flush_label(), enabled=bool(state["selected"])))
    elif node.startswith("files:") and event == "click":
        i = int(node[6:])
        showing = i in state["open_files"]
        if showing:
            state["open_files"].discard(i)
            patch(set_props(f"list:{i}", visible=False), set_props(node, label="Files"))
        else:
            state["open_files"].add(i)
            include = plugin.call("settings.get").get("includeUntracked", True)
            text = changed_files(state["repos"][i]["path"], include) or "(no changes)"
            patch(set_props(f"list:{i}", text=text, visible=True), set_props(node, label="Hide files"))
    elif node == "refresh" and event == "click":
        open_panel({})
    elif node == "flush" and event == "click":
        flush()


def prompt_for(repos, instructions):
    lines = [f"- {r['path']} (branch {r['branch']}" + (f" → {r['upstream']}" if r["upstream"] else ", no upstream yet") + f"): {describe(r).split(' · ')[-1]}"
             for r in repos]
    extra = f"\n\nAlso: {instructions.strip()}" if instructions and instructions.strip() else ""
    opening = ("Flush the uncommitted work in this git repository.\n\n" if len(repos) == 1 else
               f"Flush the uncommitted work in these {len(repos)} git repositories. Work through them one by one.\n\n")
    return (
        opening +
        "For each repository:\n"
        "1. Go into it and read `git status` and `git diff` (staged and unstaged), and look at the new files.\n"
        "2. Commit the changes as one or more meaningful commits: group related changes, and write clear messages "
        "in the imperative mood that say what changed and why. Follow the repository's existing commit style if it has one.\n"
        "3. Do not commit secrets or junk (.env files, keys, tokens, build output, large binaries). Leave them "
        "uncommitted and name them in your summary.\n"
        "4. Push the current branch: `git push`, or `git push -u origin HEAD` when it has no upstream yet.\n\n"
        "Rules: stay on the current branch. Never force-push, rebase, reset, merge other branches or delete files. "
        "If a push is rejected because the remote has new commits, run `git pull --ff-only` once and push again; "
        "if that fails too, stop for that repository and report it.\n\n"
        "When you are done, print a short summary: for each repository, the commits you made and whether the push succeeded.\n\n"
        "Repositories:\n" + "\n".join(lines) + extra
    )


def flush():
    chosen = [state["repos"][i] for i in sorted(state["selected"])]
    if not chosen:
        return
    values = plugin.call("settings.get")
    agent = values.get("agent", "claude")
    # The agent starts in the folder the chosen repositories share.
    folder = os.path.commonpath([r["path"] for r in chosen]) if len(chosen) > 1 else chosen[0]["path"]
    patch(set_props("flush", enabled=False))
    try:
        plugin.call("harness.launch", agent=agent, folder=folder, prompt=prompt_for(chosen, values.get("instructions", "")))
    except RpcError as error:
        hint = error.data.get("hint") or error.message
        patch(set_props("status", text=f"Could not start {AGENTS.get(agent, agent)}: {hint}", style="error", visible=True),
              set_props("flush", enabled=True))
        return
    names = ", ".join(r["name"] for r in chosen)
    patch(set_props("status", text=f"Started {AGENTS.get(agent, agent)} in a new card for {names}. "
                                   "Watch it there and answer its questions; press Refresh when it is done.",
                    style="success", visible=True))


@plugin.on("view.closed")
def closed(handle):
    if handle == state["handle"]:
        state["handle"] = None


@plugin.on("overlay.shown")
def shown():
    # Keep the badge fresh without scanning on every show.
    if time.time() - state["scanned_at"] > RESCAN_AFTER:
        threading.Thread(target=lambda: update_badge(scan()[0]), daemon=True).start()


@plugin.on("settings.changed")
def settings_changed(values):
    threading.Thread(target=lambda: update_badge(scan()[0]), daemon=True).start()


plugin.run()
