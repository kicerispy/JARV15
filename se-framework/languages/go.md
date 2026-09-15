# Go Engineering Guide

## Code Style
- Follow Go conventions (`gofmt`)
- Use tabs for indentation
- Use `camelCase` for functions and variables
- Use `PascalCase` for exported names
- Use short variable names in scoped code

## Best Practices

### Error Handling
- Go uses explicit error handling
- Return errors as last value
- Use `errors.Is()` and `errors.As()` for checking
- Use custom error types with `fmt.Errorf`

```go
func getUser(id int) (*User, error) {
    user, err := repository.FindByID(id)
    if err != nil {
        return nil, fmt.Errorf("failed to get user %d: %w", id, err)
    }
    return user, nil
}
```

### Concurrency
- Use goroutines for lightweight threads
- Use channels for communication
- Use `sync.WaitGroup` for waiting
- Use `sync.Mutex` for shared state
- Use `select` for multiplexing

```go
func processItems(items []Item) error {
    var wg sync.WaitGroup
    errCh := make(chan error, len(items))
    
    for _, item := range items {
        wg.Add(1)
        go func(item Item) {
            defer wg.Done()
            if err := process(item); err != nil {
                errCh <- err
            }
        }(item)
    }
    
    wg.Wait()
    close(errCh)
    
    for err := range errCh {
        return err
    }
    return nil
}
```

### Interfaces
- Use small interfaces
- Define interfaces for behavior
- Use `io.Reader` and `io.Writer` patterns
- Accept interfaces, return concrete types

## Project Structure
```
project/
  cmd/           # Main applications
  internal/      # Private packages
  pkg/           # Public packages
  api/           # API definitions
  web/           # Web templates/static
  configs/       # Configuration files
  migrations/    # Database migrations
```

## Testing
- Use `testing` standard library
- Use table-driven tests
- Use `testify` for assertions
- Use `go-test-runner` for CI

```go
func TestGetUser(t *testing.T) {
    tests := []struct {
        name string
        id   int
        want *User
        err  bool
    }{
        {"valid user", 1, &User{ID: 1, Name: "Alice"}, false},
        {"not found", 999, nil, true},
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            user, err := getUser(tt.id)
            if tt.err {
                assert.Error(t, err)
            } else {
                assert.NoError(t, err)
                assert.Equal(t, tt.want, user)
            }
        })
    }
}
```

## Performance
- Use `go benchmark` for performance testing
- Use `pprof` for profiling
- Avoid unnecessary allocations
- Use object pools for frequent allocations
- Use `sync.Pool` for reusable objects

## Tools
- `gofmt`: Code formatting
- `go vet`: Static analysis
- `golangci-lint`: Linting
- `testify`: Testing assertions
- `cobra`: CLI framework
- `gin`/`echo`: Web frameworks
- `grpc`: RPC framework