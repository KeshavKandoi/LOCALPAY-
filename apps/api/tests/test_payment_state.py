import pytest

from app.models import Payment
from app.services.payments import TRANSITIONS, PaymentError, transition


@pytest.mark.parametrize("state", list(TRANSITIONS))
@pytest.mark.parametrize("target", list(TRANSITIONS))
def test_payment_transition_matrix(state: str, target: str) -> None:
    payment = Payment(status=state)
    expected = {
        ("created", "authorized"),
        ("created", "failed"),
        ("authorized", "captured"),
        ("captured", "refunded"),
    }
    if (state, target) in expected:
        transition(payment, target)
        assert payment.status == target
    else:
        with pytest.raises(PaymentError):
            transition(payment, target)
        assert payment.status == state
