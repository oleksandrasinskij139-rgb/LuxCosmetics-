# LuxVisuals SERVER (Render): ключи, проверка для мода, профиль. Бот живёт отдельно и ходит сюда по /bot/key.
import os, re, json, time, secrets, sqlite3, threading, hmac, hashlib, base64, atexit, tempfile
import requests
from flask import Flask, request, jsonify

DATA_DIR   = os.environ.get("DATA_DIR", ".")
BOT_SECRET = "Yg484y9j1rvd8bWroXMQgohcJr1CPOCkWtyuQIA1IFc"      # общий пароль бота и сервера (должен совпадать с bot.py)
os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.RLock()   # RLock: get_or_create_user() вызывается под этим же замком (раньше был deadlock)
DB_PATH = os.path.join(DATA_DIR, "lux.db")

# ---------- сохранность базы: Render Free стирает диск при засыпании ----------
# Если заданы BACKUP_BOT_TOKEN и BACKUP_CHAT_ID (твой Telegram ID, ты должен нажать /start у бота),
# сервер сам присылает lux.db в этот чат (и закрепляет), а при старте с пустой базой скачивает её обратно.
BK_TOKEN = os.environ.get("BACKUP_BOT_TOKEN", "").strip()
BK_CHAT  = os.environ.get("BACKUP_CHAT_ID", "").strip()
_bk_dirty = threading.Event(); _bk_last_msg = None
def _bk(method, **kw):
    try:
        r = requests.post(f"https://api.telegram.org/bot{BK_TOKEN}/{method}", timeout=40, **kw).json()
        return r if r.get("ok") else None
    except Exception as e:
        print("backup tg error", method, type(e).__name__, flush=True); return None
def backup_restore():
    """Пустая/отсутствующая база -> тянем последнюю копию из закреплённого сообщения."""
    global _bk_last_msg
    if not (BK_TOKEN and BK_CHAT): return
    try:
        if os.path.exists(DB_PATH):
            try:
                c0 = sqlite3.connect(DB_PATH); n = c0.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c0.close()
                if n > 0: return
            except Exception: pass
        chat = _bk("getChat", json={"chat_id": BK_CHAT}); pin = ((chat or {}).get("result") or {}).get("pinned_message") or {}
        doc = pin.get("document")
        if not doc: print("backup: закреплённой копии нет", flush=True); return
        _bk_last_msg = pin.get("message_id")
        f = _bk("getFile", json={"file_id": doc["file_id"]})
        if not f: return
        data = requests.get(f"https://api.telegram.org/file/bot{BK_TOKEN}/{f['result']['file_path']}", timeout=60).content
        if data[:15] != b"SQLite format 3": print("backup: файл не sqlite", flush=True); return
        tmp = DB_PATH + ".restore"; open(tmp, "wb").write(data); os.replace(tmp, DB_PATH)
        print("backup: база восстановлена из Telegram,", len(data), "байт", flush=True)
    except Exception as e: print("backup restore failed", type(e).__name__, flush=True)
def backup_now():
    global _bk_last_msg
    if not (BK_TOKEN and BK_CHAT): return
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".db"); os.close(fd)
        src = sqlite3.connect(DB_PATH, timeout=10); dst = sqlite3.connect(tmp)
        with dst: src.backup(dst)
        src.close(); dst.close()
        with open(tmp, "rb") as fh:
            r = _bk("sendDocument", data={"chat_id": BK_CHAT, "disable_notification": "true", "caption": "lux.db backup " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())},
                    files={"document": ("lux.db", fh)})
        if not r: _bk_dirty.set(); return
        mid = r["result"]["message_id"]
        _bk("pinChatMessage", json={"chat_id": BK_CHAT, "message_id": mid, "disable_notification": True})
        if _bk_last_msg and _bk_last_msg != mid: _bk("deleteMessage", json={"chat_id": BK_CHAT, "message_id": _bk_last_msg})
        _bk_last_msg = mid
    except Exception as e: print("backup failed", type(e).__name__, flush=True); _bk_dirty.set()
    finally:
        if tmp and os.path.exists(tmp): os.remove(tmp)
def _bk_loop():
    while True:
        _bk_dirty.wait(); time.sleep(30); _bk_dirty.clear(); backup_now()   # не чаще раза в ~30 сек
