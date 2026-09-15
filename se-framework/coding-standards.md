# Coding Standards

## General Principles

1. **Consistency**: Follow existing codebase conventions
2. **Clarity**: Code should be self-documenting
3. **Simplicity**: Prefer simple over clever
4. **Explicitness**: Make behavior clear and obvious

## Naming Conventions

### Variables
- Use descriptive, pronounceable names
- Avoid single-letter variables (except loop counters)
- Use camelCase for variables (JavaScript/TypeScript) or snake_case (Python)
- Prefix booleans with `is`, `has`, `can`, `should`

### Functions
- Use verb phrases
- Describe what the function does
- Avoid abbreviations

### Classes
- Use nouns
- PascalCase
- Abstract classes prefixed with `Abstract` or `Base`

### Constants
- UPPER_SNAKE_CASE
- Reserve for truly constant values

## Formatting Standards

### Indentation
- Use spaces, not tabs (typically 4 spaces)
- Consistent indentation throughout

### Line Length
- Maximum 100-120 characters
- Break long lines at logical points

### Blank Lines
- Separate logical sections with one blank line
- Two blank lines between top-level definitions

### Imports
- Group standard library imports first
- Third-party imports second
- Local imports last
- Use explicit imports over wildcard imports

## Documentation

### Docstrings
- Document all public functions and classes
- Include parameter descriptions
- Include return value descriptions
- Include raises/exceptions

### Comments
- Explain why, not what
- Use for non-obvious decisions
- Avoid redundant comments

### Type Annotations
- Use type hints in statically typed languages
- Use JSDoc/TypeScript in JavaScript
- Maintain types across function boundaries

## Language-Specific Patterns

### Python
- Use list/dict comprehensions for simple transformations
- Prefer generators for large datasets
- Use context managers (`with`) for resources
- Follow PEP 8 style guide

### JavaScript/TypeScript
- Use `const` for immutable references
- Prefer arrow functions for callbacks
- Use async/await for asynchronous code
- Leverage TypeScript types

### Java
- Use interfaces for type definitions
- Prefer composition over inheritance
- Use try-with-resources for AutoCloseable
- Follow Java conventions

### Go
- Use `err` as last return value
- Use goroutines for concurrency
- Prefer explicit error handling
- Follow effective Go conventions

## Code Review Checklist

Before submitting code, verify:

- [ ] Code follows style guide
- [ ] All tests pass
- [ ] New tests added for new functionality
- [ ] No commented-out code
- [ ] No debug print statements
- [ ] Documentation updated
- [ ] No redundant code
- [ ] Error handling is appropriate
- [ ] Performance is acceptable
