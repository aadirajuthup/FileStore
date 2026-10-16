# AGENTS.md — FileStore (Codeflix-Bots/FileStore fork)

> For any AI agent working on this repo. Read this before touching code.
> Stack truth, live deployment truth, known bugs with `file:line`, and what the rewrite must test.
>
> FIX LOG 2026-10-17 (this checkout): video-delivery path hardened and verified
> (`py_compile` clean on all modules; decode/caption/fsub/filter logic unit-checked).
> Fixed: `//` decode (`start.py`), caption helper + `parse_mode=HTML` + no-silent-fail on empty delivery
> (`start.py`), `get_messages` UnboundLocal guard + `get_message_id` `(0,0)` fallthrough
> + fail-closed `is_user_subscribed` + Try-Again slash + `url=None` button guard (`helper_func.py`),
> shortener truly off when creds blank (`bot.py`/`start.py`, `requests` timeout), `batch` same-channel +
> order + 200-cap validation and `nbatch` 1–200 cap (`link_generator.py`), `channel_post` excludes
> `nbatch` + writes to `primary_db_channel` (`channel_post.py`), `full_userbase` drops config docs
> (`database.py`), `/`+`/health`+catch-all 404 + README path (`route.py`), loopback bind + `int(PORT)`
> + no `sys.exit()` in async + admins list copy (`bot.py`), `LOGGER` handler guard (`config.py`),
> `startswith` tuple fixes (`settings.py`). Template `DB_CHANNEL` now `0` (was empty → SyntaxError).
> Still open (see §5.2/5.4/5.5): panel persistence for auto_del/protect/texts/admins, atomic DB writes,
> indexes, broadcast throttle, `.gitignore`/secrets, Dockerfile hardening.
>
> RELIABILITY 2026-10-17 (this checkout, one commit per item, pushed as Yato):
> 1. Stateless fsub gate (`helper_func.py:check_subscription`): live `get_chat_member` per tap,
>    zero per-tap membership writes (events in `join_request.py` own all rows). Per-channel policy
>    `entry[4]` (`normalize_fsub_entry`/`fsub_request_enough`, default True=legacy): True = pending
>    join-request unlocks, False = must already be joined. Toggled in-chat (`toggle_fsub_reqmode`
>    in `force_sub.py`), shown in both fsub panels. Approved-but-left and no-request both read BANNED,
>    so join-leave-reopen is blocked again. `is_user_subscribed` stays fail-closed.
> 2. Explicit batch snapshots: `/batch`+`/nbatch` resolve the range at mint via `_snapshot_range`
>    (`link_generator.py`), store `{channel_id, msg_ids, missing_ids, created_by}` in new `batches`
>    collection (`database.py:save_batch/get_batch`), link carries `batch-<id>` (40 chars, fits the
>    64-char start-param budget). Mint warns about holes; `start.py` decodes `batch-` links, keeps
>    legacy `get-` range links working, and warns when delivery finds fewer than requested.
> 3. Structured stdout logs: `new_op`/`op_log` (`helper_func.py`) print one JSON line per event
>    (`op, module, action, outcome` + fields) and mirror to `LOGGER`. Mint (`channel_post.py`,
>    `link_generator.py`), gate verdict per channel (`force_sub` wrapper, op shared with handler via
>    `message.op_id`), open/decode/fetch/per-file delivery + autodel schedule (`start.py`),
>    autodel fire (`batch_auto_del_notification(op=...)`), broadcast start/progress-every-200/
>    finish/floodwait (`broadcast.py`). No tokens/keys are ever logged.

## 1. What this is

Telegram file-store bot. Flow: admin DMs file to bot (or posts in vault) → bot copies into private backup channel (`DB_CHANNEL`) → mints `t.me/<bot>?start=<base64>` link → user clicks → force-sub gate → shortener gate → bot `copy()`s vault message to user → auto-delete timer.

- Upstream: `Codeflix-Bots/FileStore` (fork of `CodeXBotz/File-Sharing-Bot`). Python, **Pyrogram fork `pyrofork==2.3.50`** (imports as `pyrogram.*`), MongoDB via `motor`.
- License GPL-3.0. Personal use only — license not a constraint.
- Mongo stores **zero file bytes**: user/channel/premium/fsub/settings docs only. Links are stateless arithmetic, not DB lookups.

## 2. Live deployment (truth, 2026-10-16)

