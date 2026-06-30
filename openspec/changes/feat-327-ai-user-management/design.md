# Design: feat-327-ai-user-management

## Architecture Overview

```
backend/
  routers/permissions.py      ← NEW: GET /permissions/ (enum introspection)
  main.py                     ← ADD: import + app.include_router(permissions.router, prefix="/api")

frontend/
  services/permissions.ts     ← NEW: usePermissions hook (fetch + state)
  components/UserManager.tsx  ← MOD: replace ALL_PERMISSIONS, add AI badge, AI perms block, service-account note
  components/RoleManager.tsx  ← MOD: replace ALL_PERMISSIONS, add expandedRoles state, AI card expand/collapse
```

Data flow:
```
GET /api/permissions/
       │
       ▼
  usePermissions()
  ┌─────────────────────────────────────┐
  │  { human[], ai[], loading, error }  │
  └────────────┬────────────────────────┘
               │
       ┌───────┴───────┐
       ▼               ▼
  UserManager      RoleManager
  (human cats +    (human cats +
   AI block when    AI expand on
   AI role)         AI cards)
```

## Backend Design

### permissions router

```python
# backend/routers/permissions.py
from fastapi import APIRouter, Depends
from models.user import User, UserPermission, AIPermission
from services.auth_service import get_current_active_user

router = APIRouter(
    prefix="/permissions",
    tags=["Permissions"],
    responses={401: {"description": "Not authenticated"}},
)


@router.get("/")
async def get_permissions(current_user: User = Depends(get_current_active_user)):
    """Return all human and AI permission enum values."""
    return {
        "human": [p.value for p in UserPermission],
        "ai": [p.value for p in AIPermission],
    }
```

No database calls. No Pydantic response model (plain dict is fine). The `get_current_active_user` dependency handles 401 for unauthenticated callers — this is exactly the same pattern used by `roles.py` (`list_roles`) and `users.py`.

### main.py registration

Current import line (line 144):
```python
from routers import audit, auth, users, roles, nodes, metrics, catalog, links, events, backup, dictionaries, cis, cli, ai
```

Updated import line:
```python
from routers import audit, auth, users, roles, nodes, metrics, catalog, links, events, backup, dictionaries, cis, cli, ai, permissions
```

Registration — append after `app.include_router(ai.router, prefix="/api")` (line 215):
```python
app.include_router(permissions.router, prefix="/api")
```

This follows the existing convention: one `include_router` call per router, all with `prefix="/api"`, ordered at startup registration.

## Frontend Design

### usePermissions hook / permissions service

```typescript
// frontend/services/permissions.ts
import { useState, useEffect } from 'react';
import { api } from './api';

export interface PermissionsResponse {
  human: string[];
  ai: string[];
}

export interface UsePermissionsResult extends PermissionsResponse {
  loading: boolean;
  error: string | null;
}

export function usePermissions(): UsePermissionsResult {
  const [human, setHuman] = useState<string[]>([]);
  const [ai, setAi] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<PermissionsResponse>('/permissions/')
      .then((data) => {
        if (!cancelled) {
          setHuman(data.human);
          setAi(data.ai);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? 'Failed to load permissions');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return { human, ai, loading, error };
}
```

Key decisions:
- Single `useEffect` with empty deps — fetches once per component mount.
- Cancellation flag prevents state updates after unmount.
- Fallback to `[]` on error keeps callers safe (NFR-2).
- Uses existing `api.get<T>()` pattern from `api.ts` (credentials handled automatically via HttpOnly cookie).

### UserManager changes

**Remove** the `ALL_PERMISSIONS` constant (lines 22-27).

**Add** at top of component body:
```typescript
const { human, ai } = usePermissions();

// Derived: is the currently-selected role an AI role?
const activeRole = editingUser ? editingUser.role : newUser.role;
const isAiRole = activeRole.startsWith('AI_');
```