def mark_dirty(): _bk_dirty.set()
backup_restore()
if BK_TOKEN and BK_CHAT:
    threading.Thread(target=_bk_loop, daemon=True).start(); atexit.register(backup_now)
def db():
    c = sqlite3.connect(DB_PATH, timeout=10); c.row_factory = sqlite3.Row; return c
with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS users(num INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER UNIQUE, username TEXT,
        key TEXT UNIQUE, created INTEGER, balance INTEGER DEFAULT 1000, data TEXT DEFAULT \"{}\")""")

PRICES = {85: 300, 86: 300, 87: 300, 88: 300, 89: 300, 90: 300, 1000: 150, 1001: 150, 1002: 150, 1003: 150, 1004: 150, 1005: 150, 1006: 150, 1011: 150, 1015: 150, 1019: 150, 1100: 250, 1101: 250, 1102: 250, 1103: 250, 1106: 250, 1111: 250, 1115: 250, 1119: 250, 1200: 100, 1201: 100, 1202: 100, 1206: 100, 1211: 100, 1215: 100, 1219: 100, 1300: 200, 1301: 200, 1302: 200, 1303: 200, 1306: 200, 1311: 200, 1315: 200, 1319: 200, 1400: 100, 1401: 100, 1402: 100, 1406: 100, 1411: 100, 1415: 100, 1419: 100, 2000: 50, 2001: 50, 2002: 50, 2003: 50, 2004: 50, 2005: 50, 2006: 50, 2007: 50, 2008: 50, 2009: 50, 2010: 50, 2011: 50, 2012: 50, 2013: 50, 2014: 50, 2015: 50, 2016: 50, 2017: 50, 2018: 50, 2019: 50}
START_BALANCE = 1000
REDEEM_CODES = {"MONIX0000": 1000}   # код -> награда, один раз на аккаунт

with db() as c:
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    if "wallet" not in cols: c.execute("ALTER TABLE users ADD COLUMN wallet TEXT DEFAULT '{}'")   # {"owned":[ids],"redeemed":[codes]}

ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
KEY_SECRET = (os.environ.get("KEY_SECRET") or BOT_SECRET).encode()

def _mac(tg_id):                           # подпись зависит только от Telegram ID, поэтому токен переживает сон/перезапуск Render
    h = hmac.new(KEY_SECRET, b"luxkey:" + str(tg_id).encode(), hashlib.sha256).digest()
    return "".join(ALPHA[b % 32] for b in h[:10])
def make_key(tg_id):
    m = _mac(tg_id); return f"LUX-{tg_id}-{m[:5]}-{m[5:]}"

def get_or_create_user(tg_id, username):
    key = make_key(tg_id)
    with _lock, db() as c:
        r = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if r:
            if r["key"] != key: c.execute("UPDATE users SET key=? WHERE tg_id=?", (key, tg_id))
            return c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        c.execute("INSERT INTO users(tg_id,username,key,created) VALUES(?,?,?,?)", (tg_id, username or "", key, int(time.time())))
        mark_dirty()
        return c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()

def user_by_key(key):
    key = (key or "").strip().upper()
    m = re.fullmatch(r"LUX-(\d{4,})-([A-Z0-9]{5})-([A-Z0-9]{5})", key)
    if not m: return None
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE key=?", (key,)).fetchone()   # старые ключи
    if r: return r
    tg_id = int(m.group(1))
    if not hmac.compare_digest(_mac(tg_id), m.group(2) + m.group(3)): return None
    return get_or_create_user(tg_id, "")   # база могла стереться — аккаунт создаётся заново по тому же токену

app = Flask(__name__)

# ---------- сайт: CORS (авторизация через заголовок Authorization, не cookie, поэтому "*" безопасен) ----------
SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "*")          # можно сузить до адреса сайта, например https://luxvisualsss.site.je
@app.before_request
def _preflight():
    if request.method == "OPTIONS": return ("", 204)
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = SITE_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp
@app.get("/")
def health(): return "LuxVisuals server OK"

@app.post("/bot/key")                      # вызывает только бот
def bot_key():
    if not BOT_SECRET or request.headers.get("X-Bot-Secret") != BOT_SECRET: return jsonify(ok=False, error="forbidden"), 403
    j = request.get_json(silent=True) or {}
    if not isinstance(j.get("tg_id"), int): return jsonify(ok=False, error="bad"), 400
    u = get_or_create_user(j["tg_id"], j.get("username"))
    return jsonify(ok=True, key=u["key"], num=u["num"])

