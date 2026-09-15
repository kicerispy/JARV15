# System Architecture

## Architecture Patterns

### 1. Layered Architecture
Separate concerns into layers:
- **Presentation**: UI, API endpoints
- **Application**: Business logic, use cases
- **Domain**: Core business rules
- **Infrastructure**: External concerns (DB, network, files)

When to use: Enterprise applications, CRUD systems

### 2. Microservices Architecture
Decompose into independently deployable services:
- Each service has its own database
- Services communicate via APIs
- Independent scaling and deployment

When to use: Large systems, independent teams, diverse tech stacks

### 3. Event-Driven Architecture
Components communicate via events:
- Loose coupling between components
- Scalable processing
- Natural fit for real-time systems

When to use: Real-time systems, high-throughput pipelines

### 4. Serverless Architecture
Use managed services instead of servers:
- Function-as-a-Service (AWS Lambda, Azure Functions)
- Managed databases and storage
- Pay-per-use pricing

When to use: Variable workloads, rapid prototyping

## Design Principles

### SOLID
- **S**ingle Responsibility: One reason to change
- **O**pen/Closed: Open for extension, closed for modification
- **L**iskov Substitution: Subtypes must be substitutable
- **I**nterface Segregation: Many client-specific interfaces
- **D**ependency Inversion: Depend on abstractions

### GRASP Principles
- **Information Expert**: Assign responsibility to the class with the needed info
- **Creator**: Class that creates another should have the knowledge
- **Controller**: Mediates between UI and domain
- **Low Coupling**: Minimize dependencies
- **High Cohesion**: Keep related things together
- **Polymorphism**: Use interfaces for varying behavior
- **Pure Fabrication**: Create classes for non-domain concepts
- **Indirection**: Use intermediaries to reduce coupling
- **Protected Variations**: Shield against changes

## Scalability Strategies

### Vertical Scaling
- Add more resources (CPU, RAM) to existing hardware
- Simple but limited by hardware limits

### Horizontal Scaling
- Add more instances of services
- Requires stateless design or distributed state

### Database Scaling
- **Read replication**: Multiple read copies
- **Sharding**: Partition data across databases
- **Caching**: Redis, Memcached for hot data
- **Connection pooling**: Manage database connections efficiently

### Caching Strategy
- **Cache-aside**: Application manages cache
- **Write-through**: Write to cache and database
- **Write-behind**: Write to cache, async write to database
- **TTL**: Set appropriate expiration times

## Database Design

### Normalization
1NF: Atomic columns, no repeating groups
2NF: No partial dependencies
3NF: No transitive dependencies

### Denormalization
- Intentional redundancy for performance
- Precompute and store derived data
- Use when read performance is critical

### Indexing
- Index frequently queried columns
- Composite indexes for multi-column queries
- Monitor index usage and maintenance overhead

## API Design

### RESTful Principles
- Resources identified by URLs
- HTTP methods for actions (GET, POST, PUT, DELETE)
- Stateless interactions
- Consistent naming conventions

### GraphQL
- Flexible queries
- Single endpoint
- Strong typing
- Efficient data fetching

### gRPC
- Binary protocol for performance
- Strong typing with Protocol Buffers
- Streaming support
- Code generation from IDL

## Message Queues

### When to Use
- Decouple services
- Handle peak loads
- Ensure delivery
- Process async tasks

### Popular Options
- RabbitMQ: Feature-rich, complex routing
- Apache Kafka: High-throughput, event streaming
- Amazon SQS: Managed service, simple API
- Redis Streams: Lightweight, fast

## Monitoring & Observability

### Three Pillars
1. **Logging**: Structured, searchable event records
2. **Metrics**: Quantitative measurements over time
3. **Tracing**: Request flow through distributed systems

### Key Metrics
- Latency (p50, p95, p99)
- Throughput (requests/second)
- Error rates
- Resource utilization (CPU, memory, disk)

### Health Checks
- Liveness: Is the process running?
- Readiness: Can it serve traffic?
- Startup: Has initialization completed?

## Configuration Management

### Best Practices
- Use environment variables for secrets
- Separate config from code
- Support multiple environments
- Validate configuration at startup
- Use typed configuration objects

### Tools
- `.env` files for local development
- Kubernetes ConfigMaps/Secrets
- HashiCorp Vault for secrets
- Consul for service discovery