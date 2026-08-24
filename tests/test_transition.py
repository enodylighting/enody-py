import math

import pytest

from enody import Configuration, Flux, Transition
from enody.interface import Fixture, Source


def test_linear_transition_exposes_target_and_duration():
    transition = Transition.linear(
        Configuration.blackbody(2700.0),
        Flux.relative(0.4),
        2.5,
    )

    assert repr(transition.configuration) == "Blackbody(2700.0)"
    assert transition.flux.value == pytest.approx(0.4)
    assert transition.duration == pytest.approx(2.5)
    assert repr(transition).startswith("Transition.linear(Blackbody(2700.0), Relative(")


@pytest.mark.parametrize("duration", [-1.0, math.nan, math.inf, -math.inf])
def test_linear_transition_rejects_invalid_duration(duration):
    with pytest.raises(
        ValueError,
        match="duration must be a finite, non-negative number of seconds",
    ):
        Transition.linear(Configuration.flux(), Flux.relative(0.0), duration)


def test_fixture_transition_requires_device_backing():
    fixture = Fixture("fixture", [])

    with pytest.raises(RuntimeError, match="transition requires a device-backed fixture"):
        fixture.transition(object())


def test_source_transition_requires_device_backing():
    source = Source("source", [])

    with pytest.raises(RuntimeError, match="transition requires a device-backed source"):
        source.transition(object())


def test_fixture_transition_delegates_to_native_fixture():
    expected = object()

    class RemoteFixture:
        def transition(self, transition):
            assert transition is expected
            return "fixture result"

    fixture = Fixture("fixture", [], remote_fixture=RemoteFixture())

    assert fixture.transition(expected) == "fixture result"


def test_source_transition_delegates_to_native_source():
    expected = object()

    class RemoteSource:
        def transition(self, transition):
            assert transition is expected
            return "source result"

    source = Source("source", [], remote_source=RemoteSource())

    assert source.transition(expected) == "source result"
