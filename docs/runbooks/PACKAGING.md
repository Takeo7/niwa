# Niwa Packaging & Release Runbook

Last updated: 2026-04-30

This runbook documents the release process. Niwa is currently distributed as source — there is no published wheel/binary. End users clone the repo and run `bootstrap.sh`.

## Versioning

Semantic versioning (`MAJOR.MINOR.PATCH`). The MVP is `v1.0.0`; security/bugfix releases bump PATCH; new features bump MINOR.

Source of truth: `backend/pyproject.toml::project.version` and the latest git tag.

## Release checklist

1. **Confirm baseline tests pass**
   ```bash
   cd backend && pytest -q
   cd frontend && npm test
   ```

2. **Update HANDBOOK + CHANGELOG**
   - Add a section under the new version with notable changes.
   - Bump `pyproject.toml::project.version`.

3. **Run cleanup smoke**
   ```bash
   niwa-executor cleanup --dry-run
   ```

4. **Tag the release**
   ```bash
   git tag -a v1.x.y -m "v1.x.y: <one-line summary>"
   git push origin v1.x.y
   ```

5. **Create GitHub release**
   - Title: `v1.x.y`
   - Body: paste the changelog section.
   - Attach: nothing — source tarball is auto-generated.

## Distribution

- **Repo clone**: users `git clone` and run `./bootstrap.sh`.
- **Pip install**: not yet supported. The backend is `editable` (`-e backend`); a release wheel would require splitting the entry point.
- **Docker**: not yet supplied. A reference Dockerfile is in `docs/runbooks/DOCKER.md` (TODO).

## Rollback

If a release breaks production:

```bash
git fetch --tags
git checkout v1.<previous>.<patch>
./bootstrap.sh   # reinstalls deps
niwa-executor restart
```

DB migrations are forward-only — downgrading code without `alembic downgrade <prev_head>` may leave the DB on a newer schema than the code expects.

## Future work

- Publish to PyPI as `niwa` (entry point: `niwa-executor`)
- Provide an installer script that resolves Python/Node prereqs
- Provide signed binaries for macOS/Linux
- Provide a Dockerfile + compose for one-command stand-up
