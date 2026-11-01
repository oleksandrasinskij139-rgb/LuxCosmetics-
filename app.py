# LuxVisuals SERVER (Render): ключи, проверка для мода, профиль. Бот живёт отдельно и ходит сюда по /bot/key.
import os, re, json, time, secrets, sqlite3, threading, hmac, hashlib, base64, atexit, tempfile
import requests
from flask import Flask, request, jsonify, Response

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

# Цены в СОТЫХ токена (100 = 1 токен). Мечи и питомцы 30-50, крылья 20-30, плащи 8-20, спина 8-18, шапки 6-15, граффити 1-5 токенов.
PRICES = {85: 3000, 86: 3500, 87: 4000, 88: 4000, 89: 4500, 90: 5000, 1000: 800, 1001: 800, 1002: 1000, 1003: 1000, 1004: 1200, 1005: 1200, 1006: 1500, 1011: 1500, 1015: 2000, 1019: 2000, 1100: 2000, 1101: 2200, 1102: 2200, 1103: 2500, 1106: 2500, 1111: 2800, 1115: 2800, 1119: 3000, 1200: 800, 1201: 1200, 1202: 1000, 1206: 1200, 1211: 1500, 1215: 1500, 1219: 1800, 1300: 3000, 1301: 3000, 1302: 3000, 1303: 4000, 1306: 4000, 1311: 4500, 1315: 5000, 1319: 3500, 1400: 600, 1401: 800, 1402: 800, 1406: 1000, 1411: 1200, 1415: 1200, 1419: 1500, 2000: 100, 2001: 100, 2002: 100, 2003: 100, 2004: 200, 2005: 200, 2006: 200, 2007: 200, 2008: 300, 2009: 300, 2010: 300, 2011: 300, 2012: 400, 2013: 400, 2014: 400, 2015: 400, 2016: 500, 2017: 500, 2018: 500, 2019: 500}
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
    if banned(u): return jsonify(ok=False, error="banned")
    touch_seen(u["num"])
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
# ВСЕ суммы в СОТЫХ токена (100 = 1 токен). Минимальный приз 1 токен, средний ~9.8 токена за прокрутку:
# за 2 суток (2 прокрутки) выходит примерно 20 токенов. Магазин: 66 предметов, 1..50 токенов.
# (приз, вес в %). Значения 500 / 1000 / CASE_JACKPOT подсвечиваются в меню мода (синий / фиолетовый / оранжевый "Куш").
CASE_JACKPOT = 5000
CASE_PRIZES = [(100, 12), (300, 17), (500, 18), (800, 14), (1000, 14), (1500, 11), (2000, 7), (3000, 4), (CASE_JACKPOT, 3)]
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
    return jsonify(ok=True, num=u["num"], username=u["username"] or "", name=site_name_of(u), site_name=u["site_name"] or "",
                   avatar_ts=(u["avatar_ts"] or 0), balance=(u["balance"] or 0) // 100,
                   created=time.strftime("%d.%m.%Y", time.gmtime(u["created"] or 0)))

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


# =====================================================================================
# ---------- САЙТ: профиль (ник + аватар) и общий каталог ресурспаков / конфигов ----------
# Всё хранится в lux.db (она бэкапится в Telegram), поэтому есть жёсткие лимиты размера.
# Картинки сайт сжимает сам (обложка до 640px, аватар 192px), здесь только проверка.
# =====================================================================================
ITEM_LIMITS = {"rp": 8 * 1024 * 1024, "config": 256 * 1024}        # макс. размер файла по разделам
ITEM_EXT    = {"rp": (".zip",), "config": (".json", ".cfg", ".txt", ".zip", ".properties", ".toml")}
IMG_MAX     = 400 * 1024                                            # обложка / аватар (после сжатия на сайте обычно 30-120 КБ)
USER_ITEMS_MAX = 20                                                 # на игрока
STORE_TOTAL_MAX = 35 * 1024 * 1024                                  # всего в базе (лимит файла Telegram для бэкапа - 50 МБ)
NICK_RE = re.compile(r"[A-Za-z0-9_]{3,16}")

