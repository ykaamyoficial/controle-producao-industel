from __future__ import annotations

import unittest

from app.ui.flow_review_state import (
    FlowRoute,
    FlowReviewItem,
    FlowReviewProposal,
    ItemState,
    apply_default,
    apply_default_to_all,
    apply_route_to_selected,
    build_payload,
    build_proposal,
    classify,
    count_affected_exceptions,
    reconcile_after_reload,
    route_from_flags,
    route_includes_production,
    route_to_flags,
    summarize,
    validate,
)


def make_item(
    item_id=1,
    *,
    proposal_id=1,
    original_route=FlowRoute.INDEFINIDO,
    original_reason="",
    is_editable=True,
    lock_reason=None,
    api_version=1,
) -> FlowReviewItem:
    return FlowReviewItem(
        proposal_id=proposal_id,
        item_id=item_id,
        api_version=api_version,
        numero_item=str(item_id),
        codigo="COD",
        descricao="Item de teste",
        quantidade="1",
        original_route=original_route,
        original_reason=original_reason,
        is_editable=is_editable,
        lock_reason=lock_reason,
    )


def make_proposal(items, *, proposal_id=1, loaded_version=5, default_route=None) -> FlowReviewProposal:
    return FlowReviewProposal(
        proposal_id=proposal_id,
        proposal_number="CP00001",
        customer_name="Cliente Teste",
        loaded_version=loaded_version,
        items=list(items),
        default_route=default_route,
    )


class RouteMappingTests(unittest.TestCase):
    def test_round_trip_for_every_defined_route(self):
        for route in (
            FlowRoute.PRODUZIR_GALVANIZAR,
            FlowRoute.PRODUZIR_SEM_GALVANIZAR,
            FlowRoute.NAO_PRODUZIR,
            FlowRoute.NAO_PRODUZIR_GALVANIZAR,
        ):
            produce, galvanize = route_to_flags(route)
            self.assertEqual(route_from_flags(produce, galvanize), route)
            # desktop-side lowercase flags (as returned by _api_flag) must resolve the same way
            self.assertEqual(route_from_flags(produce.lower(), galvanize.lower()), route)

    def test_partial_or_unknown_combinations_fall_back_to_indefinido(self):
        self.assertEqual(route_from_flags(None, None), FlowRoute.INDEFINIDO)
        self.assertEqual(route_from_flags("SIM", None), FlowRoute.INDEFINIDO)
        self.assertEqual(route_from_flags("SIM", "INDEFINIDO"), FlowRoute.INDEFINIDO)
        self.assertEqual(route_from_flags("lixo", "lixo"), FlowRoute.INDEFINIDO)

    def test_only_producing_routes_allow_automatic_production_start(self):
        self.assertTrue(route_includes_production(FlowRoute.PRODUZIR_GALVANIZAR))
        self.assertTrue(route_includes_production(FlowRoute.PRODUZIR_SEM_GALVANIZAR))
        self.assertFalse(route_includes_production(FlowRoute.NAO_PRODUZIR))
        self.assertFalse(route_includes_production(FlowRoute.NAO_PRODUZIR_GALVANIZAR))


