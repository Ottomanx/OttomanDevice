from __future__ import annotations


from ottomandevice.permissions import Permission, has_permission, normalize_permissions


def test_normalize_permissions_filters_unknown_and_duplicates() -> None:
    result = normalize_permissions(["desktop", "mouse", "desktop", "invalid", 1, None])
    assert result == frozenset({"desktop", "mouse"})


def test_normalize_permissions_none_returns_empty() -> None:
    assert normalize_permissions(None) == frozenset()


def test_has_permission_with_enum_and_string() -> None:
    perms = frozenset({"desktop", "mouse"})
    assert has_permission(perms, Permission.MOUSE) is True
    assert has_permission(perms, "desktop") is True
    assert has_permission(perms, Permission.KEYBOARD) is False
