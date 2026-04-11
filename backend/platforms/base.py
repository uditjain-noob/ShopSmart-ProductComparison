from abc import ABC, abstractmethod
from ..models import ProductData


class BasePlatform(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def base_url(self) -> str: ...

    @abstractmethod
    def can_handle(self, url: str) -> bool: ...

    @abstractmethod
    def scrape_product(self, url: str) -> ProductData: ...
