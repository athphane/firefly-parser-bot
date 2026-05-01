from dataclasses import dataclass

@dataclass
class Budget:
    id: str
    name: str

@dataclass
class Category:
    id: str
    name: str


@dataclass
class Account:
    id: str
    name: str

@dataclass
class Bill:
    id: str
    name: str
