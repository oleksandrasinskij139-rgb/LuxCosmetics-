"""LuxSync: сервер синхронизации LuxVisuals (Flask).
Косметика, Custom Sword и граффити. Render: gunicorn app:app (ровно 1 worker, много threads).
Состояние хранится в памяти процесса, поэтому worker должен быть один."""
import json, os, re, threading, time
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

TTL = int(os.environ.get("LUX_TTL", "45"))              # сек. онлайн после последнего сигнала
GRAF_LIFETIME = 300                                     # сек. жизни граффити (как в моде)
GRAF_MAX_EVENTS = 2000
MAX_POLL_WAIT = 25
TOKENS_FILE = os.environ.get("LUX_TOKENS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.txt"))
MAX_LOOKUP, MAX_UUIDS_PER_TOKEN, RATE_PER_MIN = 128, 3, 900

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
COSM_RE = re.compile(r"^[A-Za-z0-9_.\- ]{0,64}$")
EQUIP_RE = re.compile(r"^[0-9, ]{0,200}$")
SWORD_RE = re.compile(r'^[^"\\\x00-\x1f]{0,64}$')
WORLD_RE = re.compile(r"^[a-z0-9_.:/\-]{1,100}$")
DIRS = {"DOWN", "UP", "NORTH", "SOUTH", "WEST", "EAST"}

lock = threading.Lock()
graf_cond = threading.Condition(lock)
presence, state, token_uuids, rate = {}, {}, {}, {}
graf_events, graf_seq = [], 0


# Разные адреса одного и того же сервера Minecraft - в одну "комнату" граффити.
# Свои пары можно задать переменной окружения LUX_SERVER_ALIASES="адрес1=основной,адрес2=основной".
SERVER_ALIASES = {"luxmine.gomc.fun": "luxmine.ru", "mc.luxmine.ru": "luxmine.ru", "play.luxmine.ru": "luxmine.ru"}
for _pair in os.environ.get("LUX_SERVER_ALIASES", "").split(","):
    if "=" in _pair:
        _a, _b = _pair.split("=", 1)
        if _a.strip() and _b.strip():
            SERVER_ALIASES[_a.strip().lower()] = _b.strip().lower()


def norm_server(v):
    """Ключ сервера: нижний регистр, без порта по умолчанию и точки в конце, плюс алиасы адресов."""
    v = re.sub(r"[^a-z0-9_.:\-]", "_", str(v).lower())[:128]
    v = re.sub(r":25565$", "", v).rstrip(".")
    return SERVER_ALIASES.get(v, v)


def log(*a):
    print(*a, flush=True)


@app.before_request
def trace():
    if request.path not in ("/api/health", "/api/graffiti/poll", "/api/state", "/api/state/lookup"):
        has = "yes" if request.headers.get("X-Auth-Token") else "NO"
        log(f"req: {request.method} {request.path} token={has}")


def tokens():
    if not os.path.isfile(TOKENS_FILE):
        return None
    with open(TOKENS_FILE, encoding="utf-8") as f:
        found = {l.strip() for l in f if l.strip() and not l.startswith("#")}
    return found or None


REQUIRE_AUTH = os.environ.get("LUX_REQUIRE_AUTH", "0") == "1"   # 1 = строгий режим (только токены из tokens.txt)
ANON = "anon"


def client_ip():
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()


def auth():
    """Токен не обязателен: без токена (или с лишним) запрос идёт как анонимный, чтобы косметика
    отображалась у всех с модом. Строгий режим: переменная окружения LUX_REQUIRE_AUTH=1."""
    t = (request.headers.get("X-Auth-Token") or "").strip()
    allowed = tokens()
    valid = bool(t) and (allowed is None or t in allowed)
    if not valid:
        if REQUIRE_AUTH:
            return None, (jsonify(error="unauthorized"), 401)
        t = ANON
    key = t if t != ANON else ANON + ":" + client_ip()      # лимит запросов: по IP для анонимов
    now = time.time()
    with lock:
        w = rate.get(key)
        if not w or now - w[0] > 60:
            rate[key] = [now, 1]
        else:
            w[1] += 1
            if w[1] > RATE_PER_MIN:
                return None, (jsonify(error="rate_limited"), 429)
    return t, None


