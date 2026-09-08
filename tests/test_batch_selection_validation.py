from __future__ import annotations

from app.services.backend_adapter import BackendService


def _service(processes: dict[int, dict], options: dict[int, list[str]], *, can_edit: bool = True):
    service = BackendService.__new__(BackendService)
    service.can_edit = lambda _area: can_edit
    service.get_process_area_dict = lambda process_id, _area: processes.get(process_id, {})
    service.process_visible_in_area = lambda process, _area: not process.get("cancelled")
    service.next_status_options = lambda _area, process_id: list(options.get(process_id, []))
    service.action_label = lambda _area, status: status
    service.process_actions = lambda process_id, _area: processes.get(process_id, {}).get("actions", [])
    return service


def test_validation_uses_current_state_and_returns_common_official_actions():
    service = _service(
        {
            10: {"id": 10, "proposta": "CP10"},
            27: {"id": 27, "proposta": "CP27"},
        },
        {10: ["INICIADO", "PARADO"], 27: ["INICIADO"]},
    )

    result = service.validate_batch_selection("PRODUCAO", [10, 27], "STATUS")

    assert result["valid_ids"] == [10, 27]
    assert result["incompatible"] == []
    assert result["common_statuses"] == ["INICIADO"]
    assert result["global_reason"] == ""


def test_validation_blocks_missing_cancelled_and_actionless_proposals_with_reasons():
    service = _service(
        {
            10: {"id": 10, "proposta": "CP10", "cancelled": True},
            27: {"id": 27, "proposta": "CP27"},
        },
        {27: []},
    )

    result = service.validate_batch_selection("PRODUCAO", [10, 27, 38], "STATUS")

    assert result["valid_ids"] == []
    assert [row["id"] for row in result["incompatible"]] == [10, 27, 38]
    assert "disponível" in result["incompatible"][0]["reason"]
    assert "ação compatível" in result["incompatible"][1]["reason"]
    assert "encontrada" in result["incompatible"][2]["reason"]


def test_validation_blocks_selection_without_one_common_status():
    service = _service(
        {10: {"id": 10, "proposta": "CP10"}, 27: {"id": 27, "proposta": "CP27"}},
        {10: ["PARADO"], 27: ["INICIADO"]},
    )

    result = service.validate_batch_selection("PRODUCAO", [10, 27], "STATUS")

    assert result["valid_ids"] == [10, 27]
    assert result["common_statuses"] == []
    assert "Não existe uma ação comum" in result["global_reason"]


def test_flow_validation_reuses_process_action_catalog_and_permission():
    service = _service(
        {
            10: {"id": 10, "proposta": "CP10", "actions": [{"id": "DEFINE_ITEM_FLOW"}]},
            27: {"id": 27, "proposta": "CP27", "actions": []},
        },
        {},
    )

    result = service.validate_batch_selection("PRODUCAO", [10, 27], "DEFINE_ITEM_FLOW")
    assert result["valid_ids"] == [10]
    assert result["incompatible"][0]["id"] == 27

    denied = _service({10: {"id": 10, "proposta": "CP10"}}, {}, can_edit=False)
    denied_result = denied.validate_batch_selection("PRODUCAO", [10], "STATUS")
    assert denied_result["valid_ids"] == []
    assert "permissão" in denied_result["incompatible"][0]["reason"]
