# CLAUDE.md

Andiamo is a Home Assistant custom integration (installed through HACS) that tells the user when to leave: for a public transport departure (opentransportdata.swiss OJP) or to reach a place by car on time (TomTom Routing).

Simplicity is key: prefer inline, fast flows over dialogs and extra steps.

## Commands

- Tests (WSL): `wsl -d Ubuntu -- bash scripts/test.sh`
- Throwaway test HA on port 8123: `scripts/dev-ha.sh` to start, `scripts/dev-stop.sh` to stop, `scripts/dev-onboard.sh` for first-time setup

## Gotchas

- From Git Bash, run WSL commands with `MSYS_NO_PATHCONV=1` and pipe output through `tr -d '\0'`. Put anything with nested quotes in a script.
- Scripts must be LF (`.gitattributes` enforces it). Never `pkill -f`; it kills its own shell.
- HA reloads Python code and the JS file fingerprint only on restart; the card needs one extra plain reload after that.
- New websocket commands must be added to the register tuple in `websocket.py`.

## Conventions

- Check current official docs (OJP, TomTom Routing, Home Assistant developer docs) before coding against an API.
- The UI is English only (panel, card, setup form). Speaker announcements are German (default) or English.
- German texts use Swiss spelling ("ss", never "ß") and the informal "du". English texts use American spelling.
- Changes go in `CHANGELOG.md`. To release: bump `version` in `manifest.json`, date the changelog section, push a `vX.Y.Z` tag (HACS installs from these), then `gh release create` with that section as the notes. GitHub Actions only validates (HACS and hassfest).
- Every change gets its own branch off an up-to-date main. After a merge: pull main, delete the branch (`-d`), `git fetch --prune`.
- Commit as `geeForceOne <1780268+geeForceOne@users.noreply.github.com>`, with messages that explain why.
- Nothing secret is committed (API keys, `.env`, local settings, the test HA's config and storage). Check staged files before every commit.
