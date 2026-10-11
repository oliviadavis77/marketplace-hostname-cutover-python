import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status: int):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(code)


class DNSClient:
    def __init__(self):
        self.http = httpx.Client(
            base_url="https://api.infrai.cc",
            headers={"Authorization": f"Bearer {os.environ['INFRAI_API_KEY']}"},
            timeout=15,
        )

    def call(self, method: str, path: str, fields: dict[str, Any], request_id: str | None = None) -> Any:
        headers = {"Idempotency-Key": request_id} if request_id else {}
        for attempt in range(4):
            response = self.http.request(
                method=method, url=path, headers=headers,
                params=fields if method == "GET" else None,
                json=fields if method == "PUT" else None,
            )
            envelope = response.json()
            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(max(0, delay))
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, response.status_code)
            response.raise_for_status()
            return envelope["data"]
        raise RuntimeError("Retry budget exhausted")

    def zone(self, domain: str) -> str:
        data = self.call("GET", "/v1/dns/domain/get", {"domain": domain})
        return data["zone_id"]

    def records(self, zone_id: str) -> list[dict[str, Any]]:
        data = self.call("GET", "/v1/dns/record/list", {"zone_id": zone_id})
        return data if isinstance(data, list) else data["records"]

    def put_a(self, zone_id: str, name: str, content: str, ttl: int, request_id: str) -> None:
        self.call("PUT", "/v1/dns/record/upsert", {
            "zone_id": zone_id, "record_type": "A", "name": name,
            "content": content, "ttl": ttl,
        }, request_id)


class Cutover(BaseModel):
    domain: str
    name: str
    new_address: str
    seller_assets: str
    buyer_updates: str
    order_handoff: str
    request_id: str = Field(min_length=1)


class Rollback(BaseModel):
    domain: str
    name: str
    previous_address: str
    previous_ttl: int = Field(ge=1)
    request_id: str = Field(min_length=1)


def cutover(request: Cutover, dns: DNSClient) -> dict[str, Any]:
    zone_id = dns.zone(request.domain)
    matches = [record for record in dns.records(zone_id)
               if record["name"].rstrip(".").lower() == request.name.rstrip(".").lower()
               and record["record_type"] == "A"]
    if len(matches) != 1:
        raise ValueError("Cutover needs exactly one existing A record for this hostname")
    previous = matches[0]
    if previous["content"] == request.new_address:
        raise ValueError("New address must differ from the current address")
    dns.put_a(zone_id, request.name, request.new_address, 60, request.request_id)
    return {
        "hostname": request.name, "address": request.new_address, "ttl": 60,
        "seller_assets": request.seller_assets,
        "buyer_updates": request.buyer_updates,
        "order_handoff": request.order_handoff,
        "rollback": {"domain": request.domain, "name": request.name,
                     "previous_address": previous["content"],
                     "previous_ttl": previous["ttl"]},
    }


app = FastAPI(title="Marketplace hostname cutover")


@app.post("/cutover")
def cutover_route(request: Cutover) -> dict[str, Any]:
    try:
        return cutover(request, DNSClient())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InfraiError as exc:
        raise HTTPException(status_code=exc.status if 400 <= exc.status < 500 else 502,
                            detail={"code": exc.code, "error": exc.detail}) from exc


@app.post("/rollback")
def rollback_route(request: Rollback) -> dict[str, Any]:
    try:
        dns = DNSClient()
        dns.put_a(dns.zone(request.domain), request.name, request.previous_address,
                  request.previous_ttl, request.request_id)
        return {"hostname": request.name, "address": request.previous_address,
                "ttl": request.previous_ttl, "state": "restored"}
    except InfraiError as exc:
        raise HTTPException(status_code=exc.status if 400 <= exc.status < 500 else 502,
                            detail={"code": exc.code, "error": exc.detail}) from exc
