# Rust Engineering Guide

## Code Style
- Follow Rust conventions
- Use 4-space indentation
- Use `snake_case` for functions and variables
- Use `PascalCase` for types

## Best Practices

### Ownership & Borrowing
- Understand ownership, borrowing, and lifetimes
- Use references instead of copying
- Use `&T` for read-only access
- Use `&mut T` for mutable access
- Use smart pointers when needed

### Error Handling
- Use `Result<T, E>` for recoverable errors
- Use `Option<T>` for optional values
- Use `?` operator for error propagation
- Use custom error types with `thiserror`

```rust
fn get_user(id: u32) -> Result<Option<User>, DatabaseError> {
    let user = repository.find_by_id(id)?;
    Ok(user)
}
```

### Concurrency
- Use `std::thread` for threads
- Use `tokio` or `async-std` for async
- Use channels for communication
- Use `Send` and `Sync` traits correctly
- Prefer message passing over shared state

### Pattern Matching
- Use `match` for exhaustive matching
- Use `if let` for single cases
- Use `while let` for loops
- Use `let ... else` for early returns

## Memory Safety
- Rust's borrow checker ensures memory safety
- Use `Rc` for reference counting
- Use `Arc` for thread-safe reference counting
- Use `Box` for heap allocation

## Testing
- Use built-in `#[test]` attribute
- Use `proptest` for property-based testing
- Use `mockall` for mocking
- Test with `cargo test`

## Performance
- Use iterators over manual loops
- Use `Vec` with `with_capacity`
- Use `&str` over `String` when possible
- Use `cargo clippy` for linting
- Profile with `cargo flamegraph`

## Tools
- `rustfmt`: Code formatting
- `clippy`: Linting
- `cargo`: Build and dependency management
- `rust-analyzer`: Language server
- `cargo-audit`: Security auditing