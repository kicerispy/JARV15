# Python Engineering Guide

## Code Style
- Follow PEP 8
- Use 4-space indentation
- Line length: 79-99 characters
- Use `black` for formatting
- Use `isort` for import sorting

## Best Practices

### Data Types
- Use type hints (`typing` module)
- Prefer `dataclasses` for simple data structures
- Use `NamedTuple` for immutable records
- Leverage `Literal` for specific string values

### Error Handling
```python
from typing import Optional

def get_user(user_id: int) -> Optional[User]:
    try:
        return UserRepository.get(user_id)
    except DatabaseError as e:
        logger.error(f"Failed to get user {user_id}: {e}")
        return None
```

### Concurrency
- Use `asyncio` for I/O-bound tasks
- Use `concurrent.futures` for CPU-bound tasks
- Prefer `async/await` over threading for I/O
- Use `multiprocessing` for parallel CPU work

### Memory Management
- Use generators for large datasets
- Use context managers (`with` statements)
- Be mindful of circular references
- Use `__slots__` for memory-intensive classes

## Testing
- Use `pytest` framework
- Use fixtures for test data
- Use `unittest.mock` for mocking
- Use `pytest-cov` for coverage
- Test with `@pytest.mark.parametrize`

## Common Patterns

### Factory Pattern
```python
class UserFactory:
    @staticmethod
    def create(name: str, email: str) -> User:
        return User(name=name, email=email)
```

### Repository Pattern
```python
class UserRepository:
    def get_by_id(self, user_id: int) -> Optional[User]:
        # Implementation
        pass
    
    def save(self, user: User) -> None:
        # Implementation
        pass
```

### Strategy Pattern
```python
from abc import ABC, abstractmethod

class PaymentStrategy(ABC):
    @abstractmethod
    def pay(self, amount: float) -> None:
        pass

class CreditCardPayment(PaymentStrategy):
    def pay(self, amount: float) -> None:
        # Implementation
        pass
```

## Performance Tips
- Use `lru_cache` for expensive function calls
- Prefer `collections.deque` for queue operations
- Use `bisect` for sorted list operations
- Profile with `cProfile` before optimizing
- Use `pandas` for data manipulation

## Tools
- `black`: Code formatting
- `isort`: Import sorting
- `flake8`/`ruff`: Linting
- `mypy`: Type checking
- `pytest`: Testing
- `pre-commit`: Git hooks