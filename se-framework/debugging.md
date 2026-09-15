# Debugging Methodology

## Systematic Approach

### 1. Reproduce the Bug
- Get a reliable reproduction case
- Minimize the input that triggers the bug
- Document exact steps to reproduce
- Identify environment details (OS, versions, config)

### 2. Gather Information
- Read error messages carefully
- Check logs (application, system, network)
- Review recent changes
- Identify affected components
- Collect metrics and traces

### 3. Formulate Hypotheses
- Based on symptoms, propose causes
- Prioritize by likelihood and impact
- Consider edge cases and boundary conditions
- Think about timing and race conditions

### 4. Test Hypotheses
- Design experiments to validate/refute
- Use debuggers and breakpoints
- Add logging at strategic points
- Isolate components for testing
- Use profiling tools to identify bottlenecks

### 5. Fix and Verify
- Implement the fix
- Verify the original bug is resolved
- Check for side effects
- Run existing tests
- Test edge cases

### 6. Prevent Recurrence
- Add tests for the bug
- Improve monitoring
- Document the root cause
- Update coding standards if needed

## Debugging Tools

### Logging
- Use structured logging (JSON format)
- Include context (request ID, user ID, timestamp)
- Set appropriate log levels
- Rotate and manage log files

### Debuggers
- Set conditional breakpoints
- Watch expressions for variable changes
- Step through code execution
- Inspect call stacks and memory

### Profilers
- CPU profilers: Identify hot paths
- Memory profilers: Find leaks and optimization opportunities
- Network profilers: Analyze API calls and latency

### Tracing
- Distributed tracing for microservices
- Track request flow across services
- Identify latency bottlenecks

## Common Bug Patterns

### Race Conditions
- Symptoms: Intermittent failures, timing-dependent
- Detection: Run tests with stress, use thread sanitizers
- Prevention: Use locks, atomic operations, or lock-free structures

### Memory Leaks
- Symptoms: Gradual memory increase, slowdown over time
- Detection: Memory profilers, heap dumps
- Prevention: Proper resource management, reference counting

### Off-by-One Errors
- Symptoms: Wrong results at boundaries
- Detection: Boundary testing, careful index handling
- Prevention: Clear loop invariants, bounds checking

### Null Pointer Exceptions
- Symptoms: Crashes, unhandled errors
- Detection: Static analysis, defensive coding
- Prevention: Null checks, Optional types, default values

### Performance Degradation
- Symptoms: Slow responses, high CPU usage
- Detection: Benchmarking, profiling
- Prevention: Algorithm analysis, caching, optimization

## Debugging Anti-Patterns

1. **Shotgun Debugging**: Adding random prints/logs without hypothesis
2. **Root Cause Skipping**: Fixing symptoms instead of causes
3. **Ignoring Warnings**: Not addressing compiler/linter warnings
4. **Over-Engineering Fixes**: Adding complexity to solve simple issues
5. **Skipping Verification**: Not testing the fix thoroughly

## Debugging Tools by Language

### Python
- `pdb`: Interactive debugger
- `logging`: Structured logging
- `cProfile`: CPU profiling
- `memory_profiler`: Memory analysis
- `faulthandler`: Dump tracebacks on crashes

### JavaScript/Node.js
- `console.debug`: Debug logging
- Node inspector: Built-in debugger
- `clinic.js`: Profiling toolkit
- `node --inspect`: Chrome DevTools integration

### Java
- `jstack`: Thread analysis
- `jmap`: Memory analysis
- VisualVM/JConsole: JVM monitoring
- IDE debuggers: Eclipse, IntelliJ

### Go
- `pprof`: CPU and memory profiling
- `delve`: Debugger
- `go test -race`: Race condition detection
- `trace`: Execution tracing

### C/C++
- `gdb`: Debugger
- `valgrind`: Memory analysis
- `strace`: System call tracing
- `perf`: Performance analysis