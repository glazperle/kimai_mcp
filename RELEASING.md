# Release Process

This document describes how to create a new release of the Kimai MCP Server.

## Automatic Docker Image Building

The project uses GitHub Actions to **automatically** build and publish Docker images when you create a new release.

### What Gets Built Automatically

When you create a release tag (e.g., `v2.7.0`), GitHub Actions will:

1. ✅ Build Docker images for `linux/amd64` and `linux/arm64`
2. ✅ Push to GitHub Container Registry (ghcr.io)
3. ✅ Create multiple image tags automatically:
   - `ghcr.io/glazperle/kimai_mcp:2.7.0` (exact version)
   - `ghcr.io/glazperle/kimai_mcp:2.7` (minor version)
   - `ghcr.io/glazperle/kimai_mcp:2` (major version)
   - `ghcr.io/glazperle/kimai_mcp:latest` (if from main branch)

## Release Checklist

### 1. Prepare the Release

```bash
# Update version in pyproject.toml
# Current version: 2.6.0 → New version: 2.7.0
```

Edit `pyproject.toml`:
```toml
[project]
name = "kimai-mcp"
version = "2.7.0"  # Update this line
```

### 2. Update Changelog

Create or update `CHANGELOG.md` with release notes:

```markdown
## [2.7.0] - 2024-XX-XX

### Added
- New feature X
- Enhancement Y

### Fixed
- Bug fix Z

### Changed
- Breaking change W (if any)
```

### 3. Update Version in Code

Also update `__version__` in `src/kimai_mcp/server.py`:

```python
__version__ = "2.7.0"
```

### 4. Commit Version Bump

```bash
git add pyproject.toml src/kimai_mcp/server.py CHANGELOG.md
git commit -m "chore: Bump version to 2.7.0"
git push origin main
```

### 5. Create and Push Tag

```bash
# Create annotated tag
git tag -a v2.7.0 -m "Release version 2.7.0

- Feature X
- Enhancement Y
- Bug fix Z
"

# Push tag to trigger GitHub Actions
git push origin v2.7.0
```

### 6. Create GitHub Release

**Option A: Via GitHub Web Interface (Recommended)**

1. Go to https://github.com/glazperle/kimai_mcp/releases
2. Click "Create a new release"
3. Select tag: `v2.7.0`
4. Release title: `v2.7.0` or `Kimai MCP Server v2.7.0`
5. Description: Copy from CHANGELOG.md
6. Click "Publish release"

**Option B: Via GitHub CLI**

```bash
gh release create v2.7.0 \
  --title "v2.7.0" \
  --notes "$(cat CHANGELOG.md | sed -n '/## \[2.7.0\]/,/## \[/p' | sed '$d')"
```

### 7. Verify Build

1. Go to **Actions** tab on GitHub
2. Wait for "Docker Build and Publish" workflow to complete (usually 5-10 minutes)
3. Check **Packages** section to see the new Docker images

### 8. Publish to PyPI

```bash
# Install build tools
pip install --upgrade build twine

# Build package
python -m build

# Upload to PyPI (requires PyPI credentials)
python -m twine upload dist/*

# Or upload to TestPyPI first
python -m twine upload --repository testpypi dist/*
```

### 9. Test the Release

```bash
# Test Docker image
docker pull ghcr.io/glazperle/kimai_mcp:2.7.0
docker run --rm ghcr.io/glazperle/kimai_mcp:2.7.0 --version

# Test PyPI package
pip install --upgrade kimai-mcp
kimai-mcp --version
```

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** version (X.0.0): Incompatible API changes
- **MINOR** version (0.X.0): Backwards-compatible new features
- **PATCH** version (0.0.X): Backwards-compatible bug fixes

### Examples:

- `2.6.0` → `2.6.1`: Bug fix (patch)
- `2.6.0` → `2.7.0`: New feature (minor)
- `2.6.0` → `3.0.0`: Breaking change (major)

## Post-Release

### Update Documentation

If there are significant changes, update:
- [ ] README.md
- [ ] DEPLOYMENT.md
- [ ] Examples in `examples/`

### Announce Release

Consider announcing the release:
- [ ] GitHub Discussions
- [ ] Project website (if any)
- [ ] Social media (if applicable)

### Monitor Issues

Watch for issues related to the new release:
- Check GitHub Issues
- Monitor Docker image pulls
- Review PyPI download stats

## Rollback Procedure

If you need to rollback a release:

### Docker Images

Users can pin to previous version:
```bash
docker pull ghcr.io/glazperle/kimai_mcp:2.6.0
```

### PyPI Package

1. Yank the problematic release (doesn't delete, just marks as unstable):
```bash
# Via PyPI web interface or
pip install twine
twine upload --repository pypi --skip-existing dist/*
```

2. Release a hotfix version (e.g., 2.7.1)

### Git Tags

Only delete tags if absolutely necessary:
```bash
# Delete local tag
git tag -d v2.7.0

# Delete remote tag
git push origin :refs/tags/v2.7.0

# Warn users about the deleted tag
```

## Troubleshooting

### GitHub Actions Fails

Check the workflow logs:
1. Go to Actions tab
2. Click on failed workflow
3. Check error messages
4. Common issues:
   - Missing GITHUB_TOKEN permissions
   - Docker build errors
   - Multi-architecture build issues

### PyPI Upload Fails

Common issues:
- Version already exists (can't overwrite)
- Missing credentials (need API token)
- Invalid package format

Solutions:
```bash
# Check package before upload
twine check dist/*

# Use API token for authentication
# Create at: https://pypi.org/manage/account/token/
```

## Automation Ideas

Consider automating releases with:

### Release Please (GitHub Action)

Automatically creates releases based on Conventional Commits:
```yaml
name: Release Please
on:
  push:
    branches:
      - main
jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: google-github-actions/release-please-action@v3
        with:
          release-type: python
          package-name: kimai-mcp
```

### Conventional Commits

Use commit message format:
```
feat: Add new feature (triggers minor version bump)
fix: Fix bug (triggers patch version bump)
feat!: Breaking change (triggers major version bump)
```

## Release Schedule

Consider establishing a release schedule:

- **Patch releases**: As needed for critical bugs
- **Minor releases**: Monthly or bi-monthly for new features
- **Major releases**: Yearly or when breaking changes are needed

## Support Policy

Document which versions are actively supported:

- **Current version (2.7.x)**: Full support
- **Previous minor (2.6.x)**: Security fixes only
- **Older versions (<2.6)**: End of life

Update this in README.md or create SECURITY.md.
