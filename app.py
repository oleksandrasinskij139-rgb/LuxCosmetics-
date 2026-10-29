# LuxVisuals SERVER (Render): ключи, проверка для мода, профиль. Бот живёт отдельно и ходит сюда по /bot/key.
import os, re, json, time, secrets, sqlite3, threading
from flask import Flask, request, jsonify

DATA_DIR   = os.environ.get("DATA_DIR", ".")
BOT_SECRET = "Yg484y9j1rvd8bWroXMQgohcJr1CPOCkWtyuQIA1IFc"      # общий пароль бота и сервера (должен совпадать с bot.py)
os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.Lock()
def db():
    c = sqlite3.connect(os.path.join(DATA_DIR, "lux.db"), timeout=10); c.row_factory = sqlite3.Row; return c
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
def get_or_create_user(tg_id, username):
    with _lock, db() as c:
        r = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if r: return r
        while True:
            rnd = "".join(secrets.choice(ALPHA) for _ in range(10))
            try:
                cur = c.execute("INSERT INTO users(tg_id,username,key,created) VALUES(?,?,?,?)", (tg_id, username or "", "tmp" + rnd, int(time.time())))
                num = cur.lastrowid
                c.execute("UPDATE users SET key=? WHERE num=?", (f"LUX-{num:04d}-{rnd[:5]}-{rnd[5:]}", num)); break
            except sqlite3.IntegrityError: continue
        return c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()

def user_by_key(key):
    key = (key or "").strip().upper()
    if not re.fullmatch(r"LUX-\d{4,}-[A-Z0-9]{5}-[A-Z0-9]{5}", key): return None
    with db() as c: return c.execute("SELECT * FROM users WHERE key=?", (key,)).fetchone()

app = Flask(__name__)
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
    return {"owned": sorted(set(int(x) for x in w.get("owned", []))), "redeemed": list(w.get("redeemed", []))}

def state(u):
    w = wallet_of(u)
    return dict(ok=True, num=u["num"], balance=u["balance"], owned=w["owned"], data=json.loads(u["data"] or "{}"))

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
        c.execute("UPDATE users SET balance=balance-?, wallet=? WHERE num=?", (cost, json.dumps(w), u["num"]))
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
        c.execute("UPDATE users SET balance=balance+?, wallet=? WHERE num=?", (REDEEM_CODES[code], json.dumps(w), u["num"]))
        u = c.execute("SELECT * FROM users WHERE num=?", (u["num"],)).fetchone()
    return jsonify(state(u))

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
    return jsonify(ok=True)
