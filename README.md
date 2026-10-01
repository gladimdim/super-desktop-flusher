# Flusher

A [SUPER DESKTOP](https://github.com/gladimdim/super-desktop) plugin that
finds the git repositories with uncommitted changes in your folders and hands
them to an AI agent that commits them with meaningful messages and pushes them.

- **🧹 Flush** in the top bar (with a badge counting the projects with
  changes), or **SUPER + CTRL + G** from anywhere, opens a panel listing every
  repository with uncommitted changes in the folders you chose and their
  sub-folders. All of them are ticked.
- Untick the ones that should stay as they are. **Files** shows what changed
  in a repository.
- **Flush** starts the agent you chose (Claude Code, Codex, Grok, Cursor Agent,
  OpenCode, Gemini CLI or Antigravity) in a new SUPER DESKTOP card, in the folder those repositories share,
  with instructions to commit each one's changes as meaningful commits and push
  its current branch. You watch it work in that card and answer its questions.

Repositories in the middle of a merge or rebase, with conflicts, or on a
detached HEAD are listed but cannot be ticked.

## Install

Needs a SUPER DESKTOP build with plugin API 1 (`super-desktop plugin describe`
says so).

```sh
git clone https://github.com/gladimdim/super-desktop-flusher
super-desktop plugin link super-desktop-flusher
super-desktop plugin activate flusher
```

Then open ⚙ Settings → Plugins → Flusher and add the folders to scan.

## Settings

| Setting | Default | |
| --- | --- | --- |
| Folders to scan | none | Repositories in these folders and their sub-folders are listed. Hidden folders, `node_modules`, `target`, `vendor`, `dist`, `build` and virtualenvs are skipped, and a repository's own sub-folders are not searched. |
| Agent that flushes | Claude Code | `claude`, `codex`, `grok`, `cursor`, `opencode`, `gemini` or `antigravity`: the harnesses SUPER DESKTOP can start with a prompt. It must be installed. |
| Sub-folder depth | 4 | How many levels below each folder are searched (1–8). |
| Count new (untracked) files as changes | on | Off: only changes to tracked files count. |
| Extra instructions for the agent | none | Added to the agent's prompt, e.g. a commit convention. |

The shortcut can be changed or turned off in Settings → Plugins.

## Permissions, and why

| Permission | Why |
| --- | --- |
| `ui.toolbar` | The 🧹 Flush button and its badge. |
| `ui.popup` | The panel. |
| `shortcuts.global` | SUPER + CTRL + G. |
| `harness.launch` | Starting the agent in a card with its instructions. |

The plugin reads `git status` in the folders you chose. It never commits,
pushes or changes a file itself, and it sends nothing anywhere.

## What the agent does

The agent gets this list of the repositories you ticked and these rules:

- commit related changes together, with clear messages in the imperative mood
  that say what changed and why (following the repository's style if it has one);
- leave secrets and junk uncommitted (`.env` files, keys, tokens, build output,
  large binaries) and name them in its summary;
- push the current branch (`git push`, or `git push -u origin HEAD` without an
  upstream);
- stay on the current branch: never force-push, rebase, reset, merge other
  branches or delete files; on a rejected push, `git pull --ff-only` once and
  retry, otherwise stop and report.

The agent runs with your harness's own settings. If your harness is set to
skip its permission prompts (for example Claude Code with
`--dangerously-skip-permissions` in Settings → Harness parameters), it commits
and pushes without asking you.

The diffs it reads go to that agent's AI provider, as with any other use of it.

## Development

```sh
super-desktop plugin validate .
super-desktop plugin test .      # scenarios in tests/, no desktop needed
```

See `AGENTS.md`.
