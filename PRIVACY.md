# Privacy policy

Last updated: 2026-11-24

PoENavi is a local desktop application. It does not include telemetry, advertising, user accounts, or analytics, and the project operator does not run a server that receives PoENavi user data.

## Data processed on the user's computer

Depending on the enabled features, PoENavi processes the following information locally:

- Path of Exile `Client.txt` entries used to detect area, level, campaign progress, and optional hideout-stay notifications in Poetore
- item text copied to the Windows clipboard when the user requests a price search
- PoENavi settings, notes, guide edits, timer records, window positions, and cached prices
- the Path of Exile process name, process status, and window position used to identify the target game window
- images of user-selected screen regions captured on demand for local OCR (PoE1 Heist rewards/trinkets, PoE2 Expedition rewards, and PoE2 Abyss Desecration modifiers)

Settings, notes, timer records, and caches are stored under `%APPDATA%\PoENavi\` (and optional high-accuracy OCR packs under `%LOCALAPPDATA%\PoENavi\ocr-packs\`), while game logs remain in the user's selected Path of Exile log location. PoENavi does not transmit `Client.txt`, personal notes, timer records, captured screen images, OCR text, or Path of Exile credentials to the project operator or any external server.

## Network connections

PoENavi connects only for the functions described below:

- **GitHub Releases (`api.github.com`, `github.com`)**: in official builds, checks for stable PoENavi updates and, after user confirmation, downloads the release archive and SHA-256 checksum; when OCR numeric rescue is enabled, downloads the optional high-accuracy OCR pack (NDLOCR-Lite) and its SHA-256 checksum.
- **Path of Exile official Trade & Leagues API (`www.pathofexile.com`, `jp.pathofexile.com`)**: after the user requests a price search or league refresh, sends item names, modifiers, numeric filters, league, and related search criteria.
- **Path of Exile official CDN & Currency Exchange (`web.poecdn.com`)**: obtains public item/currency icons and Currency Exchange reference data.
- **poe.ninja (`poe.ninja`)**: obtains public currency and item reference prices.
- **PoE Wiki (`www.poewiki.net`)**: obtains public item images used in search results.
- **VOICEVOX Engine (`http://127.0.0.1:50021`, local PC only)**: when PoE2 Mini-Navi voice guidance is enabled, sends guide text locally to the user's own VOICEVOX process.
- **PoELab and external information pages**: opens a page in the user's default browser only after the user selects the corresponding action.

As with ordinary web requests, external services can receive the user's IP address, request time, user-agent information, and the request data described above. Their processing is governed by their own privacy policies and terms.

## Input and system interaction

PoENavi can monitor configured global hotkeys and Raw Input mouse wheel events (for stash tab scrolling). In response to a user action, it can send key input for copying item text, pasting search text, scrolling stash tabs, or sending a configured Path of Exile chat command. OCR features are manually initiated, read-only, and never generate game input. If the user enables and invokes the logout feature, PoENavi deletes the Path of Exile client's matching TCP connection through the Windows API.

PoENavi does not read or modify game memory, inject code into the game, intercept or alter network packets, collect Path of Exile authentication data, or perform autonomous gameplay.

## Updates and system changes

PoENavi is distributed as a portable ZIP and does not install a Windows service. Automatic updates apply only in official builds after the user accepts the update prompt; fork builds do not overwrite themselves with upstream releases. The updater verifies the downloaded SHA-256 checksum, replaces files in the PoENavi application folder, and preserves a rollback copy while confirming that the updated application starts.

## Deletion and uninstallation

Delete the extracted PoENavi application folder to remove the program. To remove local settings, notes, caches, and records as well, delete `%APPDATA%\PoENavi\` (and `%LOCALAPPDATA%\PoENavi\ocr-packs\` if the optional OCR pack was installed). Users should back up any records they want to keep before deletion.

## Contact

Privacy questions regarding the official release can be submitted through [upstream GitHub Issues](https://github.com/buri34/poenavi/issues). Questions specific to this fork can be raised via [this fork's repository](https://github.com/devunit47/poenavi). Do not include account credentials, private log content, or other sensitive information in a public issue.
