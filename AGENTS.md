# Agent instructions

This is a SUPER DESKTOP plugin (`flusher`). Follow the `super-desktop-plugin`
skill in `.agents/skills/super-desktop-plugin/SKILL.md` (also at
https://github.com/gladimdim/super-desktop/tree/master/skills/super-desktop-plugin); review with `super-desktop-plugin-review` before a release.

- Start with `super-desktop plugin describe --json`: use only what it lists.
- The manifest is `super-desktop-plugin.json`; run
  `super-desktop plugin validate . --json` after every change and fix every error.
- Run `super-desktop plugin test .` before committing.
- Never print to stdout from plugin code: it is the protocol channel.
- Ask for the fewest permissions; never edit SUPER DESKTOP's or Hyprland's files.
