# DevOps & Deployment

## CI/CD Pipeline

### Pipeline Stages
1. **Build**: Compile code, install dependencies
2. **Test**: Run unit and integration tests
3. **Scan**: Security and dependency scanning
4. **Package**: Create deployable artifacts
5. **Deploy**: Push to staging/production
6. **Verify**: Smoke tests and validation

### Best Practices
- Automate everything in the pipeline
- Run tests in parallel where possible
- Use immutable infrastructure
- Deploy frequently (multiple times per day)
- Feature flags for safe deployments

## Infrastructure as Code (IaC)

### IaC Tools
- **Terraform**: Multi-cloud, declarative
- **AWS CloudFormation**: AWS-specific
- **Pulumi**: Programming-based IaC
- **Ansible**: Configuration management

### IaC Principles
- Define infrastructure in code
- Version control infrastructure
- Use modules and reuse
- Test infrastructure changes
- Plan before applying

## Containerization

### Docker Best Practices
- Use multi-stage builds
- Minimize layer count
- Use .dockerignore
- Run as non-root user
- Use health checks
- Set resource limits

### Dockerfile Example
```dockerfile
FROM node:18-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

FROM node:18-alpine

WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY . .

USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

### Orchestration
- **Kubernetes**: Container orchestration
- **Docker Compose**: Local development
- **AWS ECS**: Managed container service
- **Google GKE**: Kubernetes as a service

## Deployment Strategies

### Blue-Green Deployment
- Run two identical production environments
- Switch traffic gradually
- Rollback by switching back
- Zero downtime

### Rolling Update
- Replace instances one at a time
- Maintain capacity during deployment
- Simple rollback

### Canary Deployment
- Deploy to small subset of users
- Monitor for issues
- Gradually increase traffic
- Fast rollback if problems

### Feature Toggles
- Deploy code with features off
- Enable gradually
- No rollback needed
- Complex state management

## Monitoring & Alerting

### Metrics Collection
- Use Prometheus for metrics
- Collect system and application metrics
- Store time-series data
- Visualize with Grafana

### Logging
- Centralized logging (ELK stack, Loki)
- Structured logs (JSON)
- Correlation IDs for tracing
- Log retention policies

### Tracing
- Distributed tracing (Jaeger, Zipkin)
- Track requests across services
- Identify latency bottlenecks

### Alerting
- Define SLOs and error budgets
- Create meaningful alerts
- Avoid alert fatigue
- On-call rotation

## Configuration Management

### Environment Configuration
- Separate config from code
- Use environment variables
- Support multiple environments
- Validate at startup

### Secrets Management
- Use HashiCorp Vault
- AWS Secrets Manager
- Kubernetes Secrets
- Never commit secrets

## Infrastructure Components

### Load Balancing
- Distribute traffic across instances
- Health checks
- SSL termination
- Session affinity (if needed)

### Auto Scaling
- Scale based on metrics (CPU, memory)
- Scale up/down gradually
- Minimum and maximum instances
- Cost optimization

### DNS & CDN
- Use CDN for static assets
- DNS for service discovery
- Load balancing across regions
- Health-based routing

## Backup & Disaster Recovery

### Backup Strategy
- Regular automated backups
- Test backup restoration
- Store backups offsite
- Encrypt backups at rest

### RTO/RPO
- Recovery Time Objective: How fast to recover
- Recovery Point Objective: How much data to lose
- Define for each critical system
- Regularly test recovery

## Cost Optimization

### Strategies
- Rightsize instances
- Use spot instances where possible
- Auto-scale down during low traffic
- Optimize database usage
- Use serverless for variable workloads

### Monitoring Costs
- Track spend by service
- Set budget alerts
- Optimize storage costs
- Use reserved instances for steady workloads

## Deployment Checklist

Before deploying:
- [ ] All tests passing
- [ ] Security scans clean
- [ ] Database migrations ready
- [ ] Rollback plan prepared
- [ ] Monitoring configured
- [ ] Team notified
- [ ] Deployment window scheduled
- [ ] Post-deployment checks defined