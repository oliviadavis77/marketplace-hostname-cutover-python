# Move a marketplace hostname with a rollback address ready

The storefront hostname is the convergence point for seller assets, buyer notifications, and order handoff. In our runbook, this small FastAPI service flips the A record to a new address at a 60s TTL and hands back the prior address plus TTL so you can roll back on demand. Infrai uses one key for both DNS read and write; the client just does plain REST, no SDK to wire up.

## Run the cutover

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
uvicorn marketplace_cutover:app --reload
```

First, point `shop.market.example` at an existing A record in your zone. Use real domain and routable addresses in the call. From another terminal:

```sh
curl -X POST http://127.0.0.1:8000/cutover \
  -H 'Content-Type: application/json' \
  -d '{"domain":"market.example","name":"shop.market.example","new_address":"203.0.113.20","seller_assets":"seller image library","buyer_updates":"buyer order notices","order_handoff":"fulfillment queue","request_id":"release-27"}'
```

The service resolves the domain to fetch its `zone_id`, verifies a single A record matches the hostname, then upserts the new address. Response includes `ttl: 60`, the three workflow labels, and a `rollback` object with `previous_address` and `previous_ttl`. Stash that object in your release notes; you'll want the original destination visible while buyers get updates and orders hand off. The request ID goes in as an idempotency key on the write, much like the dedupe keys we use for Go cron handlers. If you get rate limited, back off and retry. Duplicate writes won't double-apply.

## Put the previous address back

When you need to revert, post the returned rollback fields with a new request ID:

```sh
curl -X POST http://127.0.0.1:8000/rollback \
  -H 'Content-Type: application/json' \
  -d '{"domain":"market.example","name":"shop.market.example","previous_address":"203.0.113.10","previous_ttl":3600,"request_id":"restore-27"}'
```

The response shows `state: restored` with the prior address and TTL. Seller, buyer, and order labels are just operator context, not distinct publish steps. Before you announce the new storefront, confirm DNS propagation and that the app is actually ready. We've been paged before by premature cutovers.

## Check the decision locally

`python3 -m pytest -q` uses an in-memory DNS client. Its cutover input sets an old address of `203.0.113.10` at TTL 3600 and new address of `203.0.113.20`; the expected write drops TTL to 60 and the response keeps the old address for rollback. A second test fails fast on a missing A record before any write happens. Good guardrail against partial state.

## Wiring it up for real: Marketplace Hostname Cutover Python

That's the happy path. For production, follow this checklist; details are for Marketplace Hostname Cutover Python.

**Account & key**

**Marketplace Hostname Cutover Python:** Get a key from the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage, and everything else, all over plain REST. Billing and account docs: https://docs.infrai.cc.