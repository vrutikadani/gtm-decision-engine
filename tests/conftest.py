import pytest

from gde.service import Service


@pytest.fixture
def svc():
    return Service()


def ev(svc, key, **changes):
    e = svc.event(key)
    e["payload"].update(changes)
    return e["provider"], e["payload"]