# ---------- внешнее хранилище файлов (S3-совместимое: Backblaze B2, Cloudflare R2 и т.п.) ----------
# Если заданы S3_ENDPOINT, S3_KEY_ID, S3_SECRET, S3_BUCKET — обложки и файлы ресурспаков/конфигов лежат там,
# а в lux.db остаются только названия и ссылки. Без этих переменных всё работает по-старому (в базе, лимит 35 МБ).
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "").strip()
S3_KEY_ID   = os.environ.get("S3_KEY_ID", "").strip()
S3_SECRET   = os.environ.get("S3_SECRET", "").strip()
S3_BUCKET   = os.environ.get("S3_BUCKET", "").strip()
S3_REGION   = os.environ.get("S3_REGION", "").strip() or "auto"
try: S3_TOTAL_MAX = int(float(os.environ.get("S3_TOTAL_GB", "9")) * 1024 ** 3)       # потолок, чтобы не вылезти за бесплатные 10 ГБ
except ValueError: S3_TOTAL_MAX = 9 * 1024 ** 3
RP_MAX_S3   = 25 * 1024 * 1024                                                       # размер ресурспака, когда есть внешнее хранилище
_s3 = None
def s3_on(): return bool(S3_ENDPOINT and S3_KEY_ID and S3_SECRET and S3_BUCKET)
def s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config
        _s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT, aws_access_key_id=S3_KEY_ID, aws_secret_access_key=S3_SECRET, region_name=S3_REGION,
                           config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}, connect_timeout=10, read_timeout=60))
    return _s3
def s3_put(key, data, ctype): s3().put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=ctype)
def s3_url(key, fname=None, ttl=600):
    params = {"Bucket": S3_BUCKET, "Key": key}
    if fname: params["ResponseContentDisposition"] = 'attachment; filename="%s"' % fname
    return s3().generate_presigned_url("get_object", Params=params, ExpiresIn=ttl)
def s3_del(*keys):
    for k in keys:
        if not k: continue
        try: s3().delete_object(Bucket=S3_BUCKET, Key=k)
        except Exception as e: print("s3 delete failed", type(e).__name__, flush=True)

# ---------- Dropbox (бесплатно 2 ГБ): DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN ----------
DBX_KEY     = os.environ.get("DROPBOX_APP_KEY", "").strip()
DBX_SECRET  = os.environ.get("DROPBOX_APP_SECRET", "").strip()
DBX_REFRESH = os.environ.get("DROPBOX_REFRESH_TOKEN", "").strip()
_dbx = {"tok": "", "exp": 0}
def dbx_on(): return bool(DBX_KEY and DBX_SECRET and DBX_REFRESH)
def dbx_token():
    if _dbx["tok"] and time.time() < _dbx["exp"] - 60: return _dbx["tok"]
    r = requests.post("https://api.dropboxapi.com/oauth2/token", data={"grant_type": "refresh_token", "refresh_token": DBX_REFRESH}, auth=(DBX_KEY, DBX_SECRET), timeout=20)
    r.raise_for_status(); j = r.json()
    _dbx["tok"], _dbx["exp"] = j["access_token"], time.time() + int(j.get("expires_in", 14400))
    return _dbx["tok"]
def _dbx_hdr(extra=None):
    h = {"Authorization": "Bearer " + dbx_token()}; h.update(extra or {}); return h
def dbx_put(key, data):
    arg = json.dumps({"path": "/" + key, "mode": "overwrite", "mute": True, "autorename": False})   # ensure_ascii: заголовок только ASCII
    r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=_dbx_hdr({"Dropbox-API-Arg": arg, "Content-Type": "application/octet-stream"}), data=data, timeout=120)
    r.raise_for_status()
def dbx_url(key):
    r = requests.post("https://api.dropboxapi.com/2/files/get_temporary_link", headers=_dbx_hdr(), json={"path": "/" + key}, timeout=20)
    r.raise_for_status(); return r.json()["link"]
def dbx_del(key):
    try: requests.post("https://api.dropboxapi.com/2/files/delete_v2", headers=_dbx_hdr(), json={"path": "/" + key}, timeout=20)
    except Exception as e: print("dropbox delete failed", type(e).__name__, flush=True)

# ---------- общий слой: S3 приоритетнее, иначе Dropbox ----------
def ext_on(): return s3_on() or dbx_on()
def ext_put(key, data, ctype):
    if s3_on(): s3_put(key, data, ctype)
    else: dbx_put(key, data)
