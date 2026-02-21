# blogging

[![Build and Deploy Site](https://github.com/r-leyshon/blogging/actions/workflows/build-deploy.yml/badge.svg)](https://github.com/r-leyshon/blogging/actions/workflows/build-deploy.yml)

Musings, ramblings, generally putting things down in text so I don't forget them.

## Deployment

The site is built and deployed automatically via GitHub Actions:

- **Pull requests** → preview deploy to Netlify
- **Merge to main** → production deploy

The `docs/` folder is gitignored and built fresh in CI.

## Local Development

```bash
# Preview the site locally
quarto preview

# Full render (if needed)
make site
```

The `make site` command runs `quarto render` followed by a Python script that fixes nested listing files.

## Quarto Notes

- Use `quarto render` (CLI) rather than the GUI render button for full site builds.
- The site uses `freeze: auto` - code execution results are cached in `_freeze/`.
- If you modify a blog with code cells, render locally first to update the freeze cache.
- Article-specific conda environments live in `environments/` (gitignored).

## Secrets

For music reviews (Spotify integration), create a `.secrets.toml` in the project root:

```toml
[spotify]
client_id = "<INSERT_CLIENT_ID>"
client_secret = "<INSERT_CLIENT_SECRET>"
```

Get credentials from the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
