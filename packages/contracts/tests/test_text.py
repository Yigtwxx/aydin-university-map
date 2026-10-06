import pytest

from amap_contracts import FLORYA_BBOX, lower_tr, search_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("İSTANBUL", "istanbul"),
        ("IĞDIR", "ığdır"),
        ("Kütüphane", "kütüphane"),
        ("İSTANBUL", "istanbul"),  # decomposed İ (I + combining dot)
    ],
)
def test_lower_tr_turkish_capitals_maps_dotted_and_dotless_i(
    raw: str, expected: str
) -> None:
    result = lower_tr(raw)
    assert result == expected, f"Expected {expected!r}, got {result!r}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KÜTÜPHANE", "kutuphane"),
        ("Kütüphane", "kutuphane"),
        ("kutuphane", "kutuphane"),
        ("IŞIK", "isik"),
        ("İnşaat Mühendisliği Lab.", "insaat muhendisligi lab"),
        ("T Blok -1.Kat", "t blok 1 kat"),
        ("  Öğrenci   İşleri  ", "ogrenci isleri"),
        ("", ""),
    ],
)
def test_search_key_mixed_turkish_labels_returns_ascii_key(
    raw: str, expected: str
) -> None:
    result = search_key(raw)
    assert result == expected, f"Expected {expected!r}, got {result!r}"


def test_florya_bbox_campus_hub_is_inside() -> None:
    assert FLORYA_BBOX.contains(40.991470, 28.797111), "Campus hub must be inside"


def test_florya_bbox_other_campus_is_outside() -> None:
    assert not FLORYA_BBOX.contains(41.020931, 28.583117), (
        "Büyükçekmece campus must be outside the Florya box"
    )
