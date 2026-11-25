"""Expected yield and part weight are learned from production history (task T256).

SC-010 names both as figures an instrumented item should carry an observed
origin for, and FR-015d says yield is learned per failure mode. Before this,
only print time and purge waste could ever become observed.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.variance_service import VarianceDecision
from app.tasks import telemetry
from app.tasks.telemetry import (
    YieldEvidence,
    part_weight_outcome,
    pooled_yield,
    runs_under_current_mode,
    yield_evidence,
)

MODEL_ID = uuid.uuid4()
SPOOL_ID = uuid.uuid4()


def _model(**overrides):
    values = dict(
        id=MODEL_ID,
        prints_per_plate=4,
        failure_mode="per_part",
        failure_mode_since=None,
        expected_yield=Decimal("0.9"),
        materials=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _item_run(ok: int, lost: int, *, model_id=MODEL_ID, day: int = 10, grams=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        total_plates=0,
        completed_at=datetime(2026, 10, day, tzinfo=timezone.utc),
        started_at=None,
        items=[SimpleNamespace(model_id=model_id, successful_quantity=ok, failed_quantity=lost)],
        plates=[],
        materials=[SimpleNamespace(spool_id=SPOOL_ID, actual_model_weight_grams=grams)]
        if grams is not None
        else [],
    )


class TestYieldEvidence:
    def test_an_item_run_counts_parts_and_the_plates_they_filled(self) -> None:
        # 8 parts at 4 a plate is 2 plates; 1 failed part condemns 1 plate.
        assert yield_evidence(_item_run(7, 1), _model()) == YieldEvidence(8, 7, 2, 1)

    def test_a_multi_plate_run_counts_each_plate(self) -> None:
        run = SimpleNamespace(
            total_plates=2,
            plates=[
                SimpleNamespace(
                    model_id=MODEL_ID, successful_prints=4, failed_prints=0, prints_per_plate=4
                ),
                SimpleNamespace(
                    model_id=MODEL_ID, successful_prints=0, failed_prints=4, prints_per_plate=4
                ),
            ],
        )
        assert yield_evidence(run, _model()) == YieldEvidence(8, 4, 2, 1)

    def test_another_models_parts_are_not_evidence(self) -> None:
        assert yield_evidence(_item_run(5, 0, model_id=uuid.uuid4()), _model()) is None


class TestPooledYield:
    def test_per_part_pools_parts_so_a_small_run_does_not_weigh_like_a_large_one(self) -> None:
        evidence = [YieldEvidence(40, 36, 10, 9), YieldEvidence(1, 0, 1, 0)]
        assert pooled_yield(evidence, "per_part", 4) == Decimal(36) / Decimal(41)

    def test_per_plate_is_the_nth_root_of_the_plate_success_rate(self) -> None:
        evidence = [YieldEvidence(16, 12, 4, 3)]
        learned = pooled_yield(evidence, "per_plate", 4)
        assert learned is not None
        # Plate survival is y**N (research D3), so y**4 must give back 3/4.
        assert abs(learned**4 - Decimal("0.75")) < Decimal("1e-20")

    def test_one_per_plate_makes_the_two_modes_agree(self) -> None:
        evidence = [YieldEvidence(10, 9, 10, 9)]
        assert pooled_yield(evidence, "per_plate", 1) == pooled_yield(evidence, "per_part", 1)

    def test_nothing_succeeding_is_not_learned_as_a_zero_yield(self) -> None:
        assert pooled_yield([YieldEvidence(4, 0, 1, 0)], "per_part", 4) is None


class TestOnlyTheCurrentModesRunsCount:
    def test_runs_before_the_mode_changed_are_left_out(self) -> None:
        before, after = _item_run(4, 0, day=1), _item_run(4, 0, day=20)
        model = _model(failure_mode_since=date(2026, 10, 15))
        assert runs_under_current_mode(model, [before, after]) == [after]

    def test_an_item_that_never_changed_mode_reads_every_run(self) -> None:
        runs = [_item_run(4, 0, day=1), _item_run(4, 0, day=20)]
        assert runs_under_current_mode(_model(), runs) == runs


class TestPartWeight:
    def test_a_clean_single_model_run_attributes_its_spool_to_the_line(self) -> None:
        material = SimpleNamespace(id=uuid.uuid4(), spool_id=SPOOL_ID)
        run = _item_run(8, 0, grams=Decimal("360"))
        assert part_weight_outcome(run, _model(), material) == Decimal("45")

    def test_a_run_with_failures_is_skipped(self) -> None:
        material = SimpleNamespace(id=uuid.uuid4(), spool_id=SPOOL_ID)
        assert (
            part_weight_outcome(_item_run(7, 1, grams=Decimal("360")), _model(), material) is None
        )

    def test_a_run_of_two_models_is_skipped(self) -> None:
        material = SimpleNamespace(id=uuid.uuid4(), spool_id=SPOOL_ID)
        run = _item_run(8, 0, grams=Decimal("360"))
        run.items.append(
            SimpleNamespace(model_id=uuid.uuid4(), successful_quantity=2, failed_quantity=0)
        )
        assert part_weight_outcome(run, _model(), material) is None

    def test_a_run_with_no_actual_for_the_spool_is_skipped(self) -> None:
        material = SimpleNamespace(id=uuid.uuid4(), spool_id=uuid.uuid4())
        assert (
            part_weight_outcome(_item_run(8, 0, grams=Decimal("360")), _model(), material) is None
        )


class TestTheSweepRoutesBothThroughTheVarianceService:
    @pytest.mark.asyncio
    async def test_yield_and_weight_are_considered_with_the_operators_thresholds(
        self, monkeypatch
    ) -> None:
        considered: list[tuple[str, str, int, object]] = []

        async def fake_consider(db, tenant, entity, *, entity_type, field_name, outcomes, **kwargs):
            considered.append((entity_type, field_name, len(outcomes), kwargs.get("observed")))
            return VarianceDecision(applied=False, reason="recorded")

        monkeypatch.setattr(telemetry, "consider_outcomes", fake_consider)

        material = SimpleNamespace(id=uuid.uuid4(), spool_id=SPOOL_ID, weight_grams=Decimal("40"))
        model = _model(materials=[material], print_time_minutes=None, waste_grams=None)
        runs = [_item_run(8, 0, grams=Decimal("360"), day=d) for d in (1, 2, 3)]

        decisions = await telemetry.learn_from_runs(
            None,
            SimpleNamespace(id=uuid.uuid4()),
            model,
            runs,
            min_outcomes=3,
            divergence_threshold_pct=Decimal("20"),
        )

        assert ("model", "expected_yield", 3, Decimal("1")) in considered
        assert ("model_material", "weight_grams", 3, None) in considered
        assert "expected_yield" in decisions
