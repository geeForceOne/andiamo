"""Message templates: placeholders, and the built-in text when a template is broken."""

from __future__ import annotations

from custom_components.andiamo.texts import road_phrase, short_minutes, text, unknown_placeholders


def test_template_replaces_default() -> None:
    templates = {"leave_at": "Nimm die {line} nach {destination} um {departure}, los um {time}."}
    said = text("de", "leave_at", templates, time="10:07", minutes="7 Minuten", route="Work",
                line="S12", destination="Brugg", departure="10:12")
    assert said == "Nimm die S12 nach Brugg um 10:12, los um 10:07."


def test_missing_values_are_empty() -> None:
    # A car route has no line.
    assert text("de", "go_now", {"go_now": "Los{line}!"}, route="Work") == "Los!"


def test_broken_template_uses_default() -> None:
    assert text("de", "go_now", {"go_now": "Los {tme}!"}) == "Los jetzt!"
    assert text("de", "go_now", {"go_now": "Los {"}) == "Los jetzt!"
    assert text("de", "go_now", {"go_now": "{route.__class__}"}, route="Work") == "Los jetzt!"


def test_unknown_placeholders() -> None:
    assert unknown_placeholders("um {time} mit {line}") == []
    assert unknown_placeholders("um {tme}") == ["tme"]


def test_short_minutes() -> None:
    assert short_minutes(41) == "41 min"
    assert short_minutes(60) == "1 h"
    assert short_minutes(101) == "1 h 41 min"


def test_drive_time_names_roads() -> None:
    said = text("de", "drive_time", route="Work", destination="Büro", minutes="41 Minuten",
                traffic="12 Minuten", km="32", via=road_phrase("de", "via", "A2"),
                jam=road_phrase("de", "jam_on", "A1"))
    assert said == "Bis Büro brauchst du jetzt 41 Minuten über die A2, davon 12 Minuten Stau auf der A1."
    said = text("en", "drive_time_free", route="Work", destination="Office", minutes="29 minutes",
                traffic="0 minutes", km="32", via=road_phrase("en", "via", None), jam="")
    assert said == "Driving to Office takes 29 minutes right now, no traffic."
