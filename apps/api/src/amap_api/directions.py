"""Human-readable TR/EN instructions for route steps."""

from amap_api.routing import Step, Turn

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


def instruction(
    step: Step, destination_tr: str, destination_en: str
) -> tuple[str, str]:
    """Return (Turkish, English) text for one step."""
    if step.turn is Turn.ARRIVE:
        return f"Vardınız: {destination_tr}", f"You have arrived: {destination_en}"
    d = _metres(step.distance_m)
    if step.turn is Turn.START:
        i = compass_index(step.bearing_deg)
        return (
            f"{_COMPASS_TR[i].capitalize()} yönünde {d} m yürüyün",
            f"Head {_COMPASS_EN[i]} for {d} m",
        )
    return f"{_TURN_TR[step.turn]}, {d} m yürüyün", f"{_TURN_EN[step.turn]}, walk {d} m"