- Host: Oracle A1 ARM64, 12 GB (`ubuntu@instance-a1-20230513-1634`). NOT the 1 GB x86 boxes.
- Path: `~/telegram-bots/filestore-0/` (`SESSION = "filestore-0"` → `filestore-0.session` in CWD).
- Service: `filestore-0.service` — `systemctl status filestore-0`, enabled on boot. Venv `.venv`, `main.py` entry.
- DB: Atlas M0 `ClusterZero` (free). `DB_NAME = "filestore-0"`. Collections auto-created on first write.
- Env: no Docker, no `.env` — everything in `config.py` (see §3). `PORT = '5010'` is a **string** in config (must `int()` before `TCPSite`).

## 3. config.py (redacted snapshot — live values)

```python
OWNER_ID = 6809310728
ADMINS = [6809310728, 5450362722, 8317194788]  # effective admins = ADMINS + OWNER_ID (bot.py:34)
SESSION = "filestore-0"
WORKERS = 4
DB_NAME = "filestore-0"
FSUBS = []                 # managed in-chat afterwards; [channel_id, request_enabled, timer_min]
DB_CHANNEL = -1004428586726  # MUST be bare int, no quotes — arithmetic is done on it
AUTO_DEL = 900             # seconds; 0 = disabled
DISABLE_BTN = True         # True = vault posts get NO Share-URL button; DM-to-bot still replies with link
PROTECT = True             # protect_content on delivered copies
SHORT_URL/SHORT_API = ""   # blank = shortener disabled in practice, BUT flag defaults True (see §5.3)
MESSAGES.START_PHOTO = "https://i.ibb.co/nsZQBVcz/download-1.jpg"
MESSAGES.FSUB_PHOTO  = "https://i.ibb.co/fVV2zPxG/....jpg"
MESSAGES.SHORT_PIC / SHORT = ""  # unused while shortener blank
MSG_EFFECT = 5046509860389126442  # greeting animation only (start.py:274,281); ignore
```

Rules: bot must be admin in `DB_CHANNEL` (post/edit/delete) and in every force-sub channel. Never delete vault posts — each post IS the file; deleting kills its link permanently. Don't post-then-forward the same file (orphan double-copy).

## 4. Link math (must understand before editing)

- Encode: `converted = vault_msg_id * abs(vault_channel_id)` → `get-<converted>` (single) or `get-<start*mult>-<end*mult>` (batch). Base64-urlsafe, `=` stripped. `helper/helper_func.py:13-26`, `plugins/channel_post.py:23-25`, `plugins/link_generator.py:89,126,170`.
- Decode (`plugins/start.py:79-157`): tries primary multiplier first via `encoded % mult == 0`, else secondaries, else fallback to primary. **Current code uses float `/` (`int(x/y)`) — must be `//`; values ~1e15 risk precision loss → off-by-one msg_id.**
- Fetch: `client.get_messages(source, ids)` → filter `None` → fallback `get_messages_from_db_channels` (primary then actives). Deleted vault msg → `[]` → user sees "Couldn't find the files in the database." (`start.py:203-204`). That is the durable-link failure mode.
- `nbatch N` = blind range `first … first+N-1` (`link_generator.py:168`). Any gap (service msg, deleted post, test-delete at `bot.py:145`) = broken/short batch, no warning.
- `batch` discards 2nd message's channel (`link_generator.py:80` `s_msg_id, _ = ...`, encodes both with first channel) — cross-channel batch corrupts.

## 5. Known bugs (verified in code — fix or test in rewrite)

### 5.1 "Upload video → link → nothing delivered" (reported 2026-10-12)
Pasted `systemctl` log (`GET default.asp → InvalidURLError 400`) is **unrelated scanner noise** hitting the aiohttp web server (`bot.py:172-176` binds `0.0.0.0:5010`, only `GET /` exists). It never reaches bot logic; ignore / filter access log. Real delivery failure leaves **no traceback** because copy errors are swallowed (`start.py:234-236: pass`, `helper_func.py:30-44` bare `except: pass` → even `UnboundLocalError`). Suspects in order:
1. **Shortener gate** (`start.py:51-76`): non-premium + `shortner_enabled` default `True` (`bot.py:133,140`) → bot sends SHORT_PIC/SHORT_MSG + Open-Link and `return`s. First click looks dead; user must click twice. With blank `SHORT_API`, `get_short` falls back to long URL but hop remains. Dead `SHORT_PIC` URL → `send_photo` throws outside `try` → handler dies, zero files.
2. **FSUB gate** — expected block, not a bug, but UX-identical ("no file").
3. **Caption path** (`start.py:209-214`): `CAPTION` template only applied `if msg.document`; video/photo/audio fall through to `msg.caption.html` with **no `parse_mode='html'`** on `msg.copy()` → HTML-caption videos can throw → swallowed → `yugen_msgs=[]` yet auto-del checks original `messages`, so user gets nothing + no error.
4. **Float decode** (§4) → wrong `msg_id` → `[]` → "Couldn't find files".
5. **Vault msg deleted / secondary failover miss** → `[]`.
6. `channel_post.py:9` filter omits `nbatch` → `/nbatch` also triggers `channel_post` copy race/dupe.

