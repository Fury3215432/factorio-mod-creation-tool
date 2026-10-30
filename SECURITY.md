# Security and privacy

Factorio Mod Creation Tool is a local desktop app by FuryziN. It has no analytics, accounts, or telemetry. The project website contains no trackers, forms, or third-party scripts.

The app runs the installed Factorio executable to load game and mod data. Load only mods you trust. A supplied mod's Lua scripts run in Factorio's normal data stage.

Local `.studio/` files can contain projects, image data, and local file paths. `.cache/` can contain copied mods, game data, logs, and temporary saves. Exported mods and reports may contain your mod content. These files are excluded from the public repository and release package.

Before sharing bug reports, remove local usernames, absolute file paths, project data, saves, and credentials. Do not post tokens, passwords, or private logs in public issues. Use GitHub's private vulnerability reporting when enabled; otherwise contact the maintainer through their public GitHub profile without posting sensitive details.

Only the repository owner and explicitly authorized collaborators should have write access. Outside suggestions and pull requests are not applied automatically. A public repository can be read and forked; write restrictions protect the original repository, not other people's copies.
