# Testing Strategy

## Testing Pyramid

### Unit Tests (70%)
- Test individual functions and classes
- Fast and isolated
- Mock external dependencies
- High coverage target: 80%+

### Integration Tests (20%)
- Test component interactions
- Use real databases/services or test doubles
- Verify API contracts
- Test data flow between components

### End-to-End Tests (10%)
- Test complete user workflows
- Use browser automation or HTTP clients
- Test real user scenarios
- Slower but validate full system

## Test Design

### Test Structure
- **Arrange**: Set up test data and dependencies
- **Act**: Execute the code under test
- **Assert**: Verify expected outcomes

### Naming Conventions
- Use descriptive test names
- Follow pattern: `Should_<expected_behavior>_<when>_<condition>`
- Example: `Should_ReturnUser_When_IdIsValid`

### Test Data
- Use factories or fixtures for test data
- Avoid hardcoded test data
- Use meaningful but simple values
- Clean up after tests

## Testing Patterns

### Unit Testing
- Test public methods and functions
- Mock dependencies
- Test edge cases and error conditions
- Keep tests fast (< 100ms each)

### Property-Based Testing
- Generate random inputs and verify properties
- Great for finding edge cases
- Libraries: Hypothesis (Python), FastCheck (JS)

### Mutation Testing
- Introduce bugs into code
- Verify tests catch them
- Measures test suite effectiveness

### Contract Testing
- Verify API contracts between services
- Consumer-driven contracts
- Tools: Pact, Spring Cloud Contract

## Mocking Strategy

### When to Mock
- External services (HTTP, databases)
- File system operations
- Time-dependent code
- Random number generators

### Mocking Best Practices
- Only mock what you own or control
- Verify interactions when important
- Use spies for partial mocking
- Avoid mocking the system under test

### Mocking Libraries
- Python: `unittest.mock`, `pytest-mock`
- JavaScript: `jest.mock`, `sinon`
- Java: `Mockito`, `EasyMock`
- C#: `Moq`, `NSubstitute`

## Test Automation

### CI/CD Integration
- Run tests on every commit
- Block merges on test failures
- Run tests in parallel
- Generate coverage reports

### Test Environments
- Use isolated test databases
- Reset state between tests
- Use Docker for consistency
- Avoid test interdependencies

### Performance Testing
- Load testing: Simulate user traffic
- Stress testing: Push beyond limits
- Soak testing: Long-duration stability
- Spike testing: Sudden traffic increases

## Test Anti-Patterns

1. **Testing Implementation Details**: Test behavior, not internals
2. **Over-mocking**: Mock everything, lose integration value
3. **Slow Tests**: Not isolated, use real resources
4. **Fragile Tests**: Overly sensitive to changes
5. **Ignoring Failures**: Commenting out failing tests

## Testing Checklist

Before marking code as tested:
- [ ] Unit tests for all public methods
- [ ] Edge cases covered
- [ ] Error conditions tested
- [ ] Integration points verified
- [ ] Performance acceptable
- [ ] Tests run in CI/CD
- [ ] Coverage above 80%