def bind_uuid(t, u):
    """Один uuid принадлежит одному токену. Вызывать под lock. Возвращает ошибку или None."""
    if t == ANON:
        return None                      # анонимным игрокам привязка uuid к токену не нужна
    own = token_uuids.setdefault(t, set())
    if u not in own:
        if len(own) >= MAX_UUIDS_PER_TOKEN:
            log(f"bind refused: too_many_accounts uuid={u[:8]}")
            return jsonify(error="too_many_accounts"), 403
        if any(u in s for k, s in token_uuids.items() if k != t):
            log(f"bind refused: uuid_taken uuid={u[:8]}")
            return jsonify(error="uuid_taken"), 403
        own.add(u)
    return None


def gc():
    now = time.time()
    for store in (presence, state):
        for u in [u for u, p in store.items() if now - p["seen"] > TTL]:
            del store[u]


def same_spot(g, srv, world, x, y, z, face):
    return (g["server"] == srv and g["world"] == world and g["x"] == x and g["y"] == y
            and g["z"] == z and g["face"] == face)


def raw_json(obj, status=200):
    """json.dumps без сортировки ключей: клиент читает первый "seq" в теле, он должен идти первым."""
    return Response(json.dumps(obj, separators=(",", ":")), status=status, mimetype="application/json")


VERSION = "luxsync-2026-10-12-noauth"


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/version")
def version():
    """Открыть в браузере: https://luxcosmetics.onrender.com/api/version - видно, что новая версия запущена."""
    with lock:
        gc()
        rooms = {}
        for g in graf_events:
            if g["op"] == "add":
                rooms[g["server"]] = rooms.get(g["server"], 0) + 1
        who = [{"id": u[:8], "equipped": bool(p["equipped"]), "sword": bool(p["sword"]),
                "seen_s_ago": int(time.time() - p["seen"])} for u, p in state.items()]
        return jsonify(version=VERSION, state_players=len(state), cosmetic_players=len(presence),
                       graffiti_events=len(graf_events), graffiti_seq=graf_seq,
                       graffiti_rooms=rooms, players=who)


# ---------- старая косметика (совместимость) ----------
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
        e = bind_uuid(t, u)
        if e: return e
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
    return jsonify(cosmetics=res)


@app.get("/api/cosmetics/online")
def online():
    t, err = auth()
    if err: return err
    with lock:
        gc()
        players = list(set(presence) | set(state))
    return jsonify(count=len(players), players=players)


# ---------- косметика + Custom Sword ----------
@app.put("/api/state")
def put_state():
    t, err = auth()
    if err: return err
    b = request.get_json(silent=True)
    if not isinstance(b, dict): return jsonify(error="bad_body"), 400
    u = str(b.get("playerUuid", "")).lower()
    eq, sw = b.get("equipped", ""), b.get("sword", "")
    eq = "" if eq is None else str(eq)
    sw = "" if sw is None else str(sw)
    if not UUID_RE.match(u) or not EQUIP_RE.match(eq) or not SWORD_RE.match(sw):
        return jsonify(error="bad_fields"), 400
    with lock:
        e = bind_uuid(t, u)
        if e: return e
        prev = state.get(u)
        if prev is None or prev["equipped"] != eq or prev["sword"] != sw:
            log(f"state: {u} equipped={eq!r} sword={sw!r}")
        state[u] = {"equipped": eq, "sword": sw, "seen": time.time()}
    return jsonify(ok=True)


@app.post("/api/state/lookup")
def state_lookup():
    t, err = auth()
    if err: return err
    b = request.get_json(silent=True)
    if not isinstance(b, dict) or not isinstance(b.get("playerUuids"), list):
        return jsonify(error="bad_body"), 400
    now, res = time.time(), {}
    with lock:
        gc()
        for u in b["playerUuids"][:MAX_LOOKUP]:
            u = str(u).lower()
            p = state.get(u)
            if p and (p["equipped"] or p["sword"]) and now - p["seen"] <= TTL:
                res[u] = {"equipped": p["equipped"], "sword": p["sword"]}   # порядок ключей важен для клиента
    return raw_json({"states": res})


