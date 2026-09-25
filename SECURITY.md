# Security Policy

## Never commit secrets

Do not commit:

- API keys
- access tokens
- passwords
- `.env` files
- browser cookies or profiles
- local databases/history containing personal data
- credentials exported by desktop applications

Use environment variables or an external secret manager instead.

## Browser automation

JARVIS may create a persistent Playwright profile locally. Treat that directory as sensitive because browser profiles can contain authentication/session data.

The public repository ignores `playwright_profile/`; do not override that rule just to make local browser state convenient to commit.

## Reporting a security issue

For a suspected vulnerability in the public repository, open a private security report through GitHub's Security tab when available. Do not publish credentials or exploit details in a public issue.

## Before publishing changes

Run:

```powershell
git status --short
git diff --check
git ls-files | Select-String '\.env$|playwright_profile|jarvis_history\.json'
```

The final command should return nothing for the sensitive paths above.
