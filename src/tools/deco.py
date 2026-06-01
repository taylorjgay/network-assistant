import base64
import hashlib
import json
import os
import time
from urllib.parse import urlencode

import httpx
from Crypto.Cipher import AES
from Crypto.Cipher import PKCS1_v1_5 as PKCS1_Cipher
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad


class DecoClient:
    """
    Client for the TP-Link Deco X55 local web UI API.
    Uses a 3-step RSA+AES auth flow (same UI style as ER605).
    Entry point is the primary Deco node (wired to ER605).
    """

    def __init__(self, host: str, password: str):
        self.host = host
        self.password = password
        self._stok: str | None = None
        self._aes_key: bytes | None = None
        self._aes_iv: bytes | None = None
        self._hash: str | None = None       # MD5("admin" + password), reused for all request signs
        self._key2_mod: str | None = None   # RSA key2 modulus, used to sign all requests
        self._seq: int | None = None        # Base seq from form=auth, constant across all requests
        # Device expects application/json Content-Type (confirmed from browser HAR)
        # Steps 1+2 send JSON body; step 3 sends URL-encoded sign+data with this same header
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": f"https://{host}",
            "Referer": f"https://{host}/webpages/index.html",
        }

    def _aes_encrypt(self, plaintext: str) -> str:
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_iv)
        return base64.b64encode(
            cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
        ).decode("ascii")

    def _aes_decrypt(self, ciphertext_b64: str) -> str:
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_iv)
        return unpad(
            cipher.decrypt(base64.b64decode(ciphertext_b64)), AES.block_size
        ).decode("utf-8")

    def _sign(self, enc_body: str, include_aes_key: bool = False) -> str:
        """
        Compute RSA-PKCS1v15 signature for a request body.
        Login (first) request: sign includes AES key — "k=<key>&i=<iv>&h=<hash>&s=<seq+len>"
        All subsequent requests: sign omits AES key — "h=<hash>&s=<seq+len>"
        The seq never changes after login; only the data length varies per request.
        """
        s_val = self._seq + len(enc_body)
        if include_aes_key:
            aes_key_str = self._aes_key.decode("ascii")
            aes_iv_str = self._aes_iv.decode("ascii")
            sig_str = f"k={aes_key_str}&i={aes_iv_str}&h={self._hash}&s={s_val}"
        else:
            sig_str = f"h={self._hash}&s={s_val}"
        n2 = int(self._key2_mod, 16)
        cipher = PKCS1_Cipher.new(RSA.construct((n2, 65537)))
        return "".join(
            cipher.encrypt(sig_str[i : i + 53].encode("utf-8")).hex()
            for i in range(0, len(sig_str), 53)
        )

    def _authenticate(self, client: httpx.Client) -> bool:
        base = f"https://{self.host}/cgi-bin/luci/;stok=/login"

        # Steps 1+2: send as JSON body (browser sends {"operation":"read"} with application/json)
        json_read = json.dumps({"operation": "read"}).encode()

        # Step 1: RSA key1 (1024-bit) for password encryption
        r1 = client.post(f"{base}?form=keys", content=json_read, headers=self._headers)
        d1 = r1.json()
        if d1.get("error_code") != 0:
            return False
        key1_mod = d1["result"]["password"][0]

        # Step 2: RSA key2 (512-bit) + seq for session signature
        r2 = client.post(f"{base}?form=auth", content=json_read, headers=self._headers)
        d2 = r2.json()
        if d2.get("error_code") != 0:
            return False
        self._key2_mod = d2["result"]["key"][0]
        self._seq = d2["result"]["seq"]

        # AES session key: 16 ASCII hex chars (matches JS timestamp+random pattern)
        ts_hex = "%016x" % int(time.time() * 1000)
        rnd_hex = os.urandom(8).hex()
        aes_key_str = (ts_hex + rnd_hex)[:16]
        aes_iv_str = (rnd_hex + ts_hex)[:16]
        self._aes_key = aes_key_str.encode("ascii")
        self._aes_iv = aes_iv_str.encode("ascii")

        # Encrypt password with key1 (standard PKCS#1 v1.5 — NOT the ER605 nopadding variant)
        n1 = int(key1_mod, 16)
        enc_pwd_hex = PKCS1_Cipher.new(RSA.construct((n1, 65537))).encrypt(
            self.password.encode("utf-8")
        ).hex()

        # Hash = MD5("admin" + password) — confirmed from device JS setHash("admin", e)
        self._hash = hashlib.md5(("admin" + self.password).encode("utf-8")).hexdigest()

        # AES-CBC-PKCS7 encrypt the login body — password is nested under "params" (confirmed from HAR)
        body_json = json.dumps({"params": {"password": enc_pwd_hex}, "operation": "login"})
        enc_body = self._aes_encrypt(body_json)

        # Login sign includes AES key so the server can decrypt subsequent requests
        sign_hex = self._sign(enc_body, include_aes_key=True)

        # Step 3: Login — URL-encode sign+data (browser sends form body with JSON Content-Type)
        r3 = client.post(
            f"{base}?form=login",
            content=urlencode({"sign": sign_hex, "data": enc_body}).encode(),
            headers=self._headers,
        )
        raw = r3.json()

        if "data" not in raw:
            return False
        try:
            result = json.loads(self._aes_decrypt(raw["data"]))
            if result.get("error_code") == 0:
                self._stok = result["result"]["stok"]
                return True
        except Exception:
            pass
        return False

    def _request(self, resource: str, form: str, client: httpx.Client) -> dict:
        if not self._stok:
            if not self._authenticate(client):
                raise Exception(
                    "Deco authentication failed — check deco.host and deco.password in config.json"
                )
        # All post-login requests use the same sign+data encrypted format as login
        enc_body = self._aes_encrypt(json.dumps({"operation": "read"}))
        sign = self._sign(enc_body, include_aes_key=False)
        url = f"https://{self.host}/cgi-bin/luci/;stok={self._stok}/admin/{resource}?form={form}"
        resp = client.post(
            url,
            content=urlencode({"sign": sign, "data": enc_body}).encode(),
            headers=self._headers,
        )
        try:
            raw = resp.json()
        except Exception:
            # Deco sends raw AES-encrypted body on 500 errors (not wrapped in JSON)
            try:
                error_msg = self._aes_decrypt(resp.text.strip())
            except Exception:
                error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            raise Exception(f"Deco returned error: {error_msg}")
        if "data" in raw:
            return json.loads(self._aes_decrypt(raw["data"]))
        return raw

    def get_connected_clients(self) -> dict:
        """Get all clients connected to the mesh with their Deco node assignment."""
        try:
            with httpx.Client(verify=False, timeout=15) as client:
                data = self._request("client", "client_list", client)
                clients_raw = data.get("result", {}).get("client_list", [])
                clients = [
                    {
                        "hostname": c.get("name", c.get("mac", "unknown")),
                        "mac": c.get("mac"),
                        "ip": c.get("ip"),
                        "deco_node_mac": c.get("belong_to"),
                        "connection": c.get("type"),
                        "band": c.get("wire_type"),
                    }
                    for c in clients_raw
                ]
                return {"success": True, "clients": clients, "count": len(clients)}
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "suggestion": "Check deco.host and deco.password in config.json",
                "attempted": f"https://{self.host}/cgi-bin/luci/;stok=.../admin/client?form=client_list",
            }

    def get_mesh_health(self) -> dict:
        """Get status of all Deco nodes including backhaul type and signal strength."""
        try:
            with httpx.Client(verify=False, timeout=15) as client:
                data = self._request("device", "device_list", client)
                nodes_raw = data.get("result", {}).get("device_list", [])
                nodes = [
                    {
                        "mac": n.get("mac"),
                        "ip": n.get("device_ip"),
                        "status": n.get("inet_status"),
                        "is_primary": n.get("master", False),
                        "backhaul": n.get("connection_type"),
                        "signal_level_dbm": n.get("signal_level", {}).get("band5_0"),
                    }
                    for n in nodes_raw
                ]
                return {"success": True, "nodes": nodes, "node_count": len(nodes)}
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "suggestion": "Check deco.host and deco.password in config.json",
                "attempted": f"https://{self.host}/cgi-bin/luci/;stok=.../admin/device?form=device_list",
            }
