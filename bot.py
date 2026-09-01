"""
╔══════════════════════════════════════════════════════════════════════╗
║   🚀 TELEGRAM SUPPORT FORM MASS-BLASTER v3.0                         ║
║──────────────────────────────────────────────────────────────────────║
║   ⚡ Concurrent form submissions (parallel workers, blazing fast)   ║
║   ✅ Bulletproof proxy validation (real HTTPS test, not just TCP)   ║
║   ✅ Per-submission retry with proxy rotation (up to 8 attempts)    ║
║   ✅ Dead proxy auto-eviction + background pool refill              ║
║   ✅ Owner + Sudo access control (/sudo /rmsudo /sudolist)          ║
║   ✅ Stylish access-denied UI with Contact button                   ║
║   ✅ Hidden /addgif command (owner-only) for custom denial media    ║
║   ✅ No direct fallback — always via proxy (unless pool empty)      ║
║   ✅ Bigger pool (up to 150 validated proxies)                      ║
║   ✅ Concurrent proxy testing (10x faster reload)                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import json
import random
import sys
import os
import urllib.request
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Set

import aiohttp
from aiohttp_socks import ProxyConnector, ProxyType

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes,
)

# ═══════════════════════════════════════════════════════════════════
# 🔐 CONFIG
# ═══════════════════════════════════════════════════════════════════
BOT_TOKEN   = os.getenv("BOT_TOKEN", "8805646310:AAF0oIReNkBfT7ca3oASIGx-n6K4GoMKh8I")
BOT_VERSION = "3.0"

# 🔑 OWNER — set your Telegram user ID here (integer)
OWNER_ID = int(os.getenv("OWNER_ID", "6980326908"))

# 📎 Contact for access requests (Telegram username, WITHOUT @)
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "Someattachment")

# 🌐 Target
FORM_URL  = "https://telegram.org/support"
FORM_POST = "https://telegram.org/support"

# ⚙️ Tunables
MAX_POOL_SIZE      = 150
MIN_POOL_REFILL    = 25
PROXY_TEST_TIMEOUT = 6
SUBMIT_TIMEOUT     = 18
MAX_ATTEMPTS       = 8
CONCURRENT_TESTS   = 60
CONCURRENT_SUBMITS = 12   # 🔥 parallel form submissions
BATCH_STATUS_EVERY = 5    # send status update every N submissions

# 📂 Data files (persistent)
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR = DATA_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

NAMES_FILE   = DATA_DIR / "names.json"
EMAILS_FILE  = DATA_DIR / "emails.json"
PHONES_FILE  = DATA_DIR / "phones.json"
SUDO_FILE    = DATA_DIR / "sudo.json"
GIF_FILE     = DATA_DIR / "denial_gif.json"   # stores file_id + type

# ═══════════════════════════════════════════════════════════════════
# 🌐 FREE PROXY SOURCES
# ═══════════════════════════════════════════════════════════════════
FREE_PROXY_SOURCES = [
    ("http",   "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"),
    ("socks5", "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

# ═══════════════════════════════════════════════════════════════════
# 🎨 ANSI
# ═══════════════════════════════════════════════════════════════════
class C:
    R = "\033[0m"; B = "\033[1m"; CYN = "\033[96m"; YLW = "\033[93m"
    GRN = "\033[92m"; RED = "\033[91m"; MAG = "\033[95m"

# ═══════════════════════════════════════════════════════════════════
# 📝 LOGGING
# ═══════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S", level=logging.INFO,
)
logger = logging.getLogger("blaster")
live_logs: List[str] = []

# ═══════════════════════════════════════════════════════════════════
# 🌐 GLOBAL STATE
# ═══════════════════════════════════════════════════════════════════
PROXY_LIST: List[dict] = []
DEAD_PROXIES: Set[str] = set()
_refill_lock = asyncio.Lock()

names_list: List[str]  = []
emails_list: List[str] = []
phones_list: List[str] = []
sudo_users: Set[int]   = set()

denial_media: Dict[str, str] = {}  # {"type": "gif"|"video"|"photo"|"animation", "file_id": "..."}

running_jobs: Dict[int, bool] = {}

# Conversation states
ADD_NAMES, ADD_EMAILS, ADD_PHONES, FORM_MSG, FORM_COUNT = range(5)
WAIT_GIF = 100

# ═══════════════════════════════════════════════════════════════════
# 🧰 UTILITIES
# ═══════════════════════════════════════════════════════════════════
def add_log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    live_logs.append(entry)
    if len(live_logs) > 500:
        live_logs.pop(0)
    logger.info(msg)
    try:
        with open(LOGS_DIR / f"activity_{datetime.now().strftime('%Y-%m-%d')}.log", "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass

def get_logs(limit: int = 50) -> str:
    return "\n".join(live_logs[-limit:]) if live_logs else "No logs yet."

# ═══════════════════════════════════════════════════════════════════
# 💾 JSON HELPERS
# ═══════════════════════════════════════════════════════════════════
def load_json_list(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception as e:
        logger.error(f"Load fail {path}: {e}")
        return []

def save_json_list(path: Path, data: List[str]):
    try:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:
        logger.error(f"Save fail {path}: {e}")

def load_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def save_json_dict(path: Path, data: dict):
    try:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)
    except Exception as e:
        logger.error(f"Save dict fail {path}: {e}")

def load_all_lists():
    global names_list, emails_list, phones_list, denial_media
    names_list  = load_json_list(NAMES_FILE)
    emails_list = load_json_list(EMAILS_FILE)
    phones_list = load_json_list(PHONES_FILE)
    denial_media = load_json_dict(GIF_FILE)
    add_log(f"📦 Loaded: {len(names_list)} names, {len(emails_list)} emails, {len(phones_list)} phones")

# ═══════════════════════════════════════════════════════════════════
# 🔐 SUDO / OWNER SYSTEM
# ═══════════════════════════════════════════════════════════════════
def load_sudo():
    global sudo_users
    if not SUDO_FILE.exists():
        sudo_users = set()
        return
    try:
        with open(SUDO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        sudo_users = set(int(x) for x in data if str(x).lstrip("-").isdigit())
    except Exception as e:
        logger.error(f"Sudo load fail: {e}")
        sudo_users = set()

def save_sudo():
    try:
        tmp = SUDO_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sorted(sudo_users), f, indent=2)
        tmp.replace(SUDO_FILE)
    except Exception as e:
        logger.error(f"Sudo save fail: {e}")

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in sudo_users

# ═══════════════════════════════════════════════════════════════════
# 🚫 ACCESS-DENIED UI (fancy + Contact button + optional GIF/video)
# ═══════════════════════════════════════════════════════════════════
def denial_caption() -> str:
    return (
        "╔══════════════════════════════╗\n"
        "║   🔒  <b>ACCESS RESTRICTED</b>   ║\n"
        "╚══════════════════════════════╝\n\n"
        "👋 <b>Hey there!</b>\n\n"
        "⛔ You don't have permission to use this bot.\n"
        "🛡️ This is a <b>private tool</b> — access is granted by the owner only.\n\n"
        "💎 <b>Want in?</b>\n"
        "Tap the button below to contact the owner and request access.\n\n"
        f"📩 <b>Contact:</b> @{CONTACT_USERNAME}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 <i>Powered by TG Form Blaster v" + BOT_VERSION + "</i>"
    )

def denial_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Contact Owner", url=f"https://t.me/{CONTACT_USERNAME}")],
    ])

async def send_denial(update: Update):
    """Send stylish access-denied message with optional GIF/video + Contact button."""
    chat = update.effective_chat
    if not chat:
        return
    caption = denial_caption()
    kb = denial_kb()
    try:
        if denial_media and denial_media.get("file_id"):
            mtype = denial_media.get("type", "animation")
            fid   = denial_media["file_id"]
            if mtype == "video":
                await chat.send_video(video=fid, caption=caption, parse_mode="HTML", reply_markup=kb)
            elif mtype == "photo":
                await chat.send_photo(photo=fid, caption=caption, parse_mode="HTML", reply_markup=kb)
            else:  # animation / gif
                await chat.send_animation(animation=fid, caption=caption, parse_mode="HTML", reply_markup=kb)
            return
    except Exception as e:
        logger.error(f"Denial media send fail: {e}")
    # Fallback: plain styled message
    try:
        await chat.send_message(caption, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass

async def guard(update: Update) -> bool:
    """Return True if user allowed; else notify + return False."""
    uid = update.effective_user.id if update.effective_user else 0
    if is_authorized(uid):
        return True
    await send_denial(update)
    add_log(f"🚫 Unauthorized access attempt by {uid}")
    return False

def _resolve_target_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> Optional[Tuple[int, str]]:
    msg = update.message
    if not msg:
        return None
    # Reply
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        name = u.full_name or (u.username or str(u.id))
        return (u.id, f"{name} (id: {u.id})")
    # Arg
    args = ctx.args if ctx.args else []
    if args:
        arg = args[0].strip().lstrip("@")
        if arg.lstrip("-").isdigit():
            return (int(arg), f"user id {arg}")
        return None
    return None

# ═══════════════════════════════════════════════════════════════════
# 🎛️ KEYBOARDS
# ═══════════════════════════════════════════════════════════════════
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Names",   callback_data="MENU|add_names"),
         InlineKeyboardButton("📧 Add Emails",  callback_data="MENU|add_emails")],
        [InlineKeyboardButton("📱 Add Phones",  callback_data="MENU|add_phones"),
         InlineKeyboardButton("📋 View Lists",  callback_data="MENU|view")],
        [InlineKeyboardButton("🚀 Submit Form", callback_data="MENU|submit"),
         InlineKeyboardButton("⛔ Stop",        callback_data="MENU|stop")],
        [InlineKeyboardButton("🌐 Proxy",       callback_data="MENU|proxy"),
         InlineKeyboardButton("🔄 Reload",      callback_data="MENU|reload")],
        [InlineKeyboardButton("📊 Logs",        callback_data="MENU|logs"),
         InlineKeyboardButton("🗑️ Clear",      callback_data="MENU|clear")],
        [InlineKeyboardButton("❔ Help",        callback_data="MENU|help")],
    ])

def clear_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Names",  callback_data="CLR|names"),
         InlineKeyboardButton("📧 Emails", callback_data="CLR|emails")],
        [InlineKeyboardButton("📱 Phones", callback_data="CLR|phones"),
         InlineKeyboardButton("💣 ALL",    callback_data="CLR|all")],
        [InlineKeyboardButton("⬅️ Back",   callback_data="MENU|home")],
    ])

# ═══════════════════════════════════════════════════════════════════
# 🌐 PROXY MANAGEMENT — HARDENED
# ═══════════════════════════════════════════════════════════════════
def proxy_key(p: dict) -> str:
    return f"{p['type']}://{p['addr']}:{p['port']}"

def _fetch_proxy_source(ptype: str, url: str) -> List[Tuple[str, str, int]]:
    out = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line or line.startswith("#"):
                continue
            try:
                addr, port = line.split(":", 1)
                addr = addr.strip()
                port = int(port.strip())
                if not addr or port < 1 or port > 65535:
                    continue
                out.append((ptype, addr, port))
            except Exception:
                continue
    except Exception as e:
        add_log(f"⚠️ Proxy source fail: {url} ({type(e).__name__})")
    return out

async def _validate_proxy(p: dict) -> bool:
    try:
        ptype_str = p["type"].lower()
        if ptype_str == "socks5":
            ptype = ProxyType.SOCKS5
        elif ptype_str == "socks4":
            ptype = ProxyType.SOCKS4
        else:
            ptype = ProxyType.HTTP
        connector = ProxyConnector(
            proxy_type=ptype,
            host=p["addr"],
            port=int(p["port"]),
            rdns=True,
        )
        timeout = aiohttp.ClientTimeout(total=PROXY_TEST_TIMEOUT, connect=PROXY_TEST_TIMEOUT)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout,
                                         headers={"User-Agent": random.choice(USER_AGENTS)}) as s:
            async with s.get("https://api.ipify.org?format=text", allow_redirects=False) as r:
                if r.status != 200:
                    return False
                body = (await r.text()).strip()
                parts = body.split(".")
                if len(parts) != 4 or not all(x.isdigit() for x in parts):
                    return False
                return True
    except Exception:
        return False

async def _validate_batch(cands: List[dict], target_needed: int) -> List[dict]:
    good: List[dict] = []
    sem = asyncio.Semaphore(CONCURRENT_TESTS)
    done_event = asyncio.Event()

    async def worker(p: dict):
        if done_event.is_set():
            return
        async with sem:
            if done_event.is_set():
                return
            ok = await _validate_proxy(p)
            if ok:
                good.append(p)
                if len(good) >= target_needed:
                    done_event.set()

    tasks = [asyncio.create_task(worker(p)) for p in cands]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=90)
    except asyncio.TimeoutError:
        for t in tasks:
            if not t.done():
                t.cancel()
    return good

async def load_free_proxies_async(max_proxies: int = MAX_POOL_SIZE):
    global PROXY_LIST
    add_log("🔍 Fetching proxy candidates from sources...")
    loop = asyncio.get_event_loop()

    all_cands: List[dict] = []
    seen: Set[str] = set()

    fetch_tasks = [
        loop.run_in_executor(None, _fetch_proxy_source, ptype, url)
        for ptype, url in FREE_PROXY_SOURCES
    ]
    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception) or not res:
            continue
        for ptype, addr, port in res:
            key = f"{ptype}://{addr}:{port}"
            if key in seen or key in DEAD_PROXIES:
                continue
            seen.add(key)
            all_cands.append({"type": ptype, "addr": addr, "port": port})

    random.shuffle(all_cands)
    add_log(f"🧪 Validating up to {len(all_cands)} candidates (need {max_proxies})...")

    good: List[dict] = []
    batch_size = 400
    for i in range(0, len(all_cands), batch_size):
        need = max_proxies - len(good)
        if need <= 0:
            break
        batch = all_cands[i:i + batch_size]
        picked = await _validate_batch(batch, need)
        good.extend(picked)
        add_log(f"   ↳ batch {i//batch_size + 1}: got {len(picked)} good (total {len(good)})")
        if len(good) >= max_proxies:
            break

    PROXY_LIST = good[:max_proxies]
    add_log(f"✅ Proxy pool ready: {len(PROXY_LIST)} validated working proxies")

async def refill_proxy_pool_if_low():
    if _refill_lock.locked():
        return
    if len(PROXY_LIST) >= MIN_POOL_REFILL:
        return
    async with _refill_lock:
        add_log(f"♻️  Pool low ({len(PROXY_LIST)}) — refilling in background...")
        try:
            await load_free_proxies_async(MAX_POOL_SIZE)
        except Exception as e:
            add_log(f"⚠️ Refill error: {type(e).__name__}: {e}")

def random_proxy(exclude: Optional[Set[str]] = None) -> Optional[dict]:
    exclude = exclude or set()
    pool = [p for p in PROXY_LIST if proxy_key(p) not in exclude]
    if not pool:
        return None
    return random.choice(pool)

def mark_proxy_dead(p: dict):
    if not p:
        return
    key = proxy_key(p)
    DEAD_PROXIES.add(key)
    try:
        PROXY_LIST[:] = [x for x in PROXY_LIST if proxy_key(x) != key]
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════
# 📝 FORM SUBMITTER — RETRY-HARDENED
# ═══════════════════════════════════════════════════════════════════
async def _submit_once_via_proxy(name: str, email: str, phone: str, message: str,
                                  proxy: dict) -> Tuple[bool, str]:
    ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Origin": "https://telegram.org",
        "Referer": "https://telegram.org/support",
        "Content-Type": "application/x-www-form-urlencoded",
        "DNT": "1",
        "Connection": "close",
    }
    form_data = {
        "your_name": name,
        "your_email": email,
        "your_phone": phone,
        "your_message": message,
        "name": name,
        "email": email,
        "phone": phone,
        "message": message,
    }

    ptype_str = proxy["type"].lower()
    if ptype_str == "socks5":
        ptype = ProxyType.SOCKS5
    elif ptype_str == "socks4":
        ptype = ProxyType.SOCKS4
    else:
        ptype = ProxyType.HTTP

    try:
        connector = ProxyConnector(
            proxy_type=ptype,
            host=proxy["addr"],
            port=int(proxy["port"]),
            rdns=True,
        )
        timeout = aiohttp.ClientTimeout(total=SUBMIT_TIMEOUT, connect=8)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
            try:
                async with session.get(FORM_URL, allow_redirects=True) as r0:
                    await r0.read()
            except Exception:
                pass

            try:
                async with session.post(FORM_POST, data=form_data, allow_redirects=True) as r:
                    if r.status in (200, 201, 202, 204, 302, 303):
                        return (True, f"HTTP {r.status}")
                    if r.status != 404:
                        return (False, f"HTTP {r.status}")
            except Exception:
                pass

            async with session.post(FORM_URL, data=form_data, allow_redirects=True) as r:
                if r.status in (200, 201, 202, 204, 302, 303):
                    return (True, f"HTTP {r.status} (fb)")
                return (False, f"HTTP {r.status}")
    except aiohttp.ClientProxyConnectionError:
        return (False, "ProxyRefused")
    except asyncio.TimeoutError:
        return (False, "Timeout")
    except aiohttp.ClientOSError:
        return (False, "ClientOSError")
    except Exception as e:
        return (False, f"{type(e).__name__}")

async def submit_form_with_retries(name: str, email: str, phone: str, message: str,
                                    max_attempts: int = MAX_ATTEMPTS) -> Tuple[bool, str, str, int]:
    tried: Set[str] = set()
    last_status = "no-proxy-available"
    last_ip = "N/A"

    for attempt in range(1, max_attempts + 1):
        if len(PROXY_LIST) < MIN_POOL_REFILL:
            asyncio.create_task(refill_proxy_pool_if_low())

        proxy = random_proxy(exclude=tried)
        if not proxy:
            if attempt == 1:
                last_status = "empty-pool"
            break

        key = proxy_key(proxy)
        tried.add(key)
        last_ip = f"{proxy['addr']}:{proxy['port']} ({proxy['type']})"

        ok, status = await _submit_once_via_proxy(name, email, phone, message, proxy)
        last_status = status
        if ok:
            return (True, status, last_ip, attempt)

        # Evict really-dead proxies
        if status in ("ProxyRefused", "Timeout", "ClientOSError") or status.startswith("HTTP 5"):
            mark_proxy_dead(proxy)

    return (False, last_status, last_ip, len(tried))

# ═══════════════════════════════════════════════════════════════════
# 🎨 UI HELPERS
# ═══════════════════════════════════════════════════════════════════
async def animated_welcome(message) -> "Message":
    frames = [
        "🚀 <b>Starting Form Blaster...</b>\n▱▱▱▱▱▱▱▱▱▱  0%",
        "🚀 <b>Loading modules...</b>\n▰▰▰▱▱▱▱▱▱▱  30%",
        "🌐 <b>Engaging proxy pool...</b>\n▰▰▰▰▰▰▱▱▱▱  60%",
        "🎯 <b>Targeting telegram.org/support...</b>\n▰▰▰▰▰▰▰▰▱▱  80%",
        "✅ <b>READY!</b>\n▰▰▰▰▰▰▰▰▰▰  100%",
    ]
    msg = await message.reply_text(frames[0], parse_mode="HTML")
    for f in frames[1:]:
        await asyncio.sleep(0.35)
        try:
            await msg.edit_text(f, parse_mode="HTML")
        except Exception:
            pass
    return msg

# ═══════════════════════════════════════════════════════════════════
# 🤖 COMMANDS
# ═══════════════════════════════════════════════════════════════════
def welcome_text():
    return (
        f"╔═══════════════════════════════╗\n"
        f"║ 🚀 <b>TG FORM BLASTER v{BOT_VERSION}</b> ║\n"
        f"╚═══════════════════════════════╝\n\n"
        f"🎯 <b>Target:</b> telegram.org/support\n"
        f"🌐 <b>Proxies:</b> {len(PROXY_LIST)} validated\n"
        f"⚡ <b>Concurrency:</b> {CONCURRENT_SUBMITS}x parallel\n"
        f"📦 <b>Lists:</b> {len(names_list)} names | {len(emails_list)} emails | {len(phones_list)} phones\n"
        f"🔐 <b>Sudo users:</b> {len(sudo_users)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>How to use:</b>\n"
        f"1️⃣ Add Names, Gmails, Numbers\n"
        f"2️⃣ Tap 🚀 Submit Form → enter message + count\n"
        f"3️⃣ Bot fires {CONCURRENT_SUBMITS} submissions in parallel\n"
        f"4️⃣ Auto-retry with fresh proxy on failure (up to {MAX_ATTEMPTS}x)\n\n"
        f"👇 Choose an action:"
    )

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    anim = await animated_welcome(update.message)
    await asyncio.sleep(0.2)
    try:
        await anim.edit_text(welcome_text(), parse_mode="HTML", reply_markup=main_menu_kb())
    except Exception:
        await update.message.reply_text(welcome_text(), parse_mode="HTML", reply_markup=main_menu_kb())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        f"📖 <b>HELP — TG Form Blaster v{BOT_VERSION}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>General:</b>\n"
        "🎯 /start — Main menu\n"
        "➕ /addnames — Add bulk names\n"
        "📧 /addemails — Add bulk emails\n"
        "📱 /addnumbers — Add bulk phones\n"
        "📋 /viewlists — Show lists\n"
        "🗑️ /clearlists — Clear lists menu\n"
        "🚀 /submit — Start form blast\n"
        "🌐 /proxy — Proxy pool status\n"
        "🔄 /reload — Refresh proxies\n"
        "📊 /logs — Recent activity\n"
        "⛔ /stop — Stop current job\n"
        "❌ /cancel — Cancel flow\n\n"
        "<b>Owner only:</b>\n"
        "🔑 /sudo &lt;user_id&gt; or reply — grant access\n"
        "❎ /rmsudo &lt;user_id&gt; or reply — revoke access\n"
        "📜 /sudolist — Show sudo users\n\n"
        "<b>How submission works:</b>\n"
        f"• {CONCURRENT_SUBMITS} parallel submissions at once\n"
        f"• Each attempt uses a RANDOM validated proxy\n"
        f"• On failure, auto-rotates up to {MAX_ATTEMPTS} different proxies\n"
        f"• Dead proxies are evicted permanently\n"
        f"• Background refill triggers when pool &lt; {MIN_POOL_REFILL}\n\n"
        "💡 Run /reload before big jobs.",
        parse_mode="HTML"
    )

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("❌ Cancelled. /start for menu.")
    return ConversationHandler.END

# ─── Sudo commands ──────────────────────────────────────────────────
async def sudo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await send_denial(update)
        return
    target = _resolve_target_user(update, ctx)
    if not target:
        await update.message.reply_text(
            "ℹ️ <b>Usage:</b>\n"
            "• Reply to a user's message with /sudo\n"
            "• Or /sudo &lt;numeric_user_id&gt;\n\n"
            "Usernames not supported — need numeric ID.",
            parse_mode="HTML"
        )
        return
    tid, disp = target
    if tid == OWNER_ID:
        await update.message.reply_text("👑 Owner already has full access.")
        return
    if tid in sudo_users:
        await update.message.reply_text(f"ℹ️ Already sudo: {disp}", parse_mode="HTML")
        return
    sudo_users.add(tid)
    save_sudo()
    add_log(f"🔑 Sudo granted to {tid}")
    await update.message.reply_text(
        f"✅ Sudo granted to <b>{disp}</b>\n"
        f"📊 Total sudo users: {len(sudo_users)}",
        parse_mode="HTML"
    )

async def rmsudo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await send_denial(update)
        return
    target = _resolve_target_user(update, ctx)
    if not target:
        await update.message.reply_text(
            "ℹ️ <b>Usage:</b>\n"
            "• Reply to a user's message with /rmsudo\n"
            "• Or /rmsudo &lt;numeric_user_id&gt;",
            parse_mode="HTML"
        )
        return
    tid, disp = target
    if tid not in sudo_users:
        await update.message.reply_text(f"ℹ️ Not a sudo user: {disp}", parse_mode="HTML")
        return
    sudo_users.discard(tid)
    save_sudo()
    add_log(f"❎ Sudo revoked from {tid}")
    await update.message.reply_text(
        f"✅ Sudo revoked from <b>{disp}</b>\n"
        f"📊 Total sudo users: {len(sudo_users)}",
        parse_mode="HTML"
    )

async def sudolist_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await send_denial(update)
        return
    lines = [f"👑 <b>Owner:</b> <code>{OWNER_ID}</code>"]
    if sudo_users:
        lines.append(f"\n🔑 <b>Sudo users ({len(sudo_users)}):</b>")
        for u in sorted(sudo_users):
            lines.append(f"• <code>{u}</code>")
    else:
        lines.append("\nNo sudo users yet.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

# ─── HIDDEN: /addgif (owner only) ───────────────────────────────────
async def addgif_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner-only hidden command. Sets the media shown to non-sudo users."""
    uid = update.effective_user.id
    if not is_owner(uid):
        # Silent: pretend command doesn't exist for non-owners
        await send_denial(update)
        return ConversationHandler.END
    await update.message.reply_text(
        "🎬 <b>Set Denial Media</b>\n\n"
        "Send me a <b>GIF</b>, <b>video</b>, or <b>photo</b> now.\n"
        "It will be shown to non-sudo users when they try to use the bot.\n\n"
        "Send /cancel to abort.\n"
        "Send <code>clear</code> to remove the current media.",
        parse_mode="HTML"
    )
    return WAIT_GIF

