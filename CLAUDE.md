# CLAUDE.md

The project's decisions and conventions live in AGENT.md, shared with the other coding agents:

@AGENT.md

## For Claude Code

- The user may write in French; everything committed stays in English.
- Before claiming a GUI change works, run a copy with another application id (see Testing in
  AGENT.md): the user's own ArchangeSDR instance is often running and swallows a plain launch.
- With every code change, check the README against it (see "The README follows the code" in AGENT.md)
  and update it in the same commit; say in the summary what was changed in it, or that nothing needed to.
- After changing `archangesdr`, `lang/` or `ranges/`, remind the user that `./install.sh` copies them to
  `~/.local/share/archangesdr/app` and that the running window must be restarted.