**Build permission categories dynamically** (replaces hardcoded `ALL_PERMISSIONS` usage):
```typescript
const humanCategories = [
  { category: 'Event Management', perms: human.filter(p => ['EVENT_VIEW','EVENT_ACK','EVENT_CLOSE','EVENT_FORCED_CLOSE'].includes(p)) },
  { category: 'CI Management',    perms: human.filter(p => ['CI_VIEW','CI_EDIT','CI_DELETE'].includes(p)) },
  { category: 'Diagnostics',      perms: human.filter(p => p === 'RUN_DIAGNOSTICS') },
  { category: 'System',           perms: human.filter(p => ['USER_MANAGE','ROLE_MANAGE','AUDIT_VIEW'].includes(p)) },
  { category: 'Visualization',    perms: human.filter(p => p === 'METRICS_VIEW') },
];
```

> **Design note**: The category→perm mapping is still local because it is a UI concern (grouping labels), not business logic. The actual permission strings come from the API hook.

**AI permissions block** — conditionally rendered inside the `showPerms` section after all human categories:
```tsx
{isAiRole && (
  <div key="AI Permissions">
    <h5 className="text-[10px] text-brand-400 font-bold uppercase mb-2">AI Permissions</h5>
    <div className="space-y-1">
      {ai.map(p => (
        <label key={p} className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={activeUser.permissions.includes(p)}
            onChange={() => togglePermission(p)}
            className="w-3 h-3 rounded bg-black/40 text-brand-500 border-white/10"
          />
          <span className="text-[10px] text-brand-300">{p}</span>
        </label>
      ))}
    </div>
  </div>
)}
```

**AI badge** in user list table row — rendered after `{u.username}`:
```tsx
<td className="p-4 font-bold text-white">
  {u.username}
  {u.role.startsWith('AI_') && (
    <span className="ml-2 text-[9px] bg-brand-900/60 text-brand-300 border border-brand-500/30 px-1.5 py-0.5 rounded font-bold uppercase">
      AI
    </span>
  )}
</td>
```

**Service-account note** — rendered below the role `<select>` when `isAiRole` and `!editingUser`:
```tsx
{isAiRole && !editingUser && (
  <p className="text-[10px] text-brand-400 mt-1">
    This is a service account. No password login.
  </p>
)}
```

The `password` field is already hidden for `editingUser` — no additional guard needed for existing edit flow.

### RoleManager changes

**Remove** the `ALL_PERMISSIONS` constant (lines 13-19).

**Add** at top of component body:
```typescript
const { human, ai } = usePermissions();
const [expandedRoles, setExpandedRoles] = useState<Set<string>>(new Set());

const toggleExpand = (name: string) => {
  setExpandedRoles(prev => {
    const next = new Set(prev);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    return next;
  });
};
```

**Build human categories** (same pattern as UserManager — replaces `ALL_PERMISSIONS.map(...)` in the edit view):
```typescript
const humanCategories = [
  { category: 'Event Management', perms: human.filter(p => ['EVENT_VIEW','EVENT_ACK','EVENT_CLOSE','EVENT_FORCED_CLOSE'].includes(p)) },
  { category: 'CI Management',    perms: human.filter(p => ['CI_VIEW','CI_EDIT','CI_DELETE'].includes(p)) },
  { category: 'Diagnostics',      perms: human.filter(p => p === 'RUN_DIAGNOSTICS') },
  { category: 'System',           perms: human.filter(p => ['USER_MANAGE','ROLE_MANAGE','AUDIT_VIEW'].includes(p)) },
  { category: 'Visualization',    perms: human.filter(p => p === 'METRICS_VIEW') },
];
```

**AI system role card** — in the role list `map`, after the existing permission tags and before the action buttons:
```tsx
{role.name.startsWith('AI_') && role.is_system && (
  <div className="mb-4">
    <button
      onClick={() => toggleExpand(role.name)}
      className="text-[10px] text-brand-400 hover:text-brand-200 flex items-center gap-1 font-bold uppercase"
      aria-label={`Toggle AI permissions for ${role.name}`}
    >
      <span className="material-symbols-outlined text-sm">
        {expandedRoles.has(role.name) ? 'expand_less' : 'expand_more'}
      </span>
      AI Permissions
    </button>

    {expandedRoles.has(role.name) && (
      <div className="mt-2 space-y-1 pl-2 border-l border-brand-500/20">
        {ai.map(p => (
          <label key={p} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={role.permissions.includes(p)}
              disabled
              className="w-3 h-3 rounded bg-black/40 border-white/10 cursor-not-allowed opacity-60"
            />
            <span className="text-[10px] text-brand-400">{p}</span>
          </label>
        ))}
      </div>
    )}
  </div>
)}
```