class BuildProposalTests(unittest.TestCase):
    def test_maps_raw_api_dict_into_dataclasses(self):
        data = {
            "proposal_id": 42,
            "proposta": "CP05252",
            "cliente": "MNS ENGENHARIA",
            "version": 8,
            "itens": [
                {
                    "id": 101,
                    "api_version": 3,
                    "numero_item": "1",
                    "codigo_produto": "450.830",
                    "descricao": "Portao pedestre",
                    "quantidade": "50.0000",
                    "produzir_internamente": "sim",
                    "precisa_galvanizacao": "sim",
                    "motivo_nao_produzir": "",
                    "editavel": True,
                    "motivo_bloqueio": None,
                },
                {
                    "id": 102,
                    "api_version": 1,
                    "numero_item": "2",
                    "codigo_produto": "450.398",
                    "descricao": "Quadro enterrado",
                    "quantidade": "10.0000",
                    "produzir_internamente": "nao",
                    "precisa_galvanizacao": "nao",
                    "motivo_nao_produzir": "pronta_entrega",
                    "editavel": False,
                    "motivo_bloqueio": "Item ja possui producao registrada.",
                },
            ],
        }
        proposal = build_proposal(data)
        self.assertEqual(proposal.proposal_id, 42)
        self.assertEqual(proposal.proposal_number, "CP05252")
        self.assertEqual(proposal.loaded_version, 8)
        self.assertEqual(len(proposal.items), 2)

        first, second = proposal.items
        self.assertEqual(first.original_route, FlowRoute.PRODUZIR_GALVANIZAR)
        self.assertEqual(first.quantidade, "50")  # numeric_utils.format_decimal trims "50.0000"
        self.assertTrue(first.is_editable)

        self.assertEqual(second.original_route, FlowRoute.NAO_PRODUZIR)
        self.assertEqual(second.original_reason, "pronta_entrega")
        self.assertFalse(second.is_editable)
        self.assertEqual(second.lock_reason, "Item ja possui producao registrada.")
        # proposed_* must start as a copy of original_*, never mutate the source snapshot
        self.assertEqual(second.proposed_route, second.original_route)


