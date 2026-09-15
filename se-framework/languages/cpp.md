# C++ Engineering Guide

## Code Style
- Follow Google C++ Style Guide or LLVM conventions
- Use 2-space or 4-space indentation
- Use CamelCase for classes, snake_case for functions
- Use `const` whenever possible

## Best Practices

### Resource Management
- Use RAII (Resource Acquisition Is Initialization)
- Use smart pointers (`unique_ptr`, `shared_ptr`)
- Prefer `unique_ptr` over `shared_ptr`
- Use `make_unique`/`make_shared`

```cpp
class FileHandler {
    std::unique_ptr<FILE, FileCloser> file;
public:
    FileHandler(const std::string& path) 
        : file(fopen(path.c_str(), "r")) {
        if (!file) {
            throw std::runtime_error("Cannot open file");
        }
    }
    // No need for explicit destructor - RAII handles cleanup
};
```

### Modern C++ Features
- Use `auto` for type inference
- Use range-based for loops
- Use `nullptr` instead of `NULL`
- Use `constexpr` for compile-time evaluation
- Use `std::array` over C arrays

### Error Handling
- Use exceptions for exceptional cases
- Use `noexcept` for functions that don't throw
- Use `std::optional` for optional return values
- Use `std::variant` for tagged unions

### Concurrency
- Use `std::thread` for threads
- Use `std::async` for async operations
- Use `std::mutex` and `std::lock_guard`
- Use `std::atomic` for atomic operations
- Prefer thread pools over raw threads

## Performance
- Use move semantics for expensive objects
- Prefer `emplace` over `push`
- Use `std::vector` reserve when size known
- Use cache-friendly data structures
- Profile with `perf` or VTune

## Memory Management
- Avoid manual `new`/`delete`
- Use memory pools for frequent allocations
- Be aware of false sharing
- Use `std::deque` for frequent push/pop

## Testing
- Use Google Test or Catch2
- Use fixtures for test data
- Test both success and failure cases
- Use parameterized tests

## Tools
- `clang-format`: Code formatting
- `clang-tidy`: Linting
- `clang-analyzer`: Static analysis
- `gtest`/`catch2`: Testing
- `cmake`: Build system
- `valgrind`: Memory analysis
- `perf`: Profiling