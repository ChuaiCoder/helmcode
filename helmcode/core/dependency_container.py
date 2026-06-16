from __future__ import annotations

from typing import Any, Callable



class DependencyContainer:
    def __init__(self) -> None:
        self._singletons: dict[str, Any] = {}
        self._factories: dict[str, Callable[..., Any]] = {}
        self._dependencies: dict[str, list[str]] = {}

    def register_singleton(self, name: str, instance: Any) -> None:
        self._singletons[name] = instance

    def register_factory(self, name: str, factory: Callable[..., Any], dependencies: list[str] | None = None) -> None:
        self._factories[name] = factory
        if dependencies:
            self._dependencies[name] = dependencies

    def resolve(self, name: str) -> Any:
        if name in self._singletons:
            return self._singletons[name]

        if name in self._factories:
            dependencies = self._dependencies.get(name, [])
            resolved_deps = [self.resolve(dep) for dep in dependencies]
            instance = self._factories[name](*resolved_deps)
            self._singletons[name] = instance
            return instance

        raise KeyError(f"Dependency '{name}' not registered")

    def resolve_optional(self, name: str) -> Any | None:
        try:
            return self.resolve(name)
        except KeyError:
            return None

    def has(self, name: str) -> bool:
        return name in self._singletons or name in self._factories

    def clear(self) -> None:
        self._singletons.clear()
        self._factories.clear()
        self._dependencies.clear()


class ServiceLocator:
    _instance: "ServiceLocator | None" = None
    _container: DependencyContainer

    def __new__(cls) -> "ServiceLocator":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._container = DependencyContainer()
        return cls._instance

    @classmethod
    def container(cls) -> DependencyContainer:
        return cls()._container

    @classmethod
    def register(cls, name: str, instance: Any) -> None:
        cls.container().register_singleton(name, instance)

    @classmethod
    def resolve(cls, name: str) -> Any:
        return cls.container().resolve(name)
