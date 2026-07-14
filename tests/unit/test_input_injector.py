from ottomandevice.remote_desktop.input_injector import (
    InputInjector,
    extract_mouse_fields,
    parse_normalized_coordinate_strict,
    parse_scroll_delta,
)


def test_coordinate_mapping_to_native_pixels() -> None:
    injector = InputInjector(screen_width=1920, screen_height=1080)
    assert injector._to_native(0.0, 0.0) == (0, 0)
    assert injector._to_native(1.0, 1.0) == (1919, 1079)
    assert injector._to_native(0.5, 0.5) == (959, 539)


def test_parse_normalized_coordinate_strict_rejects_out_of_range() -> None:
    assert parse_normalized_coordinate_strict(0.5) == 0.5
    assert parse_normalized_coordinate_strict(1.0) == 1.0
    assert parse_normalized_coordinate_strict(1.1) is None
    assert parse_normalized_coordinate_strict(-0.01) is None
    assert parse_normalized_coordinate_strict("bad") is None


def test_parse_scroll_delta() -> None:
    assert parse_scroll_delta(120) == 120
    assert parse_scroll_delta(-120) == -120
    assert parse_scroll_delta(0) is None
    assert parse_scroll_delta("bad") is None


def test_extract_mouse_fields_prefers_payload() -> None:
    message = {
        "type": "MOUSE_MOVE",
        "x": 0.1,
        "payload": {"x": 0.9, "y": 0.4},
    }
    assert extract_mouse_fields(message) == {"x": 0.9, "y": 0.4}


def test_extract_mouse_fields_falls_back_to_top_level() -> None:
    message = {"type": "MOUSE_MOVE", "x": 0.53, "y": 0.41}
    assert extract_mouse_fields(message) == {"x": 0.53, "y": 0.41}
