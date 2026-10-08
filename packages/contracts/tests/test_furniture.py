"""Street furniture contract: validation of flights, items and seating."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from amap_contracts.furniture import (
    Edge,
    FurnitureCollection,
    Item,
    ItemKind,
    Stairs,
    Terrace,
)


def _stairs(**kw: object) -> Stairs:
    data = {"id": "s1", "foot": (0.0, 0.0), "top": (0.0, 4.0), "width_m": 3.0,
            "steps": 12, "rise_m": 1.8, **kw}  # fmt: skip
    return Stairs.model_validate(data)


def test_stairs_run_is_foot_to_top() -> None:
    assert _stairs().run_m == pytest.approx(4.0)


def test_stairs_need_a_length() -> None:
    with pytest.raises(ValidationError, match="coincide"):
        _stairs(top=(0.1, 0.0))


def test_ids_are_unique_across_groups() -> None:
    bench = Item(id="s1", kind=ItemKind.BENCH, at=(1.0, 1.0))
    with pytest.raises(ValidationError, match="duplicate"):
        FurnitureCollection(
            generated_at=datetime(2026, 10, 7, tzinfo=UTC),
            stairs=[_stairs()],
            items=[bench],
        )


def test_collection_round_trips() -> None:
    collection = FurnitureCollection(
        generated_at=datetime(2026, 10, 7, tzinfo=UTC),
        stairs=[_stairs(railings="both")],
        items=[
            Item(
                id="b1",
                kind=ItemKind.BENCH,
                at=(2.0, 3.0),
                heading_deg=90,
                length_m=1.8,
            )
        ],
    )
    assert FurnitureCollection.model_validate_json(collection.model_dump_json()) == (
        collection
    )


def test_terrace_bank_width_is_optional() -> None:
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert Terrace(id="t", outline=square, z_m=3.0).bank_m is None
    banked = Terrace(id="t", outline=square, z_m=3.0, edge=Edge.SLOPE, bank_m=4.5)
    assert banked.bank_m == pytest.approx(4.5)
    with pytest.raises(ValidationError):
        Terrace(id="t", outline=square, z_m=3.0, bank_m=0.0)