def ext_url(key, fname=None, ttl=600):
    return s3_url(key, fname, ttl) if s3_on() else dbx_url(key)
def ext_del(*keys):
    if s3_on(): s3_del(*keys)
    elif dbx_on():
        for k in keys:
            if k: dbx_del(k)
EXT_TOTAL_MAX = S3_TOTAL_MAX if s3_on() else (int(float(os.environ.get("DROPBOX_TOTAL_GB", "1.8")) * 1024 ** 3))   # у Dropbox Basic всего 2 ГБ
def item_limit(kind): return RP_MAX_S3 if (kind == "rp" and ext_on()) else ITEM_LIMITS[kind]
app.config["MAX_CONTENT_LENGTH"] = (RP_MAX_S3 + 2 * 1024 * 1024) if ext_on() else 12 * 1024 * 1024

with db() as c:
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    for col, ddl in (("site_name", "TEXT DEFAULT ''"), ("avatar", "BLOB"), ("avatar_type", "TEXT DEFAULT ''"), ("avatar_ts", "INTEGER DEFAULT 0")):
        if col not in cols: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    c.execute("""CREATE TABLE IF NOT EXISTS site_items(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, author_num INTEGER, title TEXT, descr TEXT,
        img BLOB, img_type TEXT, fname TEXT, file BLOB, size INTEGER, dl INTEGER DEFAULT 0, created INTEGER)""")
    _icols = [r[1] for r in c.execute("PRAGMA table_info(site_items)")]
    for _col in ("img_key", "file_key"):
        if _col not in _icols: c.execute(f"ALTER TABLE site_items ADD COLUMN {_col} TEXT")

def site_name_of(u):
    return (u["site_name"] or u["username"] or ("Игрок #%d" % u["num"]))