## Component State Changes

| Component | New state | Type | Purpose |
|-----------|-----------|------|---------|
| `UserManager` | `human` | `string[]` (from hook) | Human permission values for category rendering |
| `UserManager` | `ai` | `string[]` (from hook) | AI permission values for conditional AI block |
| `RoleManager` | `human` | `string[]` (from hook) | Human permission values for edit-view categories |
| `RoleManager` | `ai` | `string[]` (from hook) | AI permission values for read-only expand blocks |
| `RoleManager` | `expandedRoles` | `Set<string>` | Tracks which AI role card names are expanded |

`loading` and `error` from `usePermissions` are also available but both components can treat `loading: true` as an empty array (graceful no-op render).

## Test Design

### Backend (`backend/tests/test_permissions_router.py`)

Uses the same `TestClient` + `app.dependency_overrides` pattern seen in existing backend tests. The `get_current_active_user` dependency is overridden with a fixture that returns a minimal `User` object.

```python
from fastapi.testclient import TestClient
from main import app
from models.user import User, UserPermission, AIPermission
from services.auth_service import get_current_active_user

def _mock_user():
    return User(username="testuser", role="ADMIN", permissions=[], allowed_locations=[])

client = TestClient(app)

def test_get_permissions_authenticated():
    app.dependency_overrides[get_current_active_user] = _mock_user
    resp = client.get("/api/permissions/")
    assert resp.status_code == 200
    body = resp.json()
    assert "human" in body
    assert "ai" in body

def test_human_permissions_match_enum():
    app.dependency_overrides[get_current_active_user] = _mock_user
    resp = client.get("/api/permissions/")
    assert set(resp.json()["human"]) == {p.value for p in UserPermission}

def test_ai_permissions_match_enum():
    app.dependency_overrides[get_current_active_user] = _mock_user
    resp = client.get("/api/permissions/")
    assert set(resp.json()["ai"]) == {p.value for p in AIPermission}

def test_get_permissions_unauthenticated():
    app.dependency_overrides.pop(get_current_active_user, None)
    resp = client.get("/api/permissions/")
    assert resp.status_code == 401
```

### Frontend (`frontend/components/__tests__/UserManager.test.tsx`)

Pattern follows `AIAgentConsole.test.tsx`: `vi.mock` for dependencies, `render` + `screen` + `fireEvent`/`userEvent`, `waitFor` for async state.

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import UserManager from '../UserManager';

// Mock api module
vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

// Mock usePermissions hook
vi.mock('../../services/permissions', () => ({
  usePermissions: vi.fn(() => ({
    human: ['EVENT_VIEW', 'EVENT_ACK', 'CI_VIEW'],
    ai: ['AI_VIEW_ALL', 'AI_EVENT_ACK'],
    loading: false,
    error: null,
  })),
}));

// Mock useAuth
vi.mock('../../context/AuthContext', () => ({
  useAuth: vi.fn(() => ({ hasPermission: () => true })),
}));
```

Key test structure: seed `api.get` to return a role list including an `AI_AGENT` role and a `VIEWER` role, then trigger `fireEvent.change` on the role selector to drive the `isAiRole` branch.

### Frontend (`frontend/components/__tests__/RoleManager.test.tsx`)

Same mock pattern. `api.get('/roles/')` returns a role with `is_system: true` and `name: 'AI_AGENT'`. Test clicks the expand button and asserts the AI permission checkboxes appear with `disabled` attribute.

### Frontend (`frontend/pages/__tests__/AdminPage.test.tsx`)

Add a module-level mock for `usePermissions` at the top of the test file:
```typescript
vi.mock('../../services/permissions', () => ({
  usePermissions: vi.fn(() => ({ human: [], ai: [], loading: false, error: null })),
}));
```

No other changes required — existing assertions still hold because the hook returns the same data shape as the old static constant.
