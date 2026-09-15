# Java Engineering Guide

## Code Style
- Follow Google Java Style or Spring Boot conventions
- Use 4-space indentation
- Use CamelCase for classes, camelCase for methods
- Use descriptive names

## Best Practices

### Object-Oriented Design
- Use interfaces for type definitions
- Prefer composition over inheritance
- Use final classes/methods when possible
- Follow SOLID principles

### Error Handling
```java
public Optional<User> getUser(Long id) {
    try {
        return Optional.ofNullable(repository.findById(id));
    } catch (DataAccessException e) {
        logger.error("Failed to get user {}", id, e);
        return Optional.empty();
    }
}
```

### Concurrency
- Use `ExecutorService` for thread pools
- Use `CompletableFuture` for async operations
- Prefer immutable objects
- Use `synchronized` or `ReentrantLock` carefully

### Memory Management
- Use try-with-resources for AutoCloseable
- Be mindful of object references
- Use lazy initialization when appropriate
- Avoid unnecessary object creation

## Spring Boot Patterns

### Controller Layer
```java
@RestController
@RequestMapping("/users")
public class UserController {
    private final UserService userService;
    
    public UserController(UserService userService) {
        this userService = userService;
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<User> getUser(@PathVariable Long id) {
        return userService.findById(id)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
}
```

### Service Layer
- Annotate with `@Service`
- Use `@Transactional` for database operations
- Use constructor injection

### Repository Layer
- Extend `JpaSpecificationExecutor` for complex queries
- Use `@Repository` annotation
- Use specification pattern for dynamic queries

## Testing
- Use JUnit 5
- Use Mockito for mocking
- Use `@SpringBootTest` for integration tests
- Use Testcontainers for database tests
- Test with `@ParameterizedTest`

## Performance
- Use connection pooling (HikariCP)
- Use caching (EhCache, Redis)
- Use pagination for large datasets
- Use `@Async` for background tasks
- Profile with VisualVM or JProfiler

## Tools
- `Maven`/`Gradle`: Build tools
- `Spotless`: Code formatting
- `Checkstyle`: Linting
- `PMD`: Static analysis
- `JUnit`: Testing
- `Spring Boot DevTools`: Hot reload