# JavaScript/TypeScript Engineering Guide

## Code Style
- Use Prettier for formatting
- Use ESLint for linting
- Use TypeScript for type safety
- 2-space indentation
- Use semicolons (consistency)

## TypeScript Best Practices

### Type System
- Use strict mode (`strict: true`)
- Prefer interfaces for object shapes
- Use union types for variant types
- Use generics for reusable components
- Use `unknown` over `any`

### Error Handling
```typescript
async function getUser(id: string): Promise<User | null> {
  try {
    return await repository.findById(id);
  } catch (error) {
    logger.error(`Failed to get user ${id}:`, error);
    return null;
  }
}
```

### Async Programming
- Use `async/await` over Promises
- Use `Promise.all()` for parallel operations
- Handle errors with try/catch
- Use AbortController for cancellation

## Node.js Best Practices

### Project Structure
```
src/
  controllers/
  services/
  repositories/
  models/
  utils/
  middleware/
```

### Express.js Patterns
- Use middleware for cross-cutting concerns
- Use routers for resource grouping
- Use dependency injection
- Validate input with libraries

### Database Access
- Use connection pooling
- Use transactions for atomic operations
- Prefer ORM/ODM or query builders
- Use migrations for schema changes

## Testing
- Use Jest or Vitest
- Mock external dependencies
- Test both success and error cases
- Use describe/it blocks
- Test async code with async/await

## Performance
- Use clustering for CPU-bound tasks
- Use streaming for large files
- Implement caching (Redis)
- Use compression middleware
- Optimize database queries

## Security
- Use Helmet for security headers
- Validate and sanitize inputs
- Use CSRF protection
- Implement rate limiting
- Use JWT securely (HttpOnly, Secure flags)

## Tools
- `typescript`: Type checking
- `eslint`: Linting
- `prettier`: Formatting
- `jest`/`vitest`: Testing
- `nodemon`: Development server
- `pm2`: Process manager