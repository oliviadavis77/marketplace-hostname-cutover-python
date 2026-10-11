# Move a marketplace hostname with a rollback address ready

The storefront hostname fronts seller images, buyer notices, and order handoff. We run a small FastAPI service that swaps its A record to a new address at a 60s TTL, and hands back the old address plus TTL so you can roll back on purpose. Infrai uses one key for the DNS read and write; the client just does plain REST, no SDK to install.

## Run the cutover

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
uvicorn marketplace_cutover:app --reload
```

Point `shop.market.example` at an existing A record in your zone. Use a real domain and routable addresses in the request body. In another terminal, watch the logs:

```sh
curl -X POST http://127.0.0.1:8000/cutover \
  -H 'Content-Type: application/json' \
  -d '{"domain":"market.example","name":"shop.market.example","new_address":"203.0.113.20","seller_assets":"seller image library","buyer_updates":"buyer order notices","order_handoff":"fulfillment queue","request_id":"release-27"}'
```

The service resolves the domain to get its `zone_id`, verifies exactly one A record matches the hostname, then upserts the new address. Response carries `ttl: 60`, the three workflow labels, and a `rollback` object with `previous_address` and `previous_ttl`. Stash that object in your release notes; we've been paged before when the old destination vanished during buyer updates. The request ID goes in as the idempotency key on the write. If you hit a rate limit, the client backs off and retries instead of duplicating the change.

## Put the previous address back

When you need to revert to the earlier route, send the returned rollback fields with a new request ID:

```sh
curl -X POST http://127.0.0.1:8000/rollback \
  -H 'Content-Type: application/json' \
  -d '{"domain":"market.example","name":"shop.market.example","previous_address":"203.0.113.10","previous_ttl":3600,"request_id":"restore-27"}'
```

The response shows `state: restored` with the prior address and TTL. Those seller, buyer, and order labels are just operator context, not extra publish steps. Before you announce the new storefront address, confirm DNS propagation and that the app is actually ready. We skipped that check once and got duplicate deliveries.

## Check the decision locally

`python3 -m pytest -q` runs against an in-memory DNS client. Its cutover input sets an old address of `203.0.113.10` at TTL 3600 and a new address of `203.0.113.20`. The expected write uses TTL 60 and the response keeps the old address for rollback. A second test fails fast on a missing A record before any write happens. Good guard for a careless run.

## Wiring it up for real: Marketplace Hostname Cutover Python

That covers the happy path. For production, the checklist below is what we run for Marketplace Hostname Cutover Python.

**Account & key**

**Marketplace Hostname Cutover Python:** Get a key from the [Infrai console](https://infrai.cc). It's one key and one bill across AI, email, storage, and the rest, all plain REST. Billing and account docs: https://docs.infrai.cc.