class ApplyDefaultTests(unittest.TestCase):
    def test_undefined_only_scope_never_touches_already_defined_items(self):
        undefined_item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        exception_item = make_item(2, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        proposal = make_proposal([undefined_item, exception_item])

        changed = apply_default(proposal, FlowRoute.PRODUZIR_GALVANIZAR, scope="undefined_only", preserve_exceptions=True)

        self.assertEqual(changed, 1)
        self.assertEqual(undefined_item.proposed_route, FlowRoute.PRODUZIR_GALVANIZAR)
        self.assertEqual(exception_item.proposed_route, FlowRoute.NAO_PRODUZIR)  # untouched

    def test_all_editable_scope_preserves_exceptions_by_default(self):
        exception_item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        already_default_item = make_item(2, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        proposal = make_proposal([exception_item, already_default_item])

        changed = apply_default(proposal, FlowRoute.PRODUZIR_GALVANIZAR, scope="all_editable", preserve_exceptions=True)

        self.assertEqual(changed, 0)
        self.assertEqual(exception_item.proposed_route, FlowRoute.NAO_PRODUZIR)

    def test_overwrite_exceptions_requires_explicit_flag(self):
        exception_item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        proposal = make_proposal([exception_item])

        changed = apply_default(
            proposal, FlowRoute.PRODUZIR_GALVANIZAR, scope="all_editable", preserve_exceptions=True, overwrite_exceptions=True
        )

        self.assertEqual(changed, 1)
        self.assertEqual(exception_item.proposed_route, FlowRoute.PRODUZIR_GALVANIZAR)

    def test_global_reason_is_applied_to_eligible_items_that_require_it(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        proposal = make_proposal([item])

        changed = apply_default(
            proposal,
            FlowRoute.NAO_PRODUZIR,
            scope="undefined_only",
            preserve_exceptions=True,
            global_reason="Motivo comum do lote",
        )

        self.assertEqual(changed, 1)
        self.assertEqual(item.proposed_route, FlowRoute.NAO_PRODUZIR)
        self.assertEqual(item.proposed_reason, "Motivo comum do lote")

    def test_global_reason_preserves_an_existing_individual_reason(self):
        item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="Motivo individual")
        proposal = make_proposal([item])

        changed = apply_default(
            proposal,
            FlowRoute.NAO_PRODUZIR,
            scope="all_editable",
            preserve_exceptions=True,
            global_reason="Motivo comum do lote",
        )

        self.assertEqual(changed, 0)
        self.assertEqual(item.proposed_reason, "Motivo individual")

    def test_global_reason_overwrites_an_existing_reason_when_requested(self):
        item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="Motivo individual")
        proposal = make_proposal([item])

        changed = apply_default(
            proposal,
            FlowRoute.NAO_PRODUZIR,
            scope="all_editable",
            preserve_exceptions=False,
            overwrite_exceptions=True,
            global_reason="Motivo comum do lote",
        )

        self.assertEqual(changed, 1)
        self.assertEqual(item.proposed_reason, "Motivo comum do lote")

    def test_locked_items_are_never_touched_by_the_default(self):
        locked_item = make_item(1, original_route=FlowRoute.INDEFINIDO, is_editable=False, lock_reason="Item ja possui producao registrada.")
        proposal = make_proposal([locked_item])

        changed = apply_default(proposal, FlowRoute.PRODUZIR_GALVANIZAR, scope="all_editable", preserve_exceptions=False, overwrite_exceptions=True)

        self.assertEqual(changed, 0)
        self.assertEqual(locked_item.proposed_route, FlowRoute.INDEFINIDO)

    def test_apply_default_to_all_sums_across_proposals(self):
        p1 = make_proposal([make_item(1, original_route=FlowRoute.INDEFINIDO)], proposal_id=1)
        p2 = make_proposal([make_item(2, original_route=FlowRoute.INDEFINIDO), make_item(3, original_route=FlowRoute.INDEFINIDO)], proposal_id=2)

        changed = apply_default_to_all([p1, p2], FlowRoute.PRODUZIR_SEM_GALVANIZAR, scope="undefined_only", preserve_exceptions=True)

        self.assertEqual(changed, 3)
        self.assertEqual(p1.default_route, FlowRoute.PRODUZIR_SEM_GALVANIZAR)
        self.assertEqual(p2.default_route, FlowRoute.PRODUZIR_SEM_GALVANIZAR)

    def test_count_affected_exceptions_matches_what_would_be_overwritten(self):
        exception_item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        default_item = make_item(2, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        undefined_item = make_item(3, original_route=FlowRoute.INDEFINIDO)
        proposal = make_proposal([exception_item, default_item, undefined_item])

        self.assertEqual(count_affected_exceptions(proposal, FlowRoute.PRODUZIR_GALVANIZAR, scope="all_editable"), 1)
        self.assertEqual(count_affected_exceptions(proposal, FlowRoute.PRODUZIR_GALVANIZAR, scope="undefined_only"), 0)


class ClassifyTests(unittest.TestCase):
    def test_padrao_when_untouched_and_matches_default(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.PADRAO)

    def test_excecao_existente_when_untouched_and_differs_from_default(self):
        item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.EXCECAO_EXISTENTE)

    def test_excecao_criada_when_user_edits_away_from_default(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        item.proposed_route = FlowRoute.NAO_PRODUZIR
        item.proposed_reason = "pronta_entrega"
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.EXCECAO_CRIADA)

    def test_alterado_when_user_edits_to_match_default(self):
        item = make_item(1, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        item.proposed_route = FlowRoute.PRODUZIR_GALVANIZAR
        item.proposed_reason = ""
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.ALTERADO)

    def test_nao_definido_when_route_is_still_indefinido(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.NAO_DEFINIDO)

    def test_bloqueado_overrides_everything_else(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR, is_editable=False, lock_reason="Item ja foi entregue ao cliente.")
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.BLOQUEADO)

    def test_com_problema_when_reason_is_missing(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        item.proposed_route = FlowRoute.NAO_PRODUZIR
        item.proposed_reason = ""
        self.assertEqual(classify(item, FlowRoute.PRODUZIR_GALVANIZAR), ItemState.COM_PROBLEMA)


class ValidateTests(unittest.TestCase):
    def test_missing_reason_blocks_save(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        item.proposed_route = FlowRoute.NAO_PRODUZIR
        proposal = make_proposal([item])
        issues = validate([proposal])
        self.assertTrue(any("Motivo" in issue.message for issue in issues))

    def test_locked_item_untouched_never_blocks_save(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO, is_editable=False, lock_reason="bloqueado")
        proposal = make_proposal([item])
        self.assertEqual(validate([proposal]), [])

    def test_locked_item_touched_blocks_save(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR, is_editable=False, lock_reason="bloqueado")
        item.proposed_route = FlowRoute.NAO_PRODUZIR
        item.proposed_reason = "pronta_entrega"
        proposal = make_proposal([item])
        issues = validate([proposal])
        self.assertTrue(any("bloqueado" in issue.message.lower() for issue in issues))

    def test_duplicate_item_ids_are_flagged(self):
        proposal = make_proposal([make_item(1), make_item(1)])
        issues = validate([proposal])
        self.assertTrue(any("duplicado" in issue.message.lower() for issue in issues))

    def test_invalid_version_is_flagged(self):
        proposal = make_proposal([make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)], loaded_version=0)
        issues = validate([proposal])
        self.assertTrue(any("versao" in issue.message.lower() for issue in issues))

    def test_fully_defined_editable_items_have_no_issues(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        proposal = make_proposal([item])
        self.assertEqual(validate([proposal]), [])


class BuildPayloadTests(unittest.TestCase):
    def test_returns_none_when_nothing_changed(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        proposal = make_proposal([item])
        self.assertIsNone(build_payload(proposal))

    def test_includes_only_touched_editable_items_with_expected_keys(self):
        untouched = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR, api_version=4)
        touched = make_item(2, original_route=FlowRoute.INDEFINIDO, api_version=7)
        touched.proposed_route = FlowRoute.NAO_PRODUZIR
        touched.proposed_reason = "pronta_entrega"
        locked_but_touched = make_item(3, original_route=FlowRoute.PRODUZIR_GALVANIZAR, is_editable=False, lock_reason="bloqueado")
        locked_but_touched.proposed_route = FlowRoute.NAO_PRODUZIR

        proposal = make_proposal([untouched, touched, locked_but_touched])
        payload = build_payload(proposal)

        self.assertEqual(len(payload), 1)
        row = payload[0]
        self.assertEqual(row["id"], 2)
        self.assertEqual(row["api_version"], 7)
        self.assertEqual(row["produzir_internamente"], "nao")
        self.assertEqual(row["precisa_galvanizacao"], "nao")
        self.assertEqual(row["motivo_nao_produzir"], "pronta_entrega")

    def test_reason_is_cleared_in_payload_when_route_does_not_require_it(self):
        item = make_item(1, original_route=FlowRoute.INDEFINIDO)
        item.proposed_route = FlowRoute.PRODUZIR_GALVANIZAR
        item.proposed_reason = "texto residual que nao deveria ser enviado"
        proposal = make_proposal([item])
        payload = build_payload(proposal)
        self.assertEqual(payload[0]["motivo_nao_produzir"], "")


class BulkEditTests(unittest.TestCase):
    def test_apply_route_to_selected_skips_locked_items(self):
        editable = make_item(1, original_route=FlowRoute.INDEFINIDO)
        editable.is_selected = True
        locked = make_item(2, original_route=FlowRoute.INDEFINIDO, is_editable=False, lock_reason="bloqueado")
        locked.is_selected = True
        not_selected = make_item(3, original_route=FlowRoute.INDEFINIDO)

        changed, skipped = apply_route_to_selected([editable, locked, not_selected], FlowRoute.PRODUZIR_SEM_GALVANIZAR)

        self.assertEqual(changed, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(editable.proposed_route, FlowRoute.PRODUZIR_SEM_GALVANIZAR)
        self.assertEqual(locked.proposed_route, FlowRoute.INDEFINIDO)
        self.assertEqual(not_selected.proposed_route, FlowRoute.INDEFINIDO)


class RestoreTests(unittest.TestCase):
    def test_restore_original_undoes_manual_edit(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        item.proposed_route = FlowRoute.NAO_PRODUZIR
        item.proposed_reason = "pronta_entrega"
        item.restore_original()
        self.assertEqual(item.proposed_route, FlowRoute.PRODUZIR_GALVANIZAR)
        self.assertEqual(item.proposed_reason, "")

    def test_restore_default_applies_the_chosen_default(self):
        item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        item.proposed_route = FlowRoute.NAO_PRODUZIR
        item.proposed_reason = "pronta_entrega"
        item.restore_default(FlowRoute.PRODUZIR_SEM_GALVANIZAR)
        self.assertEqual(item.proposed_route, FlowRoute.PRODUZIR_SEM_GALVANIZAR)
        self.assertEqual(item.proposed_reason, "")


class SummarizeTests(unittest.TestCase):
    def test_counts_match_individual_classification(self):
        default_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        exception_item = make_item(2, original_route=FlowRoute.NAO_PRODUZIR, original_reason="pronta_entrega")
        undefined_item = make_item(3, original_route=FlowRoute.INDEFINIDO)
        locked_item = make_item(4, original_route=FlowRoute.INDEFINIDO, is_editable=False, lock_reason="bloqueado")
        proposal = make_proposal(
            [default_item, exception_item, undefined_item, locked_item],
            default_route=FlowRoute.PRODUZIR_GALVANIZAR,
        )

        summary = summarize([proposal])

        self.assertEqual(summary.proposal_count, 1)
        self.assertEqual(summary.item_count, 4)
        self.assertEqual(summary.default_count, 1)
        self.assertEqual(summary.existing_exception_count, 1)
        self.assertEqual(summary.undefined_count, 1)
        self.assertEqual(summary.locked_count, 1)
        self.assertEqual(summary.changed_count, 0)


class ReconcileAfterReloadTests(unittest.TestCase):
    def test_untouched_edit_is_reapplied_when_server_item_did_not_change(self):
        old_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        old_item.proposed_route = FlowRoute.NAO_PRODUZIR
        old_item.proposed_reason = "pronta_entrega"
        old_proposal = make_proposal([old_item])

        fresh_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR, api_version=old_item.api_version)
        fresh_proposal = make_proposal([fresh_item], loaded_version=old_proposal.loaded_version + 1)

        conflicted = reconcile_after_reload(old_proposal, fresh_proposal)

        self.assertEqual(conflicted, [])
        self.assertEqual(fresh_item.proposed_route, FlowRoute.NAO_PRODUZIR)
        self.assertEqual(fresh_item.proposed_reason, "pronta_entrega")

    def test_real_conflict_keeps_server_value_and_is_reported(self):
        old_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        old_item.proposed_route = FlowRoute.NAO_PRODUZIR
        old_item.proposed_reason = "pronta_entrega"
        old_proposal = make_proposal([old_item])

        # someone else changed this item's route on the server in the meantime
        fresh_item = make_item(1, original_route=FlowRoute.PRODUZIR_SEM_GALVANIZAR, api_version=old_item.api_version + 1)
        fresh_proposal = make_proposal([fresh_item], loaded_version=old_proposal.loaded_version + 1)

        conflicted = reconcile_after_reload(old_proposal, fresh_proposal)

        self.assertEqual(conflicted, [1])
        self.assertEqual(fresh_item.proposed_route, FlowRoute.PRODUZIR_SEM_GALVANIZAR)  # server value preserved, not overwritten

    def test_items_never_edited_locally_are_left_alone(self):
        old_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)  # never touched
        old_proposal = make_proposal([old_item])
        fresh_item = make_item(1, original_route=FlowRoute.PRODUZIR_SEM_GALVANIZAR)
        fresh_proposal = make_proposal([fresh_item])

        conflicted = reconcile_after_reload(old_proposal, fresh_proposal)

        self.assertEqual(conflicted, [])
        self.assertEqual(fresh_item.proposed_route, FlowRoute.PRODUZIR_SEM_GALVANIZAR)  # untouched, keeps fresh server value

    def test_locked_fresh_item_is_not_force_edited(self):
        old_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR)
        old_item.proposed_route = FlowRoute.NAO_PRODUZIR
        old_item.proposed_reason = "pronta_entrega"
        old_proposal = make_proposal([old_item])

        fresh_item = make_item(1, original_route=FlowRoute.PRODUZIR_GALVANIZAR, is_editable=False, lock_reason="Item ja possui producao registrada.")
        fresh_proposal = make_proposal([fresh_item])

        conflicted = reconcile_after_reload(old_proposal, fresh_proposal)

        self.assertEqual(conflicted, [])
        self.assertEqual(fresh_item.proposed_route, FlowRoute.PRODUZIR_GALVANIZAR)  # never force-applied to a locked item


if __name__ == "__main__":
    unittest.main()
