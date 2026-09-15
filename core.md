# Core Engineering Principles

## 1. Problem Understanding

Before writing code, fully understand the problem:

### Requirements Analysis
- **Functional requirements**: What must the system do?
- **Non-functional requirements**: Performance, security, scalability?
- **Constraints**: Budget, timeline, technology stack, dependencies?
- **Edge cases**: What unusual inputs or conditions must be handled?

### Clarification Checklist
- [ ] What is the input domain?
- [ ] What are the expected outputs?
- [ ] What are the failure modes?
- [ ] What is the scale (data volume, users, requests)?
- [ ] What are the integration points?
- [ ] What existing systems must it interact with?

## 2. Algorithm Selection

Choose algorithms based on complexity analysis:

### Complexity Classes
- **O(1)**: Constant time - ideal
- **O(log n)**: Logarithmic - excellent
- **O(n)**: Linear - good
- **O(n log n)**: Linearithmic - acceptable for most cases
- **O(n²)**: Quadratic - avoid for large n
- **O(2ⁿ)**: Exponential - only for small inputs

### Selection Guidelines
1. Analyze the data size and access patterns
2. Consider memory constraints
3. Evaluate worst-case, average-case, and best-case scenarios
4. Check for existing optimized algorithms/libraries
5. Benchmark before optimizing (measure first)

## 3. Modular Design

### Single Responsibility Principle
Each module/class should have exactly one reason to change.

### Dependency Direction
- Depend on abstractions, not concretions
- Higher-level modules should not depend on lower-level modules
- Use dependency injection for testability

### Module Boundaries
- **Public API**: Stable, well-documented interface
- **Internal implementation**: Can change freely
- **Side effects**: Minimize and document explicitly

## 4. Error Handling Strategy

### Error Classification
1. **Expected errors**: Invalid input, network failures, file not found
2. **Unexpected errors**: Bugs, memory exhaustion, hardware failures
3. **Recoverable errors**: Can retry or use fallback
4. **Non-recoverable errors**: Must terminate or restart

### Error Handling Rules
1. Handle errors at the appropriate level
2. Provide meaningful error messages
3. Don't swallow exceptions silently
4. Use specific exception types
5. Clean up resources in `finally` blocks
6. Log errors with sufficient context

### Defensive Programming
- Validate all inputs
- Check preconditions and postconditions
- Use assertions for invariants
- Handle null/None values explicitly
- Set sensible defaults
- Fail fast for unrecoverable errors

## 5. Code Quality Standards

### Readability
- Use meaningful variable and function names
- Keep functions small and focused
- Use consistent formatting and naming conventions
- Avoid deep nesting (max 3-4 levels)
- Use early returns to reduce nesting

### Maintainability
- Follow DRY (Don't Repeat Yourself) principle
- Extract common logic into reusable functions
- Use configuration over hardcoding
- Document non-obvious decisions
- Keep the codebase navigable

### Testing
- Write tests alongside code
- Test edge cases and error conditions
- Use descriptive test names
- Keep tests fast and isolated
- Maintain test coverage above 80%