from helmcode.core.dependency_container import ServiceLocator


def test_service_locator_register_initializes_shared_container() -> None:
    ServiceLocator._instance = None

    ServiceLocator.register("answer", 42)

    assert ServiceLocator.resolve("answer") == 42