async def receive_gif(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    global denial_media
    uid = update.effective_user.id
    if not is_owner(uid):
        return ConversationHandler.END

    msg = update.message
    if not msg:
        return WAIT_GIF

    # Text handling
    if msg.text:
        t = msg.text.strip().lower()
        if t == "clear":
            denial_media = {}
            save_json_dict(GIF_FILE, denial_media)
            await msg.reply_text("🗑️ Denial media cleared. Default text will be shown.")
            return ConversationHandler.END
        await msg.reply_text("⚠️ Send an actual GIF/video/photo, or /cancel.")
        return WAIT_GIF

    file_id = None
    mtype = None
    if msg.animation:
        file_id = msg.animation.file_id
        mtype = "animation"
    elif msg.video:
        file_id = msg.video.file_id
        mtype = "video"
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        mtype = "photo"
    elif msg.document and msg.document.mime_type and "gif" in msg.document.mime_type.lower():
        file_id = msg.document.file_id
        mtype = "animation"

    if not file_id:
        await msg.reply_text("⚠️ Unsupported media. Send GIF / video / photo, or /cancel.")
        return WAIT_GIF

    denial_media = {"type": mtype, "file_id": file_id}
    save_json_dict(GIF_FILE, denial_media)
    add_log(f"🎬 Denial media updated ({mtype}) by owner")
    await msg.reply_text(
        f"✅ Denial media set!\n"
        f"📂 Type: <b>{mtype}</b>\n\n"
        f"Non-sudo users will now see this along with the access-denied message.",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ─── Add Names ──────────────────────────────────────────────────────
async def addnames_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await guard(update):
        return ConversationHandler.END
    await _ask_add_names(update.effective_chat.send_message)
    return ADD_NAMES

async def _ask_add_names(send):
    await send(
        "➕ <b>ADD NAMES</b>\n\n"
        "Send names — one per line.\n"
        "Example:\n"
        "<code>Rahul Sharma\nPriya Patel\nAman Kumar</code>\n\n"
        "/cancel to abort.",
        parse_mode="HTML")

async def receive_names(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    new = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not new:
        await update.message.reply_text("⚠️ Empty. Try again or /cancel:")
        return ADD_NAMES
    before = len(names_list)
    for n in new:
        if n not in names_list:
            names_list.append(n)
    save_json_list(NAMES_FILE, names_list)
    add_log(f"➕ Added {len(names_list) - before} names")
    await update.message.reply_text(
        f"✅ Added <b>{len(names_list)-before}</b> new names\n"
        f"📊 Total: <b>{len(names_list)}</b>",
        parse_mode="HTML", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ─── Add Emails ─────────────────────────────────────────────────────
async def addemails_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await guard(update):
        return ConversationHandler.END
    await _ask_add_emails(update.effective_chat.send_message)
    return ADD_EMAILS

async def _ask_add_emails(send):
    await send(
        "📧 <b>ADD GMAILS / EMAILS</b>\n\n"
        "Send emails — one per line.\n"
        "Example:\n"
        "<code>rahul123@gmail.com\npriya.p@gmail.com</code>\n\n"
        "/cancel to abort.",
        parse_mode="HTML")

async def receive_emails(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    new = [ln.strip() for ln in text.splitlines() if "@" in ln and "." in ln]
    if not new:
        await update.message.reply_text("⚠️ No valid emails. Try again or /cancel:")
        return ADD_EMAILS
    before = len(emails_list)
    for e in new:
        if e not in emails_list:
            emails_list.append(e)
    save_json_list(EMAILS_FILE, emails_list)
    add_log(f"📧 Added {len(emails_list) - before} emails")
    await update.message.reply_text(
        f"✅ Added <b>{len(emails_list)-before}</b> new emails\n"
        f"📊 Total: <b>{len(emails_list)}</b>",
        parse_mode="HTML", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ─── Add Phones ─────────────────────────────────────────────────────
async def addphones_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await guard(update):
        return ConversationHandler.END
    await _ask_add_phones(update.effective_chat.send_message)
    return ADD_PHONES

async def _ask_add_phones(send):
    await send(
        "📱 <b>ADD PHONE NUMBERS</b>\n\n"
        "Send numbers — one per line, with country code.\n"
        "Example:\n"
        "<code>+919876543210\n+12025550143</code>\n\n"
        "/cancel to abort.",
        parse_mode="HTML")

async def receive_phones(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    new = []
    for ln in text.splitlines():
        ln = ln.strip()
        digits = "".join(ch for ch in ln if ch.isdigit() or ch == "+")
        if len(digits) >= 7:
            new.append(digits)
    if not new:
        await update.message.reply_text("⚠️ No valid numbers. Try again or /cancel:")
        return ADD_PHONES
    before = len(phones_list)
    for p in new:
        if p not in phones_list:
            phones_list.append(p)
    save_json_list(PHONES_FILE, phones_list)
    add_log(f"📱 Added {len(phones_list) - before} phones")
    await update.message.reply_text(
        f"✅ Added <b>{len(phones_list)-before}</b> new numbers\n"
        f"📊 Total: <b>{len(phones_list)}</b>",
        parse_mode="HTML", reply_markup=main_menu_kb())
    return ConversationHandler.END

# ─── View / Clear lists ─────────────────────────────────────────────
async def viewlists_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    def preview(lst, n=10):
        if not lst:
            return "(empty)"
        shown = "\n".join(f"• {x}" for x in lst[:n])
        if len(lst) > n:
            shown += f"\n…and {len(lst)-n} more"
        return shown
    txt = (
        f"📋 <b>CURRENT LISTS</b>\n━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Names ({len(names_list)}):</b>\n{preview(names_list)}\n\n"
        f"📧 <b>Emails ({len(emails_list)}):</b>\n{preview(emails_list)}\n\n"
        f"📱 <b>Phones ({len(phones_list)}):</b>\n{preview(phones_list)}"
    )
    if len(txt) > 4000:
        txt = txt[:3990] + "\n...(truncated)"
    await update.effective_chat.send_message(txt, parse_mode="HTML", reply_markup=main_menu_kb())

async def clearlists_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.effective_chat.send_message(
        "🗑️ Choose what to clear:", parse_mode="HTML", reply_markup=clear_kb())

# ─── Proxy commands ─────────────────────────────────────────────────
async def proxy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    if not PROXY_LIST:
        await update.effective_chat.send_message(
            "📭 No proxies loaded.\nUse /reload to fetch + validate.",
            reply_markup=main_menu_kb())
        return
    sample = PROXY_LIST[:15]
    txt = f"🌐 <b>PROXY POOL</b> — {len(PROXY_LIST)} working | ☠️ {len(DEAD_PROXIES)} evicted\n━━━━━━━━━━━━━━━━━\n\n"
    for p in sample:
        txt += f"🟢 <code>{proxy_key(p)}</code>\n"
    if len(PROXY_LIST) > 15:
        txt += f"\n…and {len(PROXY_LIST)-15} more"
    await update.effective_chat.send_message(txt, parse_mode="HTML", reply_markup=main_menu_kb())

async def reload_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    msg = await update.effective_chat.send_message(
        "🔄 <b>Reloading proxies</b>\n"
        "Real HTTPS validation — takes 30-90s...",
        parse_mode="HTML")
    DEAD_PROXIES.clear()
    try:
        await load_free_proxies_async(MAX_POOL_SIZE)
        await msg.edit_text(
            f"✅ <b>{len(PROXY_LIST)}</b> validated proxies loaded!\n"
            f"All tested via real HTTPS request. Ready to blast. 🚀",
            parse_mode="HTML")
    except Exception as e:
        await msg.edit_text(f"⚠️ Reload error: {type(e).__name__}: {e}", parse_mode="HTML")

# ─── Logs ───────────────────────────────────────────────────────────
async def logs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    txt = f"📊 <b>RECENT LOGS</b>\n\n<code>{get_logs(50)}</code>"
    if len(txt) > 4000:
        txt = txt[:3990] + "\n...(truncated)"
    await update.effective_chat.send_message(txt, parse_mode="HTML", reply_markup=main_menu_kb())

# ─── Stop ───────────────────────────────────────────────────────────
async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    if running_jobs.get(chat_id):
        running_jobs[chat_id] = False
        await update.effective_chat.send_message(
            "⛔ <b>Stop signal sent.</b>\nJob will halt shortly.", parse_mode="HTML")
        add_log(f"⛔ Stop signal for chat {chat_id}")
    else:
        await update.effective_chat.send_message("ℹ️ No active job.")

# ─── SUBMIT FLOW ────────────────────────────────────────────────────
async def submit_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await guard(update):
        return ConversationHandler.END
    if not names_list or not emails_list or not phones_list:
        await update.effective_chat.send_message(
            "⚠️ Need all three lists!\n\n"
            f"Names: {len(names_list)} | Emails: {len(emails_list)} | Phones: {len(phones_list)}\n\n"
            "Add at least 1 of each before submitting.",
            parse_mode="HTML", reply_markup=main_menu_kb())
        return ConversationHandler.END
    if len(PROXY_LIST) < 5:
        await update.effective_chat.send_message(
            "⚠️ Not enough working proxies. Running /reload first...")
        try:
            await load_free_proxies_async(MAX_POOL_SIZE)
        except Exception:
            pass
        if len(PROXY_LIST) < 3:
            await update.effective_chat.send_message(
                "❌ Proxy pool still too small. Try again later.")
            return ConversationHandler.END
    await update.effective_chat.send_message(
        "🚀 <b>SUBMIT FORM — Step 1/2</b>\n\n"
        "📝 Send the message body for the form:\n\n"
        "/cancel to abort.",
        parse_mode="HTML")
    return FORM_MSG

async def receive_form_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message.text.strip()
    if not msg:
        await update.message.reply_text("⚠️ Empty. Try again or /cancel:")
        return FORM_MSG
    ctx.user_data["form_msg"] = msg
    await update.message.reply_text(
        f"✅ Message saved ({len(msg)} chars)\n\n"
        f"🔢 <b>Step 2/2</b> — How many submissions? (1–2000):",
        parse_mode="HTML")
    return FORM_COUNT

async def execute_submit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        count = int(update.message.text.strip())
        if not 1 <= count <= 2000:
            raise ValueError()
    except Exception:
        await update.message.reply_text("⚠️ Enter a number 1–2000, or /cancel:")
        return FORM_COUNT

    msg = ctx.user_data.get("form_msg", "").strip()
    if not msg:
        await update.message.reply_text("⚠️ Message missing. /submit again.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    running_jobs[chat_id] = True

    await update.message.reply_text(
        f"🚀 <b>BLAST STARTING</b>\n━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Target: telegram.org/support\n"
        f"📊 Submissions: <b>{count}</b>\n"
        f"⚡ Concurrency: <b>{CONCURRENT_SUBMITS}x parallel</b>\n"
        f"🌐 Proxy pool: {len(PROXY_LIST)}\n"
        f"🔁 Max retries/submission: {MAX_ATTEMPTS}\n"
        f"👤 Name pool: {len(names_list)}\n"
        f"📧 Email pool: {len(emails_list)}\n"
        f"📱 Phone pool: {len(phones_list)}\n\n"
        f"💡 Send /stop anytime to halt.\n"
        f"━━━━━━━━━━━━━━━━━",
        parse_mode="HTML")

    ok = 0
    fail = 0
    done = 0
    start_ts = datetime.now()
    stats_lock = asyncio.Lock()
    sem = asyncio.Semaphore(CONCURRENT_SUBMITS)

    async def worker(i: int):
        nonlocal ok, fail, done
        if not running_jobs.get(chat_id, False):
            return
        async with sem:
            if not running_jobs.get(chat_id, False):
                return
            name  = random.choice(names_list)
            email = random.choice(emails_list)
            phone = random.choice(phones_list)

            success, status, ip, attempts = await submit_form_with_retries(
                name, email, phone, msg, max_attempts=MAX_ATTEMPTS
            )

            async with stats_lock:
                done += 1
                if success:
                    ok += 1
                    line = (f"✅ <b>{done}/{count}</b> | {status} | tries: {attempts}\n"
                            f"👤 {name} | 📧 <code>{email[:28]}</code>\n"
                            f"📱 <code>{phone}</code> | 🌐 <code>{ip}</code>")
                else:
                    fail += 1
                    line = (f"❌ <b>{done}/{count}</b> | {status}\n"
                            f"👤 {name} | 🌐 <code>{ip}</code>")

                add_log(f"{'✅' if success else '❌'} #{done}: {status} via {ip} (tries={attempts})")

                # Send individual result only every Nth to avoid flood, but always send fails
                if done % BATCH_STATUS_EVERY == 0 or not success or done == count:
                    try:
                        await update.message.reply_text(line, parse_mode="HTML")
                    except Exception:
                        pass

            # Small jitter to look human-ish between waves
            await asyncio.sleep(random.uniform(0.1, 0.4))

    tasks = [asyncio.create_task(worker(i)) for i in range(1, count + 1)]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        add_log(f"⚠️ Blast gather error: {e}")

    running_jobs[chat_id] = False
    elapsed = (datetime.now() - start_ts).seconds
    rate = (ok / (ok + fail) * 100) if (ok + fail) > 0 else 0
    per_sec = ((ok + fail) / elapsed) if elapsed > 0 else (ok + fail)
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━\n"
        f"🎉 <b>BLAST COMPLETE</b>\n\n"
        f"✅ Success: <b>{ok}</b>\n"
        f"❌ Failed: <b>{fail}</b>\n"
        f"📈 Rate: <b>{rate:.1f}%</b>\n"
        f"⏱ Time: <b>{elapsed//60}m {elapsed%60}s</b>\n"
        f"⚡ Speed: <b>{per_sec:.2f}/sec</b>\n\n"
        f"🌐 Remaining proxies: {len(PROXY_LIST)}\n"
        f"☠️ Evicted this run: {len(DEAD_PROXIES)}",
        parse_mode="HTML", reply_markup=main_menu_kb())
    add_log(f"🎉 Blast done: {ok}✅ / {fail}❌")
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════
# 🎛️ CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════════════
async def menu_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id if update.effective_user else 0
    if not is_authorized(uid):
        try:
            await q.edit_message_text("🚫 Access denied.")
        except Exception:
            pass
        await send_denial(update)
        return

    action = q.data.split("|", 1)[1] if "|" in q.data else q.data
    chat = update.effective_chat

    if action == "home":
        try:
            await q.edit_message_text(welcome_text(), parse_mode="HTML", reply_markup=main_menu_kb())
        except Exception:
            await chat.send_message(welcome_text(), parse_mode="HTML", reply_markup=main_menu_kb())
    elif action == "add_names":
        await _ask_add_names(chat.send_message)
    elif action == "add_emails":
        await _ask_add_emails(chat.send_message)
    elif action == "add_phones":
        await _ask_add_phones(chat.send_message)
    elif action == "submit":
        await chat.send_message("👉 Use /submit to start the form-submission flow.")
    elif action == "view":
        await viewlists_cmd(update, ctx)
    elif action == "clear":
        await chat.send_message("🗑️ Choose what to clear:", parse_mode="HTML", reply_markup=clear_kb())
    elif action == "proxy":
        await proxy_cmd(update, ctx)
    elif action == "reload":
        await reload_cmd(update, ctx)
    elif action == "logs":
        await logs_cmd(update, ctx)
    elif action == "help":
        await chat.send_message(
            "📖 Use /help for full command list.",
            parse_mode="HTML", reply_markup=main_menu_kb())
    elif action == "stop":
        await stop_cmd(update, ctx)

async def clear_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id if update.effective_user else 0
    if not is_authorized(uid):
        await send_denial(update)
        return
    what = q.data.split("|", 1)[1]
    global names_list, emails_list, phones_list
    if what == "names":
        names_list = []; save_json_list(NAMES_FILE, names_list); txt = "🗑️ Names cleared."
    elif what == "emails":
        emails_list = []; save_json_list(EMAILS_FILE, emails_list); txt = "🗑️ Emails cleared."
    elif what == "phones":
        phones_list = []; save_json_list(PHONES_FILE, phones_list); txt = "🗑️ Phones cleared."
    elif what == "all":
        names_list = []; emails_list = []; phones_list = []
        save_json_list(NAMES_FILE, names_list)
        save_json_list(EMAILS_FILE, emails_list)
        save_json_list(PHONES_FILE, phones_list)
        txt = "💣 ALL lists cleared."
    else:
        txt = "Unknown."
    add_log(txt)
    try:
        await q.edit_message_text(txt, reply_markup=main_menu_kb())
    except Exception:
        await update.effective_chat.send_message(txt, reply_markup=main_menu_kb())

# ═══════════════════════════════════════════════════════════════════
# 🚀 POST INIT
# ═══════════════════════════════════════════════════════════════════
async def post_init(app):
    add_log(f"⚡ Bot v{BOT_VERSION} starting up...")
    load_all_lists()
    load_sudo()
    add_log(f"🔐 Owner: {OWNER_ID} | Sudo users: {len(sudo_users)}")
    add_log("🌐 Fetching + HTTPS-validating free proxies (this takes a bit)...")
    try:
        await load_free_proxies_async(MAX_POOL_SIZE)
    except Exception as e:
        add_log(f"⚠️ Proxy init error: {type(e).__name__}: {e}")
    add_log(f"✅ Ready! {len(PROXY_LIST)} proxies in pool.")

async def post_shutdown(app):
    add_log("🛑 Shutting down...")

# ═══════════════════════════════════════════════════════════════════
# 🚀 MAIN
# ═══════════════════════════════════════════════════════════════════
def print_banner():
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass
    print(f"{C.CYN}{C.B}")
    print(f"  🚀 TG FORM BLASTER v{BOT_VERSION}")
    print(f"  Target: telegram.org/support")
    print(f"  Owner : {OWNER_ID}")
    print(f"  Contact: @{CONTACT_USERNAME}")
    print(f"  Status: Running...{C.R}\n")

def main():
    print_banner()

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init     = post_init
    app.post_shutdown = post_shutdown

    # Conversation handlers
    names_conv = ConversationHandler(
        entry_points=[CommandHandler("addnames", addnames_cmd)],
        states={ADD_NAMES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_names)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        per_message=False, allow_reentry=True)

    emails_conv = ConversationHandler(
        entry_points=[CommandHandler("addemails", addemails_cmd)],
        states={ADD_EMAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_emails)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        per_message=False, allow_reentry=True)

    phones_conv = ConversationHandler(
        entry_points=[CommandHandler("addnumbers", addphones_cmd)],
        states={ADD_PHONES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phones)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        per_message=False, allow_reentry=True)

    submit_conv = ConversationHandler(
        entry_points=[CommandHandler("submit", submit_cmd)],
        states={
            FORM_MSG:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_form_msg)],
            FORM_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_submit)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd), CommandHandler("stop", stop_cmd)],
        per_message=False, allow_reentry=True)

    gif_conv = ConversationHandler(
        entry_points=[CommandHandler("addgif", addgif_cmd)],
        states={
            WAIT_GIF: [MessageHandler(
                (filters.ANIMATION | filters.VIDEO | filters.PHOTO | filters.Document.ALL | filters.TEXT) & ~filters.COMMAND,
                receive_gif)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        per_message=False, allow_reentry=True)

    # Command handlers
    app.add_handler(CommandHandler("start",       start_cmd))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("viewlists",   viewlists_cmd))
    app.add_handler(CommandHandler("clearlists",  clearlists_cmd))
    app.add_handler(CommandHandler("proxy",       proxy_cmd))
    app.add_handler(CommandHandler("reload",      reload_cmd))
    app.add_handler(CommandHandler("logs",        logs_cmd))
    app.add_handler(CommandHandler("stop",        stop_cmd))
    app.add_handler(CommandHandler("cancel",      cancel_cmd))
    app.add_handler(CommandHandler("sudo",        sudo_cmd))
    app.add_handler(CommandHandler("rmsudo",      rmsudo_cmd))
    app.add_handler(CommandHandler("sudolist",    sudolist_cmd))

    app.add_handler(names_conv)
    app.add_handler(emails_conv)
    app.add_handler(phones_conv)
    app.add_handler(submit_conv)
    app.add_handler(gif_conv)   # /addgif (owner hidden)

    # Callback routers
    app.add_handler(CallbackQueryHandler(menu_router,  pattern=r"^MENU\|"))
    app.add_handler(CallbackQueryHandler(clear_router, pattern=r"^CLR\|"))

    logger.info(f"🚀 TG FORM BLASTER v{BOT_VERSION} — RUNNING")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
