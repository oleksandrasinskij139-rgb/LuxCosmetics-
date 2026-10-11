from fastapi import FastAPI, Header
from pydantic import BaseModel
from typing import List, Dict, Optional
import time

app = FastAPI(title="LuxVisuals Cosmetics Backend")

# uuid -> данные
presence_store: Dict[str, dict] = {}
TTL = 120  # секунд

class PresenceBody(BaseModel):
    playerUuid: str
    cosmeticId: str = ""

class LookupBody(BaseModel):
    playerUuids: List[str]

def cleanup():
    now = time.time()
    dead = [uid for uid, data in presence_store.items() if now - data["last_seen"] > TTL]
    for uid in dead:
        del presence_store[uid]

@app.put("/api/cosmetics/presence")
async def presence(
    body: PresenceBody,
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    x_hwid: Optional[str] = Header(None, alias="X-Hwid"),
):
    cleanup()
    uid = body.playerUuid.lower()
    presence_store[uid] = {
        "cosmeticId": body.cosmeticId or "",
        "last_seen": time.time(),
        "token": x_auth_token or "",
        "hwid": x_hwid or "",
    }
    return {"ok": True}

@app.post("/api/cosmetics/lookup")
async def lookup(
    body: LookupBody,
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    x_hwid: Optional[str] = Header(None, alias="X-Hwid"),
):
    cleanup()
    result = {}
    for uid in body.playerUuids:
        key = uid.lower()
        if key in presence_store:
            cid = presence_store[key]["cosmeticId"]
            if cid:
                result[uid] = cid
    return {"cosmetics": result}

@app.get("/")
@app.get("/api/health")
async def health():
    cleanup()
    return {"status": "ok", "online_players": len(presence_store)}
