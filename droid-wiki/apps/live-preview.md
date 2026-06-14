# Live preview

## Purpose

A single-page web app at [statusline.nvision.me](https://statusline.nvision.me) that lets users preview the three statusline tiers and pick which one they want before installing.

## Implementation

`public/index.html` is a self-contained HTML file (21KB) with inline CSS and JavaScript. It renders:

- Visual previews of minimal, standard, and full tiers using the same SVG assets from `assets/`
- Tier comparison table
- Copy-paste install instructions for the selected tier
- Links to the GitHub repository

The page has no backend dependencies. It is served as a static file.

## Key source files

| File | Purpose |
|------|---------|
| `public/index.html` | Live preview and tier picker page |
| `assets/tier-minimal.svg` | Minimal tier preview image |
| `assets/tier-standard.svg` | Standard tier preview image |
| `assets/tier-full.svg` | Full tier preview image |