_hits = {}
def limited():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip(); now = time.time()
    _hits[ip] = [t for t in _hits.get(ip, []) if now - t < 60] + [now]
    return len(_hits[ip]) > 40

def wallet_of(u):
    try: w = json.loads(u["wallet"] or "{}")
    except Exception: w = {}
    return {"owned": sorted(set(int(x) for x in w.get("owned", []))), "redeemed": list(w.get("redeemed", [])),
            "case_next": int(w.get("case_next", 0) or 0), "case_last": w.get("case_last")}

def state(u):
    w = wallet_of(u)
    return dict(ok=True, num=u["num"], balance=u["balance"], owned=w["owned"], data=json.loads(u["data"] or "{}"),
                case=dict(next_at=w["case_next"], server_ms=int(time.time() * 1000), last=w["case_last"]))

@app.post("/api/verify")                   # вызывает мод: проверка токена + вся учётка (баланс, купленное, косметика, граффити)
def verify():
    if limited(): return jsonify(ok=False, error="rate"), 429
    u = user_by_key((request.get_json(silent=True) or {}).get("key"))
    if not u: return jsonify(ok=False, error="invalid")
    return jsonify(state(u))

@app.post("/api/purchase")                 # покупка за хеллоуинские токены: цены знает только сервер
def purchase():
    if limited(): return jsonify(ok=False, error="rate"), 429
    j = request.get_json(silent=True) or {}
    ids = j.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 100 or not all(isinstance(i, int) for i in ids): return jsonify(ok=False, error="bad")
    with _lock, db() as c:
        u = user_by_key(j.get("key"))
        if not u: return jsonify(ok=False, error="invalid")
        w = wallet_of(u); owned = set(w["owned"])
        want = [i for i in dict.fromkeys(ids) if i in PRICES and i not in owned]
        if not any(i in PRICES for i in ids): return jsonify(ok=False, error="not_for_sale")
        cost = sum(PRICES[i] for i in want)
        if u["balance"] < cost: return jsonify(ok=False, error="no_money")
        w["owned"] = sorted(owned | set(want))
        c.execute("UPDATE users SET balance=balance-?, wallet=? WHERE num=?", (cost, json.dumps(w), u["num"])); mark_dirty()
        u = c.execute("SELECT * FROM users WHERE num=?", (u["num"],)).fetchone()
    return jsonify(state(u))

@app.post("/api/redeem")                   # /LuxLogin <код>: награда один раз на аккаунт
def redeem():
    if limited(): return jsonify(ok=False, error="rate"), 429
    j = request.get_json(silent=True) or {}
    code = str(j.get("code", "")).strip().upper()
    with _lock, db() as c:
        u = user_by_key(j.get("key"))
        if not u: return jsonify(ok=False, error="invalid")
        if code not in REDEEM_CODES: return jsonify(ok=False, error="bad_code")
        w = wallet_of(u)
        if code in w["redeemed"]: return jsonify(ok=False, error="used")
        w["redeemed"].append(code)
        c.execute("UPDATE users SET balance=balance+?, wallet=? WHERE num=?", (REDEEM_CODES[code], json.dumps(w), u["num"])); mark_dirty()
        u = c.execute("SELECT * FROM users WHERE num=?", (u["num"],)).fetchone()
    return jsonify(state(u))

