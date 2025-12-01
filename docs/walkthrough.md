# Walkthrough

## Docker Release & Docs Walkthrough

### Changes
#### Docker Build Fix
- Switched base image to `python:3.9` (full) to resolve missing build dependencies for `mitmproxy`/`presidio`.
- Verified build locally (successful).

#### GitHub Pages
- Created `.github/workflows/docs.yml` to automate VitePress deployment.
- Updated GitHub Actions versions to fix deprecation warnings (`checkout@v4`, `setup-node@v4`, `upload-pages-artifact@v3`, `deploy-pages@v4`).
- **Fix**: Switched to `npm install` and removed `cache: npm` because `package-lock.json` is not present in the repository.
- **Fix**: Resolved dead link in `docs/CONTRIBUTING.md` (pointed to missing `README.md`, updated to `index.md`).
- **Fix**: Added `base: '/aidlp/'` to `docs/.vitepress/config.mts` to resolve MIME type errors (404s) for assets on GitHub Pages.
- Triggers on push to `main` for changes in `docs/`.

#### Docker Release Workflow
- Created `.github/workflows/docker-publish.yml`.
- Triggers on tags `v*`.

### Setup Required
> [!IMPORTANT]
> Ensure `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` are set in GitHub Secrets.

### Verification
- **Docker Build**: Verified locally.
- **Docs**: Pushed to `main`. Check GitHub Actions for "Deploy Docs" workflow.
- **Docker Release**: Pushed tag `v1.2.2`. Check GitHub Actions for "Docker" workflow.