# ---------- граффити ----------
@app.post("/api/graffiti")
def graffiti_post():
    global graf_seq
    t, err = auth()
    if err: return err
    b = request.get_json(silent=True)
    if not isinstance(b, dict): return jsonify(error="bad_body"), 400
    u = str(b.get("playerUuid", "")).lower()
    srv = norm_server(b.get("server", ""))
    world = str(b.get("world", ""))
    face, up = str(b.get("face", "")).upper(), str(b.get("up", "")).upper()
    try:
        x, y, z, gid = (int(b[k]) for k in ("x", "y", "z", "gid"))
    except (KeyError, TypeError, ValueError):
        return jsonify(error="bad_fields"), 400
    if (not UUID_RE.match(u) or not WORLD_RE.match(world) or face not in DIRS or up not in DIRS
            or not (-30000000 <= x <= 30000000 and -30000000 <= z <= 30000000 and -2048 <= y <= 2048)
            or not (0 <= gid <= 100000)):
        return jsonify(error="bad_fields"), 400
    with graf_cond:
        e = bind_uuid(t, u)
        if e: return e
        graf_events[:] = [g for g in graf_events if not (g["op"] == "add" and same_spot(g, srv, world, x, y, z, face))]
        graf_seq += 1
        graf_events.append({"seq": graf_seq, "ts": time.time(), "op": "add", "server": srv, "uuid": u, "world": world,
                            "x": x, "y": y, "z": z, "face": face, "up": up, "gid": gid})
        cutoff = time.time() - GRAF_LIFETIME
        while graf_events and (graf_events[0]["ts"] < cutoff or len(graf_events) > GRAF_MAX_EVENTS):
            graf_events.pop(0)
        seq = graf_seq
        graf_cond.notify_all()          # мгновенно будим всех ждущих long-poll
    log(f"graffiti: {u} server={srv!r} gid={gid} seq={seq}")
    return raw_json({"ok": True, "seq": seq})


@app.post("/api/graffiti/delete")
def graffiti_delete():
    global graf_seq
    t, err = auth()
    if err: return err
    b = request.get_json(silent=True)
    if not isinstance(b, dict): return jsonify(error="bad_body"), 400
    u = str(b.get("playerUuid", "")).lower()
    srv = norm_server(b.get("server", ""))
    world, face = str(b.get("world", "")), str(b.get("face", "")).upper()
    try:
        x, y, z = (int(b[k]) for k in ("x", "y", "z"))
    except (KeyError, TypeError, ValueError):
        return jsonify(error="bad_fields"), 400
    if not UUID_RE.match(u) or not WORLD_RE.match(world) or face not in DIRS:
        return jsonify(error="bad_fields"), 400
    with graf_cond:
        e = bind_uuid(t, u)
        if e: return e
        before = len(graf_events)
        graf_events[:] = [g for g in graf_events if not (g["op"] == "add" and same_spot(g, srv, world, x, y, z, face))]
        graf_seq += 1
        graf_events.append({"seq": graf_seq, "ts": time.time(), "op": "del", "server": srv, "uuid": u, "world": world,
                            "x": x, "y": y, "z": z, "face": face, "up": "UP", "gid": 0})
        seq = graf_seq
        graf_cond.notify_all()
    log(f"graffiti delete: {u} server={srv!r} removed={before - len(graf_events) + 1} seq={seq}")
    return raw_json({"ok": True, "seq": seq})


@app.get("/api/graffiti/poll")
def graffiti_poll():
    t, err = auth()
    if err: return err
    srv = norm_server(request.args.get("server", ""))
    try:
        since = int(request.args.get("since", "-1"))
        wait = max(0, min(float(request.args.get("wait", "0")), MAX_POLL_WAIT))
    except ValueError:
        return jsonify(error="bad_args"), 400
    deadline = time.time() + wait

    def collect(since_, snapshot=False):
        now = time.time()
        out = []
        for e in graf_events:
            if (e["server"] == srv and e["seq"] > since_ and now - e["ts"] <= GRAF_LIFETIME
                    and not (snapshot and e["op"] == "del")):
                out.append({"seq": e["seq"], "op": e["op"], "uuid": e["uuid"], "world": e["world"], "x": e["x"], "y": e["y"],
                            "z": e["z"], "face": e["face"], "up": e["up"], "gid": e["gid"],
                            "age_ms": int((now - e["ts"]) * 1000)})
        return out

    with graf_cond:
        if since < 0 or since > graf_seq:
            since, instant = 0, True        # первый запрос (или сервер перезапускался): отдать живые граффити сразу
        else:
            instant = False
        snap_mode = instant
        while True:
            ev = collect(since, snap_mode)
            if ev or instant:
                break
            left = deadline - time.time()
            if left <= 0:
                break
            graf_cond.wait(timeout=left)
        cur = graf_seq
    return raw_json({"seq": cur, "events": ev})   # "seq" строго первым


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), threaded=True)
