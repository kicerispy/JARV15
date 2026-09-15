# Performance Optimization

## Performance Mindset

1. **Measure First**: Never optimize without data
2. **Identify Bottlenecks**: Use profilers to find hotspots
3. **Optimize Critical Path**: Focus on user-impacting code
4. **Consider Trade-offs**: Memory vs. speed vs. complexity
5. **Verify Improvements**: Ensure changes actually help

## Algorithmic Optimization

### Complexity Analysis
- Analyze time and space complexity
- Identify O(n²) or worse patterns
- Look for redundant computations
- Consider data structure choices

### Common Optimizations
- **Caching**: Store expensive computation results
- **Memoization**: Cache function call results
- **Lazy Evaluation**: Compute only when needed
- **Batching**: Group operations together
- **Precomputation**: Calculate in advance

## Data Structure Selection

### Arrays vs. Linked Lists
- Arrays: Fast random access, slow insertion/deletion
- Linked Lists: Fast insertion/deletion, slow random access

### Hash Tables
- O(1) average case for lookups
- Good for counting, deduplication, caching
- Watch for hash collisions and memory overhead

### Trees
- Balanced trees (AVL, Red-Black): O(log n) operations
- Heaps: O(log n) insert/extract, O(1) find min/max
- Trie: Efficient string prefix operations

### Graphs
- Adjacency list: Good for sparse graphs
- Adjacency matrix: Good for dense graphs
- Choose based on operations needed

## Database Optimization

### Query Optimization
- Use EXPLAIN to analyze query plans
- Add indexes for frequently queried columns
- Avoid SELECT * in production queries
- Use JOINs appropriately
- Limit result sets with pagination

### Connection Management
- Use connection pooling
- Close connections promptly
- Use prepared statements
- Avoid N+1 query problems

### Caching Layers
- Application-level cache (in-memory)
- Redis for distributed caching
- Database query cache
- HTTP cache headers

## Concurrency Optimization

### Parallelism
- Use thread pools for I/O-bound tasks
- Use process pools for CPU-bound tasks
- Avoid shared state when possible
- Use immutable data structures

### Async Programming
- Use async/await for I/O operations
- Non-blocking I/O for high concurrency
- Event loops for handling many connections

### Lock Optimization
- Minimize critical sections
- Use read-write locks
- Prefer lock-free algorithms
- Avoid nested locks (deadlock risk)

## Memory Management

### Memory Leaks
- Track object lifecycles
- Use weak references when appropriate
- Release resources in finally blocks
- Monitor memory usage over time

### Garbage Collection
- Understand GC behavior for your language
- Avoid creating unnecessary objects
- Tune GC parameters for your workload
- Monitor GC pauses

### Memory-Efficient Data Structures
- Use arrays of primitives instead of object arrays
- Compress large datasets
- Stream large files instead of loading entirely
- Use generators/lazy evaluation

## Profiling Tools

### CPU Profiling
- Identify hot functions and code paths
- Measure time spent in each function
- Find recursive or looping bottlenecks

### Memory Profiling
- Track object allocation
- Identify memory leaks
- Measure garbage collection overhead

### Network Profiling
- Measure API response times
- Identify slow endpoints
- Optimize payload sizes

## Optimization Anti-Patterns

1. **Premature Optimization**: Optimizing before measuring
2. **Micro-optimization**: Focusing on minor gains
3. **Over-caching**: Caching everything, managing complexity
4. **Ignoring Readability**: Making code unreadable for speed
5. **Platform Misuse**: Not using language/platform features

## Performance Testing

### Load Testing
- Simulate expected and peak loads
- Measure response times and throughput
- Identify breaking points

### Stress Testing
- Push beyond normal capacity
- Test recovery from failures
- Identify resource exhaustion

### Soak Testing
- Run extended tests (hours/days)
- Identify memory leaks and degradation
- Verify long-term stability
