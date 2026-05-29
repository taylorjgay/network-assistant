import base64
import hashlib
import json
import os

import httpx
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad


class DecoClient:
    """
    Client for the TP-Link Deco local API.
    Uses RSA key exchange + AES-CBC for all communication.
    Entry point is the primary Deco node (wired to ER605).
    """

    def __init__(self, host: str, password: str):
        self.host = host
        self.password = password
        self._base = f"http://{host}/cgi-bin/luci/;stok=/ds"
        self._stok = None
        self._aes_key = None
        self._aes_iv = None

    def _md5(self, s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest()

    def _aes_encrypt(self, plaintext: str) -> str:
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_iv)
        encrypted = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
        return base64.b64encode(encrypted).decode()

    def _aes_decrypt(self, ciphertext: str) -> str:
        data = base64.b64decode(ciphertext)
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._aes_iv)
        return unpad(cipher.decrypt(data), AES.block_size).decode()

    def _get_encryption_params(self, client: httpx.Client) -> tuple[int, int, str]:
        """Phase 1: get RSA public key from device, return (rsa_key_n, rsa_key_e, seq)."""
        payload = {"params": {"operation": "read"}}
        resp = client.post(self._base, json={"method": "do", "login": payload})
        data = resp.json()
        # Response contains RSA public key components for encrypting our AES key
        keys = data.get("result", {})
        n = int(keys.get("key", {}).get("n", "0"), 16)
        e = int(keys.get("key", {}).get("e", "0"), 16)
        seq = keys.get("seq", "0")
        return n, e, seq

    def _authenticate(self, client: httpx.Client) -> bool:
        """Full auth flow: RSA key exchange then login with AES-encrypted credentials."""
        # Generate AES session key
        self._aes_key = os.urandom(16)
        self._aes_iv = os.urandom(16)

        # Get device RSA public key
        try:
            n, e, seq = self._get_encryption_params(client)
            if n == 0:
                # Simpler auth fallback for some firmware versions
                resp = client.post(self._base, json={
                    "method": "do",
                    "login": {"password": self._md5(self.password)}
                })
                data = resp.json()
                if data.get("error_code") == 0:
                    self._stok = data.get("stok", "")
                    return True
                return False

            rsa_key = RSA.construct((n, e))
            cipher_rsa = PKCS1_OAEP.new(rsa_key)
            encrypted_aes = base64.b64encode(
                cipher_rsa.encrypt(self._aes_key + self._aes_iv)
            ).decode()
        except Exception as e:
            self._last_auth_error = f"RSA key exchange failed: {e}"
            return False

        # Send encrypted login
        login_body = json.dumps({"method": "do", "login": {
            "password": self._md5(self.password)
        }})
        encrypted_body = self._aes_encrypt(login_body)
        resp = client.post(self._base, json={"params": encrypted_body, "sign": encrypted_aes, "seq": seq})
        try:
            raw = resp.json()
            decrypted = self._aes_decrypt(raw.get("result", ""))
            data = json.loads(decrypted)
            if data.get("error_code") == 0:
                self._stok = data.get("stok", "")
                return True
        except Exception as e:
            self._last_auth_error = f"Login response decryption failed: {e}"
        return False

    def _authenticated_request(self, payload: dict) -> dict:
        """Send an encrypted authenticated request and return decrypted response."""
        with httpx.Client(timeout=15) as client:
            if not self._stok:
                if not self._authenticate(client):
                    detail = getattr(self, "_last_auth_error", "")
                    raise Exception(
                        f"Deco authentication failed{f' ({detail})' if detail else ''} "
                        "— check deco.password in config.json"
                    )

            url = f"http://{self.host}/cgi-bin/luci/;stok={self._stok}/ds"
            if self._aes_key:
                body = json.dumps(payload)
                encrypted = self._aes_encrypt(body)
                resp = client.post(url, json={"params": encrypted})
                raw = resp.json()
                decrypted = self._aes_decrypt(raw.get("result", ""))
                return json.loads(decrypted)
            else:
                resp = client.post(url, json=payload)
                return resp.json()

    def get_connected_clients(self) -> dict:
        """Get all clients connected to the mesh with their Deco node assignment."""
        try:
            data = self._authenticated_request({
                "method": "get",
                "client_list": {"name": ["client_list"]}
            })
            clients_raw = data.get("result", {}).get("client_list", [])
            clients = [{
                "hostname": c.get("name", c.get("mac", "unknown")),
                "mac": c.get("mac"),
                "ip": c.get("ip"),
                "deco_node_mac": c.get("belong_to"),
                "connection": c.get("type"),
                "band": c.get("wire_type"),
            } for c in clients_raw]
            return {"success": True, "clients": clients, "count": len(clients)}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "suggestion": "Check deco.host and deco.password in config.json"}

    def get_mesh_health(self) -> dict:
        """Get status of all Deco nodes including backhaul type and signal strength."""
        try:
            data = self._authenticated_request({
                "method": "get",
                "device_list": {"name": ["device_list"]}
            })
            nodes_raw = data.get("result", {}).get("device_list", [])
            nodes = [{
                "mac": n.get("mac"),
                "ip": n.get("device_ip"),
                "status": n.get("inet_status"),
                "is_primary": n.get("master", False),
                "backhaul": n.get("connection_type"),
                "signal_level_dbm": n.get("signal_level", {}).get("band5_0"),
            } for n in nodes_raw]
            return {"success": True, "nodes": nodes, "node_count": len(nodes)}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "suggestion": "Check deco.host and deco.password in config.json"}
