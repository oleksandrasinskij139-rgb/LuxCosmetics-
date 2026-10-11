"""LuxSync: сервер синхронизации косметики LuxVisuals (Flask).
Работает на PythonAnywhere (WSGI) и на Render (gunicorn app:app)."""
import os, re, threading, time
from flask import Flask, request, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

TTL = int(os.environ.get("LUX_TTL", "45"))          # сек. онлайн после последнего сигнала
TOKENS_FILE = os.environ.get("LUX_TOKENS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.txt"))
MAX_LOOKUP, MAX_UUIDS_PER_TOKEN, RATE_PER_MIN = 128, 3, 240

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
COSM_RE = re.compile(r"^[A-Za-z0-9_.\- ]{0,64}$")

lock = threading.Lock()
presence, token_uuids, rate = {}, {}, {}


def log(*a):
    print(*a, flush=True)


def tokens():
    if not os.path.isfile(TOKENS_FILE):
        return None            # нет файла - принимается любой токен
    with open(TOKENS_FILE, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


def auth():
    t = (request.headers.get("X-Auth-Token") or "").strip()
    allowed = tokens()
    if not t or (allowed is not None and t not in allowed):
        return None, (jsonify(error="unauthorized"), 401)
    now = time.time()
    with lock:
        w = rate.get(t)
        if not w or now - w[0] > 60:
            rate[t] = [now, 1]
        else:
            w[1] += 1
            if w[1] > RATE_PER_MIN:
                return None, (jsonify(error="rate_limited"), 429)
    return t, None


def gc():
    now = time.time()
    for u in [u for u, p in presence.items() if now - p["seen"] > TTL]:
        del presence[u]


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.put("/api/cosmetics/presence")
def put_presence():
    t, err = auth()
    if err: return err
    b = request.get_json(silent=True)
    if not isinstance(b, dict): return jsonify(error="bad_body"), 400
    u = str(b.get("playerUuid", "")).lower()
    c = b.get("cosmeticId") or ""
    if not UUID_RE.match(u) or not isinstance(c, str) or not COSM_RE.match(c):
        return jsonify(error="bad_fields"), 400
    with lock:
        own = token_uuids.setdefault(t, set())
        if u not in own:
            if len(own) >= MAX_UUIDS_PER_TOKEN: return jsonify(error="too_many_accounts"), 403
            if any(u in s for k, s in token_uuids.items() if k != t): return jsonify(error="uuid_taken"), 403
            own.add(u)
        prev = presence.get(u)
        if prev is None or prev["cosmetic"] != c:
            log(f"presence: {u} cosmetic={c!r}")
        presence[u] = {"cosmetic": c, "seen": time.time()}
    return jsonify(ok=True)


@app.post("/api/cosmetics/lookup")
def lookup():
    t, err = auth()
    if err: return err
    b = request.get_json(silent=True)
    if not isinstance(b, dict) or not isinstance(b.get("playerUuids"), list):
        return jsonify(error="bad_body"), 400
    now, res = time.time(), {}
    with lock:
        gc()
        for u in b["playerUuids"][:MAX_LOOKUP]:
            p = presence.get(str(u).lower())
            if p and p["cosmetic"] and now - p["seen"] <= TTL:
                res[str(u).lower()] = p["cosmetic"]
    if res:
        log(f"lookup: asked={len(b['playerUuids'])} found={len(res)}")
    return jsonify(cosmetics=res)


@app.get("/api/cosmetics/online")
def online():
    t, err = auth()
    if err: return err
    with lock:
        gc()
        players = list(presence)
    return jsonify(count=len(players), players=players)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
