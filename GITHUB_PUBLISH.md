# Keep SOMAS source private

Use the existing private repository. Do not initialize another Git repository, copy an old `.git` directory, or change visibility. No push or deployment has been performed by this source upgrade.

```powershell
git status --short
git diff --check
git diff --stat
```

Review changes, stage the intended source/configuration/documentation files, and inspect the staged diff before committing. `.gitignore` excludes local credentials, databases, exports, dependency directories and tooling caches. Never stage `.env`, `.dev.vars`, a real `DATABASE_URL`, passwords, cookies, AI keys or SQLite backups.

When you choose to publish the source changes to your private repository:

```powershell
git add app frontend functions migrations scripts tests .github .gitignore .env.example .dev.vars.example .python-version .vercelignore vercel.json requirements.txt requirements-dev.txt package.json package-lock.json pytest.ini alembic.ini compose.yaml run.py start_windows.bat start_mac_linux.sh README.md ARCHITECTURE.md RELEASE_NOTES.md GITHUB_PUBLISH.md DEPLOY_RENDER_CLOUDFLARE_NEON.md DEPLOY_VERCEL_CLOUDFLARE_NEON.md
git add -u
git diff --cached --stat
git commit -m "Prepare SOMAS v1.3 for native Vercel FastAPI deployment"
git push origin HEAD
```

Use the connected GitHub account/credential manager; never put an access token in the remote URL. Connecting the repository to a cloud host is a separate, explicit deployment action. Follow [the deployment guide](DEPLOY_VERCEL_CLOUDFLARE_NEON.md) for the Free plans and private secrets configuration. Review tracked deletions staged by `git add -u` as well as additions. A push can trigger an already connected host's automatic deployment; inspect your account integration settings before pushing.
