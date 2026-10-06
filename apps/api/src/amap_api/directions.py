"""Human-readable TR/EN instructions for route steps."""

from amap_api.routing import Step, Turn
from amap_contracts.text import spells_other_floor

_COMPASS_TR = (
    "kuzey",
    "kuzeydoğu",
    "doğu",
    "güneydoğu",
    "güney",
    "güneybatı",
    "batı",
    "kuzeybatı",
)
_COMPASS_EN = (
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
)

_TURN_TR = {
    Turn.SLIGHT_LEFT: "Hafif sola dönün",
    Turn.LEFT: "Sola dönün",
    Turn.SHARP_LEFT: "Keskin sola dönün",
    Turn.SLIGHT_RIGHT: "Hafif sağa dönün",
    Turn.RIGHT: "Sağa dönün",
    Turn.SHARP_RIGHT: "Keskin sağa dönün",
    Turn.U_TURN: "Geri dönün",
    Turn.STRAIGHT: "Düz devam edin",
}
_TURN_EN = {
    Turn.SLIGHT_LEFT: "Bear left",
    Turn.LEFT: "Turn left",
    Turn.SHARP_LEFT: "Turn sharp left",
    Turn.SLIGHT_RIGHT: "Bear right",
    Turn.RIGHT: "Turn right",
    Turn.SHARP_RIGHT: "Turn sharp right",
    Turn.U_TURN: "Turn around",
    Turn.STRAIGHT: "Continue straight",
}


def compass_index(bearing_deg: float) -> int:
    return round((bearing_deg % 360.0) / 45.0) % 8


def _metres(distance_m: float) -> int:
    """Round to a friendly figure: 5 m steps (minimum 1 m)."""
    return (
        max(1, int(round(distance_m / 5.0) * 5))
        if distance_m >= 5
        else max(1, round(distance_m))
    )


# U+2212 MINUS SIGN, as the web app writes basements too.
MINUS = "\u2212"


def _signed(floor: int) -> str:
    return f"{MINUS}{-floor}" if floor < 0 else str(floor)


def floor_tr(floor: int) -> str:
    """ "zemin kat", "2. kat", and "-1. kat" with a U+2212 minus sign."""
    return "zemin kat" if floor == 0 else f"{_signed(floor)}. kat"


def floor_en(floor: int, article: bool = False) -> str:
    """ "ground floor" ("the ground floor" after "to"), "floor 2", "floor -1"."""
    if floor == 0:
        return "the ground floor" if article else "ground floor"
    return f"floor {_signed(floor)}"


def _shown_floor(step: Step, *labels: str) -> int | None:
    """The step's floor, unless a label it is shown with spells it otherwise."""
    names = [*labels, *([step.place.tr, step.place.en] if step.place else [])]
    if step.floor is None or any(spells_other_floor(n, step.floor) for n in names):
        return None
    return step.floor


def _where(step: Step, *labels: str) -> tuple[str, str]:
    """ " (M Blok, 5. kat)" / " (M Block, floor 5)", or "" when unknown."""
    tr = [f"{step.building} Blok"] if step.building else []
    en = [f"{step.building} Block"] if step.building else []
    floor = _shown_floor(step, *labels)
    if floor is not None:
        tr.append(floor_tr(floor))
        en.append(floor_en(floor))
    if not tr:
        return "", ""
    return f" ({', '.join(tr)})", f" ({', '.join(en)})"


def _indoor_instruction(step: Step) -> tuple[str, str]:
    place_tr = step.place.tr if step.place else ""
    place_en = step.place.en if step.place else ""
    block = step.building
    if step.turn is Turn.ENTER:
        if block:
            return f"{block} Blok'a girin", f"Enter {block} Block"
        if step.place:  # a building without a block code, by its tour area
            return f"{place_tr} binasına girin", f"Enter {place_en}"
        return "Binaya girin", "Enter the building"
    if step.turn is Turn.THROUGH:
        if block:
            return f"{block} Blok'un içinden geçin", f"Walk through {block} Block"
        if step.place:
            return f"{place_tr} binasının içinden geçin", f"Walk through {place_en}"
        return "Binanın içinden geçin", "Walk through the building"
    if step.turn in (Turn.STAIRS_UP, Turn.STAIRS_DOWN):
        n = abs(step.floors)
        up = step.turn is Turn.STAIRS_UP
        plural = "floor" if n == 1 else "floors"
        tr = f"Merdivenle {n} kat {'çıkın' if up else 'inin'}"
        en = f"Take the stairs {'up' if up else 'down'} {n} {plural}"
        floor = _shown_floor(step)
        if floor is not None:
            tr += f" ({floor_tr(floor)})"
            en += f" to {floor_en(floor, article=True)}"
        return tr, en
    if step.turn is Turn.START:
        where_tr, where_en = _where(step)
        return f"Yola çıkın: {place_tr}{where_tr}", f"Start at {place_en}{where_en}"
    return f"Devam edin: {place_tr}", f"Continue to {place_en}"


def instruction(
    step: Step, destination_tr: str, destination_en: str
) -> tuple[str, str]:
    """Return (Turkish, English) text for one step."""
    if step.turn is Turn.ARRIVE:
        where_tr, where_en = (
            _where(step, destination_tr, destination_en) if step.indoor else ("", "")
        )
        return (
            f"Vardınız: {destination_tr}{where_tr}",
            f"You have arrived: {destination_en}{where_en}",
        )
    if step.indoor:
        return _indoor_instruction(step)
    d = _metres(step.distance_m)
    i = compass_index(step.bearing_deg)
    if step.turn is Turn.EXIT:
        block, name = step.building, step.place
        if block:
            left_tr, left_en = f"{block} Blok'tan çıkın", f"Leave {block} Block"
        elif name:
            left_tr, left_en = f"{name.tr} binasından çıkın", f"Leave {name.en}"
        else:
            left_tr, left_en = "Binadan çıkın", "Leave the building"
        return (
            f"{left_tr}, {_COMPASS_TR[i]} yönünde {d} m yürüyün",
            f"{left_en} and head {_COMPASS_EN[i]} for {d} m",
        )
    if step.turn is Turn.START:
        return (
            f"{_COMPASS_TR[i].capitalize()} yönünde {d} m yürüyün",
            f"Head {_COMPASS_EN[i]} for {d} m",
        )
    if step.turn not in _TURN_TR:  # an indoor kind of step on a measured spot
        return _indoor_instruction(step)
    return f"{_TURN_TR[step.turn]}, {d} m yürüyün", f"{_TURN_EN[step.turn]}, walk {d} m"
