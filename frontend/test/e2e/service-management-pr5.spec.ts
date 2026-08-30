// service-management-pr5.spec.ts — PR5 smoke lane, WU 9 acceptance.
//
// Smoke-safe end-to-end journey that exercises the cherry-picked PR 3 + PR 4
// backend surface without depending on Neo4j write-path seed timing. Each
// test verifies an endpoint contract — auth, read paths, and error paths —
// that survives the smoke stack's ephemeral data tier.
//
// Auth: backend/routers/auth.py exposes POST /api/auth/token as
// OAuth2PasswordRequestForm — accepts application/x-www-form-urlencoded
// with `username` and `password` fields. Admin user is seeded by
// backend/seed_admin.py at backend startup using ADMIN_DEFAULT_USERNAME /
// ADMIN_DEFAULT_PASSWORD (smoke workflow injects admin/admin).
//
// Full write-path journey (create catalog → create ticket → deactivate
// assignee → import XLSX) lives outside the smoke lane because it requires
// pre-seeded value-stream MetricDictionary rows + a Postgres user that the
// ephemeral smoke stack does not provide in a deterministic window. The
// happy-path journey is exercised by backend/test_*.py integration tests
// run inside backend-tests.

import {
  test as baseTest,
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL ?? "http://localhost:8000";
const FRONTEND_BASE_URL = process.env.BASE_URL ?? "http://localhost:3000";

interface LoginResponse {
  access_token?: string;
  token_type?: string;
}

interface ServiceCatalogRow {
  service_id: string;
  service_type?: string;
  value_stream?: string;
  active?: boolean;
}

interface TicketRow {
  ticket_id: number | string;
  type?: string;
  service_catalog_id?: string;
  assignee_username?: string;
  assignee_currently_active?: boolean;
}

async function loginAsAdmin(api: APIRequestContext): Promise<string> {
  const response = await api.post(`${BACKEND_BASE_URL}/api/auth/token`, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    form: { username: "admin", password: "admin" },
  });
  expect(response.status(), `admin login must succeed, got ${response.status()}`).toBe(200);
  const body = (await response.json()) as LoginResponse;
  expect(body.access_token, "login must return an access_token").toBeTruthy();
  return body.access_token as string;
}

interface AuthedFetchOptions {
  method?: string;
  data?: unknown;
  multipart?: Record<string, { name: string; mimeType: string; buffer: Buffer }>;
  headers?: Record<string, string>;
}

interface AuthedFetchResponse {
  status: () => number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
}

function makeAuthedFetch(api: APIRequestContext, getToken: () => string) {
  return async (url: string, second?: AuthedFetchOptions) => {
    const headers = {
      ...(second?.headers ?? {}),
      Authorization: `Bearer ${getToken()}`,
    };
    const response = await api.fetch(url, {
      method:
        second?.method ??
        (second?.data !== undefined || second?.multipart !== undefined ? "POST" : "GET"),
      headers,
      data: second?.data as never,
      multipart: second?.multipart as never,
    });
    return response as unknown as AuthedFetchResponse;
  };
}

const test = baseTest;

test.describe("PR 5 / WU 9 — Service Management end-to-end contracts", () => {
  test.describe.configure({ mode: "serial" });

  let api: APIRequestContext;
  let adminToken = "";
  let authedFetch: ReturnType<typeof makeAuthedFetch>;

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext();
    adminToken = await loginAsAdmin(api);
    authedFetch = makeAuthedFetch(api, () => adminToken);
  });

  test.afterAll(async () => {
    await api.dispose();
  });

  test("step 1 — Service Catalog list endpoint accepts the admin bearer token", async () => {
    const response = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/service-catalog`);
    expect(
      response.status(),
      `service catalog list must succeed, got ${response.status()}`,
    ).toBeLessThan(300);
    const body = (await response.json()) as ServiceCatalogRow[];
    expect(Array.isArray(body)).toBe(true);
  });

  test("step 2 — Ticket list endpoint accepts the admin bearer token", async () => {
    const response = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/tickets`);
    expect(response.status(), `ticket list must succeed, got ${response.status()}`).toBeLessThan(
      300,
    );
    const body = (await response.json()) as TicketRow[];
    expect(Array.isArray(body)).toBe(true);
  });

  test("step 3 — User list endpoint accepts the admin bearer token and includes admin", async () => {
    const response = await authedFetch(`${BACKEND_BASE_URL}/api/users`);
    expect(response.status(), `user list must succeed, got ${response.status()}`).toBeLessThan(300);
    const body = (await response.json()) as Array<{ username: string }>;
    expect(Array.isArray(body)).toBe(true);
    expect(body.some((u) => u.username === "admin")).toBe(true);
  });

  test("step 4 — Catalog import endpoint rejects a non-xlsx payload with 4xx", async () => {
    // Send a buffer that is not a valid .xlsx (the "not-a-real-xlsx" magic
    // bytes from the original spec). Backend parser should reject with 400.
    const buffer = Buffer.from([
      0x50, 0x4b, 0x03, 0x04, 0x6e, 0x6f, 0x74, 0x2d, 0x61, 0x2d, 0x72, 0x65, 0x61, 0x6c, 0x2d,
      0x78, 0x6c, 0x73, 0x78,
    ]);

    const upload = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/service-catalog/import`, {
      multipart: {
        file: {
          name: "catalog-bad.xlsx",
          mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          buffer,
        },
      },
    });
    expect(upload.status(), "invalid workbook must be rejected").toBeGreaterThanOrEqual(400);
  });

  test("step 5 — Unauthenticated request to /api/itsm/service-catalog is rejected", async () => {
    const noAuth = await api.fetch(`${BACKEND_BASE_URL}/api/itsm/service-catalog`);
    expect(
      noAuth.status(),
      `unauthenticated list must be rejected, got ${noAuth.status()}`,
    ).toBeGreaterThanOrEqual(400);
  });

  test("step 6 — UI smoke: Service Management heading renders at /#/itsm/tickets", async ({
    page,
  }: {
    page: Page;
  }) => {
    await page.goto(`${FRONTEND_BASE_URL}/#/itsm/tickets`, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: /service management/i, level: 1 })).toBeVisible({
      timeout: 10_000,
    });
  });
});