### 5.2 Settings that revert on restart (in-memory only, dead persistence helpers)
- REVERT: `auto_del`, `protect` (`settings.py:472,492` memory-only; `database.py:639,626,711,722` setters never called; `bot.py:36-37` reload from config). `disable_btn` has no toggle at all. Texts/photos/reply (`texts.py:35,52,68,84`, `settings.py:527-583`; `update_message_setting` never called; `bot.py:35,40`). Admins (`admins.py:149,172` mutate `client.admins` only; `mongodb.add/remove_admin` never called; `bot.py:34` seeds from config, `start()` never `get_admins_list`; also aliases config list object when owner present → mutates global).
- PERSIST (do not regress): fsub add/remove (`force_sub.py`, `bot.py:76-98`), `req_channels` (`bot.py:98`), shortener (`shortner.py`, `bot.py:127-140`), db_channels (`settings.py`, `bot.py:100-125`).
- All read-modify-write whole-doc ops in `database.py` race under concurrent admin edits — use atomic `$set`/dot-notation.

### 5.3 Shortener / premium / request quirks
- `shortner_enabled` defaults `True` even with blank creds. `get_short` uses blocking `requests.get` with no timeout in async loop (`shortner.py:17,35,65,239`; `start.py:53`) — stalls event loop. Cache `shortened_urls_cache` unbounded; panel prints full `short_api` secret (`shortner.py:79`).
- `/request` (premium feature-request) ≠ join-request review. Join-request channels: `join_request.py:6` listens `filters.channel` only (supergroup requests missed); `request_id` always `None` (`getattr(join_request,'id',None)` — field doesn't exist); never calls approve/decline; `check_subscription` treats `pending` as `MEMBER` (`helper_func.py:235-255,267-273`) so request-gate grants files pre-approval (bypass by design).
- `is_user_subscribed` fail-open: all-`None` statuses (bot not admin → `Forbidden`) → `all([])==True`... wait, `bool(statuses)` non-empty but generator filters `None` → `all([])` = `True` → delivers without check. Conversely `Try Again` link has extra `/` (`t.me/{user}/?start=`, `helper_func.py:369`) — can drop payload on some clients.
- `force_sub` per-click `create_chat_invite_link` failure → `Button(url=None)` crash → nothing delivered; `[request=True,timer>0]` overwrites link to `None` (`bot.py:63-69`).

### 5.4 DB / Atlas M0
- `user_data` collection overloaded: user docs `{_id:int}` collide with config docs `{_id:1,"fsub_channels","shortner_settings","db_channels","bot_settings","messages_settings","admins_list"}`. `full_userbase()` returns config docs → inflated `/users`, broadcast tries `chat_id=1/strings` → `unsuccessful` + may `del_user` config docs (`database.py:111-113`, `admins.py:36`, `broadcast.py:12,24,75`).
- `add_user` no dup guard; only `start.py` catches `DuplicateKeyError`, concurrent joins elsewhere crash. No indexes anywhere. `channels.users[]` unbounded (`$addToSet`) → 16 MB doc cap. Naive `datetime.now()` vs Mongo UTC breaks `is_pro`/expiry. `bulk_update_user_statuses` builds dicts, motor needs `UpdateOne` objects → dead code. Stats `aggregate($group)` (`database.py:318,325,400,408`) risks M0 100 MB stage cap + no `allowDiskUse` — replace with `count_documents`.
- Expired premium docs never swept (no scheduler; `cleanup_database` uncalled).
- `bot.py:102-123` prunes unreachable DB channels on boot + manual `removedb` → old links die silently. Secondary posts never get auto-links (`channel_post.py:39` checks primary only; `disable_btn=True` kills all).

### 5.5 Web / ops / deps (prod-readiness)
- `PORT` str vs `TCPSite(int)` (`config.py:6`, `bot.py:176`); `route.py:74` hardcodes `8080`. Only `GET /` exists and it reads `plugins/README.md` which doesn't exist → `/` always 404. No `/health`, no catch-all → scanner probes (`default.asp`, etc.) log `InvalidURLError` noise. Binds `0.0.0.0` unnecessarily; `main.py:34-36` `gather(main(),web_app())` no shared shutdown. `sys.exit()` inside `async start()` (`bot.py:73,155`) leaks Client/Mongo/AppRunner.
- `LOGGER()` (`config.py:54-67`) appends handlers **every call** → dup logs + FD leak. `50MB×10` log files = 500 MB disk risk. `print()` in broadcast/database bypasses logging.
- `requirements.txt`: only `pyrofork` pinned; `asyncio` listed (stdlib, bogus); `TgCrypto` needs gcc on ARM (no aarch64 wheel for py3.10) — fine on 12 GB box, OOMs on 1 GB; consider `pycryptodome` or prebuilt wheel. `ListenerTimeout` import assumes pyromod-fork behavior — brittle.
- Broadcast: no throttle/sleep/progress/cancel; single `FloodWait` retry then abort; `pin` doubles calls; `/users` loads all docs for `len()`.
- `client.ask(..., timeout=60)` (`settings/admins/texts/force_sub/batch/genlink`) often outside `try` → `ListenerTimeout` crashes handler. `settings.py:489` `startswith('+' or '-')` ≡ `'+'`; `startswith('https://' or 'http://')` ≡ `'https://'`; photo `res.text` `None` crash.
- No `.gitignore` — `.session` + `bot.log` + `config.py` secrets committable. Docker: unpinned base, root user, `COPY . .` before pip (cache bust), `start.sh` reinstalls deps every boot, shell PID1 breaks signals, no `HEALTHCHECK`/`EXPOSE`/restart policy. No health endpoint to probe.

## 6. Edge-case test matrix (rewrite MUST cover)

Delivery: single video/photo/document/audio with no caption / HTML caption / 2 GB file; link clicked by owner, stranger, banned, premium, expired-premium; FSUBS empty vs 1 public vs 3 mixed (public+private request+timer); join-request pending/approved/left-rejoin; shortener on/off + dead SHORT_PIC; `DISABLE_BTN` both; `PROTECT` both; `AUTO_DEL=0` vs 900 + restart mid-countdown; re-click transfer link after delete.
Vault: DM upload vs vault post vs forward-of-vault-post (no double-copy); vault post deleted → link shows clean "removed" (not silent); secondary DB post; `removedb` non-primary vs primary; restart with DB channel bot-demoted.
Batch: `batch` first-in-A-last-in-B (must reject/retarget, not corrupt); `nbatch` over gap (warn, deliver partial + list missing); reversed range; 200+ batch (chunked fetch); `/usage`-style unknown command ignored gracefully.
Ops: reboot → auto_del/protect/texts/admins persist; Atlas pause/timeout → clean error, no traceback to user; `PORT` int; `/` + `/health` 200, scanner path 404-quiet; broadcast 10k users with FloodWaits (throttle, progress, cancel, dead-ID prune without touching config docs); concurrent admin edits (no lost update); duplicate `/start` race (no crash); `get_chat_member` Forbidden (fail-closed, admin alerted, never free-pass).

## 7. Agent conventions

- Evidence before synthesis: read the handler + helper + DB function; cite `file:line`. Don't trust README (`/usage` doesn't exist; `stats`/`nbatch` exist but undocumented).
- No `sys.exit()` in async; no bare `except: pass`; no blocking `requests` in handlers (use `aiohttp` + timeout); every user-facing `except` → clean message + `LOGGER` with `exc_info`.
- Integer division `//` for ID math; validate `start<=end`, same-channel batch, consecutive IDs; never `Button(url=None)`.
- Type/parity: `DB_CHANNEL: int`, `PORT: int`, `API_ID: int`. Secrets via env, never commit `.session`/`bot.log`/`config.py`.
- Keep diffs small; this bot is live under systemd — confirm `systemctl status filestore-0` + `journalctl -u filestore-0 -f` + `bot.log` after any change.
