# Push SOMAS v1.1 to GitHub

v1.1 is an upgrade to the v1.0 project. **If you already published the v1.0 repository**, copy the *contents* of this v1.1 folder into your checked-out repository (leave the original `.git` folder untouched), then from the repository root run:

```bash
git status
git add .
git commit -m "Add private user accounts and per-user AI agent ownership"
git push origin main
```

If Git reports your current branch is not `main`, use the actual branch shown by `git branch --show-current`.

If you have **not yet created a GitHub repository**, create an empty `somas-ai` repository on GitHub and run these commands from the extracted v1.1 folder:

```bash
git init -b main
git add .
git commit -m "SOMAS v1.1 user workspaces"
git remote add origin https://github.com/YOUR_USERNAME/somas-ai.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your username. GitHub may require signing in using your Git credential manager, browser or a personal access token. **Never put a token in source code or commit it.**

The project's `.gitignore` excludes `.env`, `data/`, `.db` files, local credentials, Python caches, and virtual environments. Inspect `git status` before committing. Only push the source, tests and documentation.

This version is a local research MVP. A public repository is fine for sharing the source if you choose, but hosting a publicly accessible production SaaS server requires a separate security and operations phase.
