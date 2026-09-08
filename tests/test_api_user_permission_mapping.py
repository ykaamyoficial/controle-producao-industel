import ast
from pathlib import Path

from api.app.modules.auth.permissions import OFFICIAL_PERMISSIONS
from app.services.api_proposal_storage import AREA_EDIT_PERMISSIONS, AREA_VIEW_PERMISSIONS, api_permission_level, legacy_permissions_to_api_codes


def test_legacy_operator_permissions_are_translated_to_sector_api_codes():
    permissions = {
        "control_general": "EDIT",
        "production": "EDIT",
        "galvanization": "EDIT",
        "expedition": "EDIT",
        "users_permissions": "NONE",
    }

    codes = set(legacy_permissions_to_api_codes(permissions))

    assert "proposals.create" in codes
    assert "proposals.change_status" in codes
    assert "production.update" in codes
    assert "galvanization.update" in codes
    assert "expedition.update" in codes
    assert "users.create" not in codes


def test_api_permission_level_uses_returned_api_codes_without_fixed_desktop_rules():
    codes = {"production.view", "galvanization.update"}

    assert api_permission_level(codes, "production") == "VIEW"
    assert api_permission_level(codes, "galvanization") == "EDIT"
    assert api_permission_level(codes, "expedition") == "NONE"
    assert api_permission_level(codes, "users_permissions") == "NONE"


def test_desktop_permission_catalog_matches_official_api_permissions():
    official_codes = {code for code, _name, _module in OFFICIAL_PERMISSIONS}
    desktop_codes = set().union(*AREA_VIEW_PERMISSIONS.values(), *AREA_EDIT_PERMISSIONS.values())

    assert desktop_codes
    assert desktop_codes <= official_codes


def test_proposal_list_routes_require_their_own_area_permissions():
    router_path = Path("api/app/modules/proposals/router.py")
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    expected = {
        "list_proposals": "PROPOSALS_VIEW",
        "list_production_proposals": "PRODUCTION_VIEW",
    }

    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in expected:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "require_permission"
                    and child.args
                    and isinstance(child.args[0], ast.Name)
                ):
                    found[node.name] = child.args[0].id

    assert found == expected
