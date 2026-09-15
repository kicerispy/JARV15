# Security Best Practices

## Security Principles

### Defense in Depth
- Multiple layers of security controls
- No single point of failure
- Assume breaches can happen

### Least Privilege
- Grant minimum access needed
- Use role-based access control
- Regularly review permissions

### Fail Securely
- Default to deny access
- Fail closed, not open
- Secure defaults

### Keep It Simple
- Complex security is hard to verify
- Use well-tested libraries
- Avoid custom cryptography

## Authentication

### Password Security
- Use strong password policies
- Hash passwords with bcrypt/scrypt/Argon2
- Never store plaintext passwords
- Implement password reset securely

### Multi-Factor Authentication
- Add second factor (SMS, TOTP, hardware keys)
- Support backup codes
- Allow user recovery options

### Token Management
- Use short-lived JWT tokens
- Implement refresh token rotation
- Store tokens securely (HttpOnly cookies)
- Support token revocation

### Session Management
- Use secure session identifiers
- Implement session expiration
- Invalidate sessions on logout
- Prevent session fixation

## Authorization

### Access Control Models
- **DAC**: Discretionary Access Control
- **MAC**: Mandatory Access Control
- **RBAC**: Role-Based Access Control
- **ABAC**: Attribute-Based Access Control

### Authorization Patterns
- Check permissions at every layer
- Use allowlists over denylists
- Validate user can access resource
- Consider context (time, location, device)

## Data Protection

### Encryption
- Use TLS 1.2+ for network traffic
- Encrypt sensitive data at rest
- Use AES-256 for symmetric encryption
- Use RSA/ECC for asymmetric encryption

### Key Management
- Use hardware security modules (HSMs)
- Rotate keys regularly
- Never commit keys to version control
- Use environment variables or secret stores

### Data Classification
- Public: No protection needed
- Internal: Basic protection
- Confidential: Encryption required
- Restricted: Maximum protection

## Input Validation

### Validation Rules
- Validate on both client and server
- Use allowlist approach
- Validate data type, length, format
- Sanitize input for injection attacks

### Common Attacks
- **SQL Injection**: Use parameterized queries
- **XSS**: Escape output, use CSP headers
- **CSRF**: Use anti-CSRF tokens
- **Path Traversal**: Validate and sanitize paths
- **Command Injection**: Avoid shell execution with user input

## API Security

### REST API Security
- Use HTTPS only
- Implement rate limiting
- Validate and sanitize all inputs
- Use proper HTTP status codes
- Implement proper CORS policies

### Authentication
- Use OAuth 2.0 / OpenID Connect
- Implement API keys for machine-to-machine
- Use JWT with proper signing
- Support scopes and permissions

### Rate Limiting
- Prevent brute force attacks
- Use token bucket or leaky bucket
- Implement per-user and per-IP limits
- Return appropriate retry-after headers

## Dependency Security

### Vulnerability Management
- Use dependency scanning tools
- Keep dependencies updated
- Monitor security advisories
- Have a process for emergency updates

### Supply Chain Security
- Verify package integrity
- Use lock files
- Audit dependencies regularly
- Prefer official package sources

## Monitoring & Incident Response

### Security Monitoring
- Log authentication attempts
- Monitor for suspicious activity
- Set up alerting for anomalies
- Maintain audit trails

### Incident Response
- Have a response plan
- Practice incident scenarios
- Communicate transparently
- Learn from incidents

## Security Checklist

For every feature:
- [ ] Authentication required?
- [ ] Authorization checked?
- [ ] Input validated?
- [ ] Output escaped?
- [ ] Secrets not exposed?
- [ ] Dependencies secure?
- [ ] Error messages safe?
- [ ] Logging appropriate?
- [ ] Rate limiting in place?