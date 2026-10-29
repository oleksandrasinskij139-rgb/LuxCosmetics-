# LuxVisuals SERVER (Render): ключи, проверка для мода, профиль. Бот живёт отдельно и ходит сюда по /bot/key.
import os, re, json, time, secrets, sqlite3, threading
from flask import Flask, request, jsonify

DATA_DIR   = os.environ.get("DATA_DIR", ".")
BOT_SECRET = os.environ.get("BOT_SECRET", "Yg484y9j1rvd8bWroXMQgohcJr1CPOCkWtyuQIA1IFc")      # общий пароль между ботом и сервером
os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.Lock()
def db():
    c = sqlite3.connect(os.path.join(DATA_DIR, "lux.db"), timeout=10); c.row_factory = sqlite3.Row; return c
with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS users(num INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER UNIQUE, username TEXT,
        key TEXT UNIQUE, created INTEGER, balance INTEGER DEFAULT 0, data TEXT DEFAULT \"{}\")""")

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

@app.post("/api/verify")                   # вызывает мод
def verify():
    if limited(): return jsonify(ok=False, error="rate"), 429
    u = user_by_key((request.get_json(silent=True) or {}).get("key"))
    if not u: return jsonify(ok=False, error="invalid")
    return jsonify(ok=True, num=u["num"], balance=u["balance"])

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
