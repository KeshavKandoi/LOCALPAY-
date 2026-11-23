from app.services.reports import diagnostics


def test_missing_context_cannot_prove_duplicate_processing() -> None:
    assertion = {
        "type": "application_event_count",
        "expected": 1,
        "observed": 2,
        "status": "failed",
    }
    assert diagnostics({"assertions": [assertion]}) == []
    assert (
        diagnostics({"evidence": {"waiting_timed_out": True}})[0]["classification"]
        == "suspected"
    )


def test_invalid_signature_diagnostic_requires_exclusive_evidence() -> None:
    assertion = {
        "type": "application_event_count",
        "expected": 0,
        "observed": 1,
        "status": "failed",
    }
    assert (
        diagnostics({"assertions": [assertion], "evidence": {"event_count": 1}}) == []
    )
    result = diagnostics(
        {
            "assertions": [assertion],
            "evidence": {
                "event_count": 1,
                "only_invalid_signatures_observed": True,
            },
        }
    )
    assert result[0]["code"] == "invalid_signature_processing"