def img_mime(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n": return "image/png"
    if b[:3] == b"\xff\xd8\xff": return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP": return "image/webp"
    return None

def _read_upload(name, maxsize):
    f = request.files.get(name)
    if not f: return None, None
    data = f.read(maxsize + 1)
    return f, data

@app.errorhandler(413)
def _too_large(e): return jsonify(ok=False, error="Файл слишком большой."), 413

@app.post("/api/site/profile")                 # сайт: сменить ник и/или аватар (multipart: name, avatar)
def site_profile():
    u = session_user()
    if not u: return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    if limited(): return jsonify(ok=False, error="Слишком много запросов."), 429
    name = request.form.get("name"); changed = False
    with _lock, db() as c:
        if name is not None:
            name = name.strip()
            if not NICK_RE.fullmatch(name): return jsonify(ok=False, error="Ник: 3-16 символов, латиница, цифры и _."), 400
            busy = c.execute("SELECT 1 FROM users WHERE num!=? AND (lower(site_name)=lower(?) OR lower(username)=lower(?))", (u["num"], name, name)).fetchone()
            if busy: return jsonify(ok=False, error="Этот ник уже занят."), 409
            c.execute("UPDATE users SET site_name=? WHERE num=?", (name, u["num"])); changed = True
        f, data = _read_upload("avatar", IMG_MAX)
        if f is not None:
            mt = img_mime(data or b"")
            if not data or len(data) > IMG_MAX or not mt: return jsonify(ok=False, error="Аватар: PNG, JPEG или WebP до 400 КБ."), 400
            c.execute("UPDATE users SET avatar=?, avatar_type=?, avatar_ts=? WHERE num=?", (data, mt, int(time.time()), u["num"])); changed = True
        if not changed: return jsonify(ok=False, error="Нечего менять."), 400
        r = c.execute("SELECT * FROM users WHERE num=?", (u["num"],)).fetchone()
    mark_dirty()
    return jsonify(ok=True, name=site_name_of(r), avatar_ts=r["avatar_ts"] or 0)

@app.get("/api/site/avatar/<int:num>")
def site_avatar(num):
    with db() as c: r = c.execute("SELECT avatar, avatar_type FROM users WHERE num=?", (num,)).fetchone()
    if not r or not r["avatar"]: return ("", 404)
    return Response(r["avatar"], mimetype=r["avatar_type"] or "image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

def _item_json(r, me_num):
    return dict(id=r["id"], kind=r["kind"], title=r["title"], desc=r["descr"] or "", size=r["size"], dl=r["dl"] or 0, created=r["created"],
                fname=r["fname"] or "", mine=(me_num is not None and r["author_num"] == me_num),
                author=dict(num=r["author_num"], name=(r["a_site"] or r["a_user"] or ("Игрок #%d" % r["author_num"])), avatar_ts=(r["a_ts"] or 0)))

@app.get("/api/site/items")                    # ?kind=rp|config
def site_items():
    kind = request.args.get("kind", "")
    if kind not in ITEM_LIMITS: return jsonify(ok=False, error="Неизвестный раздел."), 400
    me = session_user(); me_num = me["num"] if me else None
    with db() as c:
        rows = c.execute("""SELECT i.id,i.kind,i.author_num,i.title,i.descr,i.fname,i.size,i.dl,i.created,
                                   u.site_name AS a_site, u.username AS a_user, u.avatar_ts AS a_ts
                            FROM site_items i LEFT JOIN users u ON u.num=i.author_num WHERE i.kind=? ORDER BY i.id DESC LIMIT 200""", (kind,)).fetchall()
    return jsonify(ok=True, items=[_item_json(r, me_num) for r in rows])

@app.get("/api/site/items/<int:iid>/image")
def site_item_image(iid):
    with db() as c: r = c.execute("SELECT img, img_type, img_key FROM site_items WHERE id=?", (iid,)).fetchone()
    if r and r["img_key"] and ext_on():
        try: return Response("", 302, headers={"Location": ext_url(r["img_key"], ttl=3600), "Cache-Control": "private, max-age=600"})
        except Exception as e: print("storage image url failed", type(e).__name__, flush=True); return ("", 502)
    if not r or not r["img"]: return ("", 404)
    return Response(r["img"], mimetype=r["img_type"] or "image/jpeg", headers={"Cache-Control": "public, max-age=604800"})

@app.get("/api/site/items/<int:iid>/file")     # скачивание
def site_item_file(iid):
    with _lock, db() as c:
        r = c.execute("SELECT fname, file, file_key FROM site_items WHERE id=?", (iid,)).fetchone()
        if not r: return jsonify(ok=False, error="Не найдено."), 404
        c.execute("UPDATE site_items SET dl=dl+1 WHERE id=?", (iid,))
    safe = re.sub(r"[^\w.\- ]", "_", r["fname"] or "file")[:80] or "file"
    if r["file_key"] and ext_on():                      # файл лежит во внешнем хранилище: отдаём временную ссылку, трафик идёт мимо Render
        try: return Response("", 302, headers={"Location": ext_url(r["file_key"], safe, 300), "Cache-Control": "no-store"})
        except Exception as e: print("storage file url failed", type(e).__name__, flush=True); return jsonify(ok=False, error="Хранилище недоступно, попробуй позже."), 502
    return Response(r["file"], mimetype="application/octet-stream", headers={"Content-Disposition": 'attachment; filename="%s"' % safe, "Cache-Control": "no-store"})

@app.post("/api/site/items")                   # multipart: kind, title, desc, image, file
def site_item_create():
    u = session_user()
    if not u: return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    if limited(): return jsonify(ok=False, error="Слишком много запросов."), 429
    kind = request.form.get("kind", "")
    if kind not in ITEM_LIMITS: return jsonify(ok=False, error="Неизвестный раздел."), 400
    title = (request.form.get("title") or "").strip()[:40]; desc = (request.form.get("desc") or "").strip()[:200]
    if not title: return jsonify(ok=False, error="Введи название."), 400
    fi, img = _read_upload("image", IMG_MAX)
    mt = img_mime(img or b"")
    if not img or len(img) > IMG_MAX or not mt: return jsonify(ok=False, error="Обложка: PNG, JPEG или WebP до 400 КБ."), 400
    lim = item_limit(kind)
    ff, data = _read_upload("file", lim)
    if not data: return jsonify(ok=False, error="Загрузи файл."), 400
    if len(data) > lim: return jsonify(ok=False, error="Файл больше %d МБ." % max(1, lim // 1048576) if lim >= 1048576 else "Файл больше %d КБ." % (lim // 1024)), 400
    fname = (ff.filename or "file").replace("\\", "/").split("/")[-1][:80]
    if not fname.lower().endswith(ITEM_EXT[kind]): return jsonify(ok=False, error="Допустимые файлы: " + ", ".join(ITEM_EXT[kind])), 400
    if fname.lower().endswith(".zip") and data[:2] != b"PK": return jsonify(ok=False, error="Это не настоящий .zip."), 400
    with _lock, db() as c:
        if c.execute("SELECT COUNT(*) FROM site_items WHERE author_num=?", (u["num"],)).fetchone()[0] >= USER_ITEMS_MAX:
            return jsonify(ok=False, error="Лимит: не больше %d публикаций. Удали старые." % USER_ITEMS_MAX), 400
        if ext_on():
            used = c.execute("SELECT COALESCE(SUM(size),0) FROM site_items WHERE file_key IS NOT NULL").fetchone()[0]
            if used + len(data) + len(img) > EXT_TOTAL_MAX: return jsonify(ok=False, error="Хранилище сайта заполнено."), 507
        else:
            used = c.execute("SELECT COALESCE(SUM(size+LENGTH(img)),0) FROM site_items").fetchone()[0]
            if used + len(data) + len(img) > STORE_TOTAL_MAX: return jsonify(ok=False, error="Хранилище сайта заполнено."), 507
    img_key = file_key = None
    if ext_on():                                        # сначала кладём файлы во внешнее хранилище, потом пишем запись в базу
        tok = secrets.token_hex(16); safe_name = re.sub(r"[^\w.\- ]", "_", fname)[:80] or "file"
        img_key, file_key = "img/%s.%s" % (tok, mt.split("/")[1]), "%s/%s/%s" % (kind, tok, safe_name)    # имя файла в пути = имя при скачивании
        try:
            ext_put(img_key, img, mt); ext_put(file_key, data, "application/octet-stream")
        except Exception as e:
            print("storage upload failed", type(e).__name__, flush=True); ext_del(img_key, file_key)
            return jsonify(ok=False, error="Хранилище недоступно, попробуй позже."), 502
    with _lock, db() as c:
        cur = c.execute("INSERT INTO site_items(kind,author_num,title,descr,img,img_type,fname,file,size,created,img_key,file_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (kind, u["num"], title, desc, b"" if img_key else img, mt, fname, b"" if file_key else data, len(data), int(time.time()), img_key, file_key))
        iid = cur.lastrowid
    mark_dirty()
    return jsonify(ok=True, id=iid)

@app.delete("/api/site/items/<int:iid>")       # автор или админ
def site_item_delete(iid):
    u = session_user(); adm = admin_session() if not u else None
    if not u and not adm: return jsonify(ok=False, error="Сессия истекла. Войди снова."), 401
    with db() as c:
        r = c.execute("SELECT author_num, img_key, file_key FROM site_items WHERE id=?", (iid,)).fetchone()
        if not r: return jsonify(ok=False, error="Не найдено."), 404
        if u and r["author_num"] != u["num"]: return jsonify(ok=False, error="Это не твоя публикация."), 403
        c.execute("DELETE FROM site_items WHERE id=?", (iid,))
    if ext_on(): ext_del(r["img_key"], r["file_key"])
    if adm: alog(adm["a"], "item_delete", r["author_num"], iid)
    mark_dirty()
    return jsonify(ok=True)


# =====================================================================================
# ---------- АДМИН-ПАНЕЛЬ (/admins/ на сайте) ----------
# Переменная окружения ADMIN_PASSWORD обязательна (без неё вход в панель закрыт).
# Токены игроков и UUID/tg_id в ответы админ-API не попадают никогда.
# Мод раз в ~1 сек. дёргает /api/commands/poll: забирает команды и сразу получает актуальный баланс.
# =====================================================================================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_SECRET = SESSION_SECRET + b":admin"
ADMIN_TTL = 8 * 3600
ONLINE_WINDOW = 15                                 # сек: онлайн, если мод опрашивал сервер недавно
CMD_TTL = 120                                      # команда живёт 2 минуты, потом протухает

with db() as c:
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
    for col, ddl in (("last_seen", "INTEGER DEFAULT 0"), ("play_secs", "INTEGER DEFAULT 0"), ("fps", "INTEGER DEFAULT 0"),
                     ("banned_until", "INTEGER DEFAULT 0"), ("flags", "TEXT DEFAULT ''"), ("note", "TEXT DEFAULT ''")):
        if col not in cols: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    c.execute("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, invite_hash TEXT UNIQUE, created INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS commands(id INTEGER PRIMARY KEY AUTOINCREMENT, num INTEGER, action TEXT, value TEXT, created INTEGER, done INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS admin_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, who TEXT, action TEXT, num INTEGER, value TEXT)")

def banned(u):
    try: return (u["banned_until"] or 0) > time.time()
    except Exception: return False

def touch_seen(num, fps=None):
    """Отметка «в сети» + учёт времени игры (без mark_dirty, чтобы не слать бэкап каждую секунду)."""
    try:
        now = int(time.time())
        with db() as c:
            r = c.execute("SELECT last_seen FROM users WHERE num=?", (num,)).fetchone()
            if not r: return
            gap = now - (r["last_seen"] or 0)
            add = gap if 0 < gap <= 5 else 0
            if fps is not None and 5 <= fps <= 1000:
                c.execute("UPDATE users SET last_seen=?, play_secs=play_secs+?, fps=? WHERE num=?", (now, add, fps, num))
            else:
                c.execute("UPDATE users SET last_seen=?, play_secs=play_secs+? WHERE num=?", (now, add, num))
    except Exception: pass

def make_admin_session(role, name):
    body = _b64(json.dumps({"r": role, "a": name, "e": int(time.time()) + ADMIN_TTL}).encode())
    return body + "." + hmac.new(ADMIN_SECRET, body.encode(), hashlib.sha256).hexdigest()
def admin_session():
    h = request.headers.get("Authorization", "")
    if not h.startswith("Bearer "): return None
    try:
        body, sig = h[7:].strip().split(".", 1)
        if not hmac.compare_digest(sig, hmac.new(ADMIN_SECRET, body.encode(), hashlib.sha256).hexdigest()): return None
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return d if d["e"] >= time.time() and d.get("r") in ("full", "limited") else None
    except Exception: return None
def need_admin(full=False):
    d = admin_session()
    if not d: return None, (jsonify(ok=False, error="Сессия истекла. Войди снова."), 401)
    if full and d["r"] != "full": return None, (jsonify(ok=False, error="Недостаточно прав."), 403)
    return d, None
def alog(who, action, num=None, value=None):
    with db() as c: c.execute("INSERT INTO admin_log(ts,who,action,num,value) VALUES(?,?,?,?,?)", (int(time.time()), who, action, num, str(value)[:200] if value is not None else None))

_adm_hits = {}
def admin_login_limited():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip(); now = time.time()
    _adm_hits[ip] = [t for t in _adm_hits.get(ip, []) if now - t < 300] + [now]
    return len(_adm_hits[ip]) > 8

@app.post("/api/admin/login")
def admin_login():
    if admin_login_limited(): return jsonify(ok=False, error="Слишком много попыток. Подожди 5 минут."), 429
    j = request.get_json(silent=True) or {}
    pw, inv = j.get("password"), j.get("invite")
    if isinstance(pw, str) and pw:
        if not ADMIN_PASSWORD or not hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
            return jsonify(ok=False, error="Неверный пароль."), 401
        alog("owner", "login")
        return jsonify(ok=True, session_token=make_admin_session("full", "owner"), role="full")
    if isinstance(inv, str) and inv:
        h = hashlib.sha256(inv.strip().encode()).hexdigest()
        with db() as c: r = c.execute("SELECT * FROM admins WHERE invite_hash=?", (h,)).fetchone()
        if not r: return jsonify(ok=False, error="Ссылка недействительна."), 401
        alog(r["name"], "login")
        return jsonify(ok=True, session_token=make_admin_session("limited", r["name"]), role="limited")
    return jsonify(ok=False, error="Введи пароль."), 400

@app.get("/api/admin/players")
def admin_players():
    d, err = need_admin()
    if err: return err
    now = int(time.time()); out = []
    with db() as c: rows = c.execute("SELECT * FROM users ORDER BY num").fetchall()
    for r in rows:
        try: owned = len(json.loads(r["wallet"] or "{}").get("owned", []))
        except Exception: owned = 0
        name = r["username"] or ("Игрок #%d" % r["num"])
        out.append(dict(id=r["num"], name=name, skin=r["username"] or "Steve", online=(now - (r["last_seen"] or 0)) < ONLINE_WINDOW,
                        mins=(r["play_secs"] or 0) // 60, first=time.strftime("%d.%m.%Y", time.gmtime(r["created"] or 0)),
                        last_seen=r["last_seen"] or 0, fps=r["fps"] or 0, balance=r["balance"] // 100, owned=owned,
                        flags=[x for x in (r["flags"] or "").split(",") if x], note=r["note"] or "",
                        banned_until=r["banned_until"] if (r["banned_until"] or 0) > now else 0))
    return jsonify(ok=True, players=out)

PLAYER_CMDS = {"close", "fps", "key", "jump", "chat", "third", "inventory", "menu", "message", "freeze", "title"}
FLAGS = {"cheater", "toxic", "spam", "watch"}

def _queue(c, nums, act, val):
    now = int(time.time())
    c.executemany("INSERT INTO commands(num,action,value,created) VALUES(?,?,?,?)", [(n, act, None if val is None else str(val), now) for n in nums])

def _check_cmd(act, val):
    if act == "fps" and not (isinstance(val, int) and not isinstance(val, bool) and 5 <= val <= 1000): return "FPS: от 5 до 1000."
    if act == "key" and not (isinstance(val, str) and 1 <= len(val) <= 12): return "Неверная клавиша."
    if act in ("message", "chat") and not (isinstance(val, str) and 1 <= len(val.strip()) <= 200): return "Сообщение: до 200 символов."
    if act == "freeze" and not (isinstance(val, int) and not isinstance(val, bool) and 1 <= val <= 300): return "Заморозка: 1-300 секунд."
    return None

@app.post("/api/admin/players/<int:num>/action")
def admin_player_action(num):
    j = request.get_json(silent=True) or {}; act = j.get("action"); val = j.get("value")
    d, err = need_admin(full=(act in ("tokens", "ban", "note", "flags")))
    if err: return err
    with _lock, db() as c:
        u = c.execute("SELECT * FROM users WHERE num=?", (num,)).fetchone()
        if not u: return jsonify(ok=False, error="Игрок не найден."), 404
        bal = None
        if act == "tokens":                                        # + пополнить, − списать (минус)
            if not isinstance(val, int) or isinstance(val, bool) or val == 0 or abs(val) > 100000: return jsonify(ok=False, error="Токены: от -100000 до 100000, не 0."), 400
            c.execute("UPDATE users SET balance=MAX(0, balance+?) WHERE num=?", (val * 100, num)); mark_dirty()
            bal = c.execute("SELECT balance FROM users WHERE num=?", (num,)).fetchone()["balance"] // 100
        elif act == "ban":                                         # val = минуты, 0 = снять бан
            if not isinstance(val, int) or isinstance(val, bool) or not 0 <= val <= 525600: return jsonify(ok=False, error="Минуты: 0..525600."), 400
            c.execute("UPDATE users SET banned_until=? WHERE num=?", (int(time.time()) + val * 60 if val else 0, num)); mark_dirty()
            if val: _queue(c, [num], "close", None)
        elif act == "note":
            if not isinstance(val, str) or len(val) > 500: return jsonify(ok=False, error="Заметка до 500 символов."), 400
            c.execute("UPDATE users SET note=? WHERE num=?", (val.strip(), num)); mark_dirty()
        elif act == "flags":
            if not isinstance(val, list) or not all(isinstance(x, str) and x in FLAGS for x in val): return jsonify(ok=False, error="Неверные флаги."), 400
            c.execute("UPDATE users SET flags=? WHERE num=?", (",".join(sorted(set(val))), num)); mark_dirty()
        elif act in PLAYER_CMDS:
            if (time.time() - (u["last_seen"] or 0)) >= ONLINE_WINDOW: return jsonify(ok=False, error="Игрок не в сети."), 409
            e = _check_cmd(act, val)
            if e: return jsonify(ok=False, error=e), 400
            _queue(c, [num], act, val)
        else: return jsonify(ok=False, error="Неизвестное действие."), 400
    alog(d["a"], act, num, val)
    return jsonify(ok=True, balance=bal)

@app.post("/api/admin/mass")                                      # массовые действия: только полный админ
def admin_mass():
    d, err = need_admin(full=True)
    if err: return err
    j = request.get_json(silent=True) or {}; act = j.get("action"); val = j.get("value")
    if act not in ("message", "close", "freeze"): return jsonify(ok=False, error="Неизвестное действие."), 400
    e = _check_cmd(act, val)
    if e: return jsonify(ok=False, error=e), 400
    with db() as c:
        nums = [r["num"] for r in c.execute("SELECT num FROM users WHERE last_seen>?", (int(time.time()) - ONLINE_WINDOW,))]
        _queue(c, nums, act, val)
    alog(d["a"], "mass_" + act, None, val)
    return jsonify(ok=True, sent=len(nums))

@app.get("/api/admin/admins")
def admin_list():
    d, err = need_admin(full=True)
    if err: return err
    with db() as c: rows = c.execute("SELECT id,name,created FROM admins ORDER BY id").fetchall()
    return jsonify(ok=True, admins=[dict(id=r["id"], name=r["name"]) for r in rows])

@app.post("/api/admin/admins")
def admin_create():
    d, err = need_admin(full=True)
    if err: return err
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()[:32]
    if not name: return jsonify(ok=False, error="Укажи имя."), 400
    invite = secrets.token_urlsafe(24)
    with db() as c: c.execute("INSERT INTO admins(name,invite_hash,created) VALUES(?,?,?)", (name, hashlib.sha256(invite.encode()).hexdigest(), int(time.time())))
    alog(d["a"], "admin_create", None, name)
    return jsonify(ok=True, invite=invite)

@app.delete("/api/admin/admins/<int:aid>")
def admin_delete(aid):
    d, err = need_admin(full=True)
    if err: return err
    with db() as c: c.execute("DELETE FROM admins WHERE id=?", (aid,))
    alog(d["a"], "admin_delete", None, aid)
    return jsonify(ok=True)

@app.get("/api/admin/log")
def admin_log_get():
    d, err = need_admin(full=True)
    if err: return err
    with db() as c: rows = c.execute("SELECT ts,who,action,num,value FROM admin_log ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify(ok=True, log=[dict(ts=r["ts"], who=r["who"], action=r["action"], num=r["num"], value=r["value"]) for r in rows])

@app.post("/api/commands/poll")                    # мод: раз в ~1 сек. Отдаёт команды и актуальный баланс/покупки
def commands_poll():
    ip_ok = True
    j = request.get_json(silent=True) or {}
    u = user_by_key(j.get("key"))
    if not u: return jsonify(ok=False, error="invalid")
    if banned(u): return jsonify(ok=False, error="banned")
    fps = j.get("fps") if isinstance(j.get("fps"), int) and not isinstance(j.get("fps"), bool) else None
    touch_seen(u["num"], fps)
    with _lock, db() as c:
        rows = c.execute("SELECT id,action,value FROM commands WHERE num=? AND done=0 AND created>? ORDER BY id", (u["num"], int(time.time()) - CMD_TTL)).fetchall()
        if rows: c.execute("UPDATE commands SET done=1 WHERE num=? AND done=0", (u["num"],))
        fresh = c.execute("SELECT balance, wallet FROM users WHERE num=?", (u["num"],)).fetchone()
    w = wallet_of(fresh)
    return jsonify(ok=True, balance=fresh["balance"], owned=w["owned"], commands=[dict(action=r["action"], value=r["value"]) for r in rows])


# =====================================================================================
# ---------- Необязательный самопинг против сна Render (KEEP_AWAKE=1) ----------
# Не заменяет внешний мониторинг (UptimeRobot/cron-job.org каждые 5-10 минут) —
# тот надёжнее, т.к. бьёт по адресу снаружи, а не изнутри того же процесса.
# =====================================================================================
if os.environ.get("KEEP_AWAKE") == "1":
    def _keep_awake():
        import urllib.request
        url = os.environ.get("RENDER_EXTERNAL_URL", "")
        while True:
            time.sleep(600)
            if not url: continue
            try: urllib.request.urlopen(url + "/", timeout=10)
            except Exception: pass
    threading.Thread(target=_keep_awake, daemon=True).start()
