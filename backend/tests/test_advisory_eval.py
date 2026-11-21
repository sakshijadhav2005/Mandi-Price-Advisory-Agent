"""The advisory evaluation set (evaluation/test_sets/advisory_questions.jsonl) must fully pass
with the offline answer writer: a routing or content regression fails the build."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.db.models import AdvisoryChunk, AdvisoryDocument, AgrometBulletin, KccAnswer, PesticideUse

SCRIPT = Path(__file__).resolve().parents[2] / "evaluation" / "scripts" / "run_advisory_eval.py"


@pytest.fixture
def eval_module(session):
    spec = importlib.util.spec_from_file_location("run_advisory_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def wipe():
        for model in (AdvisoryChunk, AdvisoryDocument, AgrometBulletin, KccAnswer, PesticideUse):
            session.execute(delete(model))
        session.commit()

    wipe()
    yield module
    wipe()


def test_every_advisory_question_passes(eval_module, session):
    eval_module.seed(session)
    report = eval_module.evaluate(session)
    assert report["failures"] == [], [(f["id"], f["problems"]) for f in report["failures"]]
    assert report["questions"] >= 30 and report["routing_accuracy"] == 1.0
    assert set(report["by_language"]) == {"en", "hi", "mr"}
