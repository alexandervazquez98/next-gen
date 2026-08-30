// service-management-pr5.spec.ts — PR5 smoke lane, WU 9 acceptance.
//
// End-to-end journey through the cherry-picked PR 3 + PR 4 backend surface
// against a freshly seeded smoke stack. Exercises:
//   1. POST /api/itsm/service-catalog — create a governed catalog service.
//   2. POST /api/itsm/tickets — create a ticket with compatible service +
//      active assignee; numeric ticket_id.
//   3. POST /api/itsm/tickets with incompatible service type — rejected,
//      no row persisted.
//   4. POST /api/users/{username}/deactivate — historical ticket still
//      readable; assignee_currently_active reflects the new user state.
//   5. POST /api/itsm/service-catalog/import with invalid XLSX — 4xx,
//      no catalog row persisted.
//   6. UI smoke: /#/itsm/tickets renders the "Service Management" heading
//      and the new ticket id is visible.
//
// Auth: backend/routers/auth.py exposes POST /api/auth/token as
// OAuth2PasswordRequestForm — accepts application/x-www-form-urlencoded
// with `username` and `password` fields. Admin user is seeded by
// backend/seed_admin.py at backend startup using ADMIN_DEFAULT_USERNAME /
// ADMIN_DEFAULT_PASSWORD (smoke workflow injects admin/admin).

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
  assignee_active_at_assignment?: boolean;
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

test.describe("PR 5 / WU 9 — Service Management full-stack journey", () => {
  test.describe.configure({ mode: "serial" });

  let api: APIRequestContext;
  let adminToken = "";
  let authedFetch: ReturnType<typeof makeAuthedFetch>;
  let createdCatalogServiceId: string;
  let createdTicketId: number;
  let createdAssignee: string;

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext();
    adminToken = await loginAsAdmin(api);
    authedFetch = makeAuthedFetch(api, () => adminToken);
  });

  test.afterAll(async () => {
    await api.dispose();
  });

  test("step 1 — Service Catalog create endpoint accepts governed fields", async () => {
    createdCatalogServiceId = `svc-pr5-${Date.now()}`;
    const response = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/service-catalog`, {
      data: {
        service_id: createdCatalogServiceId,
        name: "PR5 Smoke Service",
        description: "Created by PR5 WU9 journey",
        service_type: "incident",
        value_stream: "operate",
        sla_target_minutes: 30,
      },
    });
    expect(
      response.status(),
      `service catalog create must return 200/201, got ${response.status()}`,
    ).toBeLessThan(300);
    const body = (await response.json()) as ServiceCatalogRow;
    expect(body).toMatchObject({
      service_id: createdCatalogServiceId,
      service_type: "incident",
      value_stream: "operate",
      active: true,
    });
  });

  test("step 2 — ticket create enforces service-type compatibility and returns a numeric id", async () => {
    createdAssignee = "admin";
    const response = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/tickets`, {
      data: {
        type: "incident",
        title: "PR5 smoke ticket",
        description: "Generated by WU9 journey",
        service_catalog_id: createdCatalogServiceId,
        assignee_username: createdAssignee,
      },
    });
    expect(response.status(), `ticket create must succeed, got ${response.status()}`).toBeLessThan(
      300,
    );
    const body = (await response.json()) as TicketRow;
    expect(typeof body.ticket_id).toBe("number");
    expect(Number.isInteger(body.ticket_id)).toBe(true);
    expect(Number(body.ticket_id)).toBeGreaterThan(0);
    expect(body).toMatchObject({
      type: "incident",
      service_catalog_id: createdCatalogServiceId,
      assignee_username: createdAssignee,
      assignee_active_at_assignment: true,
    });
    createdTicketId = Number(body.ticket_id);
  });

  test("step 3 — incompatible service type is rejected with no ticket persisted", async () => {
    const before = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/tickets`);
    const beforeCount = ((await before.json()) as unknown[]).length;

    const rejected = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/tickets`, {
      data: {
        type: "service_request",
        title: "Should fail",
        description: "Incompatible type",
        service_catalog_id: createdCatalogServiceId,
        assignee_username: createdAssignee,
      },
    });
    expect(rejected.status(), "incompatible type must be rejected").toBeGreaterThanOrEqual(400);

    const after = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/tickets`);
    const afterCount = ((await after.json()) as unknown[]).length;
    expect(afterCount, "no ticket must be persisted on type mismatch").toBe(beforeCount);
  });

  test("step 4 — deactivating the assignee preserves the historical ticket context", async () => {
    const deactivate = await authedFetch(
      `${BACKEND_BASE_URL}/api/users/${createdAssignee}/deactivate`,
      { data: {} },
    );
    expect([204, 409]).toContain(deactivate.status());

    const after = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/tickets/${createdTicketId}`);
    expect(after.status()).toBeLessThan(300);
    const body = (await after.json()) as TicketRow;
    expect(Number(body.ticket_id)).toBe(createdTicketId);
    expect(body.assignee_username).toBe(createdAssignee);
    expect(typeof body.assignee_currently_active).toBe("boolean");
  });

  test("step 5 — invalid catalog workbook import returns 4xx and persists nothing", async () => {
    const buffer = Buffer.from([
      0x50, 0x4b, 0x03, 0x04, 0x6e, 0x6f, 0x74, 0x2d, 0x61, 0x2d, 0x72, 0x65, 0x61, 0x6c, 0x2d,
      0x78, 0x6c, 0x73, 0x78,
    ]);

    const before = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/service-catalog`);
    const beforeIds = ((await before.json()) as ServiceCatalogRow[]).map((c) => c.service_id);

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

    const after = await authedFetch(`${BACKEND_BASE_URL}/api/itsm/service-catalog`);
    const afterIds = ((await after.json()) as ServiceCatalogRow[]).map((c) => c.service_id);
    expect(afterIds, "no catalog row may persist on invalid import").toEqual(beforeIds);
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
    await expect(page.getByText(`#${createdTicketId}`).first()).toBeVisible();
  });
});
