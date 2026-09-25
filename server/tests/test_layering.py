from outfit_core.capabilities import TryOnSpec
from outfit_core.layering import plan_steps
from outfit_core.types import Slot, TryOnOptions


def cats(steps):
    return [[g.category.value for g in s] for s in steps]


def test_top_and_bottom_in_one_call(garment):
    top, pants = garment("top"), garment("bottom")
    steps, skipped = plan_steps([top, pants], TryOnSpec(max_garments_per_call=2), TryOnOptions())
    assert cats(steps) == [["bottom", "top"]] and skipped == []


def test_single_garment_engine_orders_by_tuck(garment):
    top, skirt = garment("top"), garment("skirt")
    spec = TryOnSpec(max_garments_per_call=1)
    assert cats(plan_steps([top, skirt], spec, TryOnOptions(tuck="out"))[0]) == [["skirt"], ["top"]]
    assert cats(plan_steps([top, skirt], spec, TryOnOptions(tuck="in"))[0]) == [["top"], ["skirt"]]


def test_outer_layer_after_base(garment):
    steps, _ = plan_steps([garment("outer"), garment("top"), garment("bottom")],
                          TryOnSpec(max_garments_per_call=2), TryOnOptions())
    assert cats(steps) == [["bottom", "top"], ["outer"]]


def test_outer_alone_acts_as_top(garment):
    steps, skipped = plan_steps([garment("outer"), garment("bottom")], TryOnSpec(max_garments_per_call=2), TryOnOptions())
    assert cats(steps) == [["bottom", "outer"]] and skipped == []


def test_dress_wins_over_top_and_bottom(garment):
    dress, top, pants = garment("dress"), garment("top"), garment("bottom")
    steps, skipped = plan_steps([top, dress, pants], TryOnSpec(), TryOnOptions())
    assert cats(steps) == [["dress"]]
    assert set(skipped) == {top.id, pants.id}


def test_unsupported_and_duplicate_items_skipped(garment):
    shoes, top1, top2 = garment("shoes"), garment("top", "t1"), garment("top", "t2")
    steps, skipped = plan_steps([shoes, top1, top2], TryOnSpec(), TryOnOptions())
    assert cats(steps) == [["top"]]
    assert set(skipped) == {shoes.id, top2.id}


def test_engine_slot_limits_and_no_layering(garment):
    pants, top, coat = garment("bottom"), garment("top"), garment("outer")
    spec = TryOnSpec(slots={Slot.upper}, supports_layering=False)
    steps, skipped = plan_steps([pants, top, coat], spec, TryOnOptions())
    assert cats(steps) == [["top"]]
    assert set(skipped) == {pants.id, coat.id}
