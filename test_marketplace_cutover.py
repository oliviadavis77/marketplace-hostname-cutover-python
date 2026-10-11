import pytest

from marketplace_cutover import Cutover, cutover


class FakeDNS:
    def __init__(self, records):
        self.saved = []
        self.existing = records

    def zone(self, domain):
        assert domain == "market.example"
        return "zone-42"

    def records(self, zone_id):
        assert zone_id == "zone-42"
        return self.existing

    def put_a(self, *args):
        self.saved.append(args)


def request():
    return Cutover(domain="market.example", name="shop.market.example",
                   new_address="203.0.113.20", seller_assets="seller image library",
                   buyer_updates="buyer order notices", order_handoff="fulfillment queue",
                   request_id="release-27")


def test_cutover_keeps_previous_address_for_rollback():
    dns = FakeDNS([{"name": "shop.market.example", "record_type": "A",
                    "content": "203.0.113.10", "ttl": 3600}])
    result = cutover(request(), dns)
    assert dns.saved == [("zone-42", "shop.market.example", "203.0.113.20", 60, "release-27")]
    assert result["rollback"]["previous_address"] == "203.0.113.10"
    assert result["rollback"]["previous_ttl"] == 3600
    assert result["order_handoff"] == "fulfillment queue"


def test_cutover_refuses_ambiguous_records():
    dns = FakeDNS([])
    with pytest.raises(ValueError, match="exactly one"):
        cutover(request(), dns)
    assert dns.saved == []
