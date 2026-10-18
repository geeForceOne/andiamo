# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Andiamo is a Home Assistant custom integration (installed through HACS) that tells the user when to leave: to catch a public transport departure, or to reach a place by car on time. It is still in the design phase; no code yet.

- **Simplicity is key.** The user's own words: prefer inline, fast flows over dialogs and extra steps.

## Workflow

When the user gives feedback or requests changes in a back-and-forth (bug reports, tweaks, "also do X"), don't implement each one immediately as it comes in. Acknowledge it, queue it, and keep gathering. Only start making changes once the user explicitly says "go" (or an equally unambiguous confirmation). Purely informational questions can still be answered right away.

## Git workflow

Never run `git commit` or `git push` unless the user explicitly asks for it in that turn. A commit approval does not imply a push approval, and approval from an earlier turn does not carry forward to later changes. Every change starts on its own branch off an up-to-date main; after a merge, pull main, delete merged branches (`-d`) and `git fetch --prune`. Commit as `geeForceOne <1780268+geeForceOne@users.noreply.github.com>`, never with a real name or Gmail. Write commit messages that explain why.

Nothing secret is ever committed: API keys (opentransportdata.swiss, TomTom), `.env`, local settings, a test Home Assistant's config and storage. Check staged files before every commit.

## Releases

Changes are recorded in `CHANGELOG.md`. Releases are tagged `vX.Y.Z` (HACS installs from these tags), and GitHub Actions builds the release.

## Conventions

- **Verify external APIs, don't work from memory.** Check current official docs (OJP / opentransportdata.swiss, TomTom Routing, Home Assistant developer docs) before coding against a library or service.
- **The UI is English only** (panel, card, setup form), whatever HA's language. Speaker announcements are German (default) or English, a setting.
- **German texts** (announcements) use Swiss spelling ("ss", never "ß") and address the user with the informal "du". English texts use American spelling.
