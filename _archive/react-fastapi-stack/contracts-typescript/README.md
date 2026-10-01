# Generated API contracts

`api.d.ts` is generated from `apps/api`'s live OpenAPI schema. **Do not
hand-edit** -- changes will be overwritten the next time this is run.

Regenerate (with the FastAPI dev server running on :8000):

```
npm run gen:contracts --prefix apps/web
```

This is what makes `03-system-architecture.md`'s AD-1 literally true:
`apps/web` imports types only from `packages/contracts`, never directly
from `apps/api`'s internal Pydantic models.