# ---------- кейс: раз в сутки (таймер 24ч с момента прокрутки) ----------
# ВСЕ суммы в СОТЫХ токена (100 = 1 токен), как цены магазина (50..300) и баланс (старт 1000 = 10 токенов).
# Магазин: 66 предметов, от 0.5 до 3 токенов, всего 93 токена. Среднее за прокрутку ~1.1 токена:
# самый дешёвый предмет (0.5) — почти каждый день, предмет за 3 токена — за 2-3 дня, весь магазин — за пару месяцев.
# (приз, вес в %). Значения 500 / 1000 / CASE_JACKPOT подсвечиваются в меню мода (синий / фиолетовый / оранжевый "Куш").
CASE_JACKPOT = 3000
CASE_PRIZES = [(0, 10), (25, 22), (50, 25), (100, 20), (150, 11), (250, 7), (500, 3.5), (1000, 1.2), (CASE_JACKPOT, 0.3)]
CASE_COOLDOWN_MS = 24 * 3600 * 1000
@app.post("/api/case/spin")
def case_spin():
    if limited(): return jsonify(ok=False, error="rate"), 429
    j = request.get_json(silent=True) or {}
    with _lock, db() as c:
        u = user_by_key(j.get("key"))
        if not u: return jsonify(ok=False, error="invalid")
        w = wallet_of(u); now = int(time.time() * 1000)
        if now < w["case_next"]:
            return jsonify(ok=False, error="cooldown", case=dict(next_at=w["case_next"], server_ms=now, last=w["case_last"]))
        prize = secrets.SystemRandom().choices([p for p, _ in CASE_PRIZES], weights=[x for _, x in CASE_PRIZES])[0]
        w["case_next"] = now + CASE_COOLDOWN_MS; w["case_last"] = prize
        c.execute("UPDATE users SET balance=balance+?, wallet=? WHERE num=?", (prize, json.dumps(w), u["num"]))
        u = c.execute("SELECT * FROM users WHERE num=?", (u["num"],)).fetchone()
    mark_dirty()
    r = state(u); r["prize"] = prize
    return jsonify(r)

@app.get("/api/profile")
def profile_get():
    if limited(): return jsonify(ok=False), 429
    u = user_by_key(request.args.get("key"))
    if not u: return jsonify(ok=False, error="invalid")
    return jsonify(ok=True, num=u["num"], balance=u["balance"], data=json.loads(u["data"] or "{}"))

@app.post("/api/profile")                  # косметика / граффити игрока
def profile_set():
    if limited(): return jsonify(ok=False), 429
    j = request.get_json(silent=True) or {}; u = user_by_key(j.get("key"))
    if not u or not isinstance(j.get("data"), dict): return jsonify(ok=False, error="invalid")
    raw = json.dumps(j["data"], ensure_ascii=False)
    if len(raw) > 100_000: return jsonify(ok=False, error="too_big")
    with db() as c: c.execute("UPDATE users SET data=? WHERE num=?", (raw, u["num"]))
    mark_dirty()
    return jsonify(ok=True)


# ---------- сайт: вход по токену, сессия, заглушки граффити (этап 1) ----------
SESSION_SECRET = (os.environ.get("SESSION_SECRET") or BOT_SECRET).encode()
SESSION_TTL = 24 * 3600
def _b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def make_session(num):
    body = _b64(json.dumps({"n": num, "e": int(time.time()) + SESSION_TTL}).encode())
    return body + "." + hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
def session_user():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "): return None
    try:
        body, sig = h[7:].strip().split(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()): return None
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if d["e"] < time.time(): return None
        with db() as c: return c.execute("SELECT * FROM users WHERE num=?", (int(d["n"]),)).fetchone()
    except Exception: return None

_login_hits = {}
def login_limited():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip(); now = time.time()
    _login_hits[ip] = [t for t in _login_hits.get(ip, []) if now - t < 60] + [now]
    return len(_login_hits[ip]) > 10

@app.post("/api/site/login")               # сайт: токен -> короткая сессия
def site_login():
    if login_limited(): return jsonify(ok=False, error="Слишком много попыток. Попробуй через минуту."), 429
    u = user_by_key((request.get_json(silent=True) or {}).get("key"))
    if not u: return jsonify(ok=False, error="Токен не найден. Проверь, что скопировал его целиком."), 401
    return jsonify(ok=True, session_token=make_session(u["num"]), num=u["num"], expires_in=SESSION_TTL)

@app.get("/api/site/me")
def site_me():
    u = session_user()
    if not u: return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    return jsonify(ok=True, num=u["num"], username=u["username"] or "")

GRAFFITI_LIMIT = 12
@app.get("/api/graffiti/mine")             # заглушка до этапа 2 (хранилище картинок)
def graffiti_mine():
    if not session_user(): return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    return jsonify(ok=True, graffiti=[], limit=GRAFFITI_LIMIT)

@app.post("/api/graffiti/upload")          # заглушка до этапа 2
def graffiti_upload():
    if not session_user(): return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    return jsonify(ok=False, error="Загрузка картинок появится на следующем этапе."), 501

@app.delete("/api/graffiti/<gid>")         # заглушка до этапа 2
def graffiti_delete(gid):
    if not session_user(): return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    return jsonify(ok=False, error="Граффити не найдено."), 404
