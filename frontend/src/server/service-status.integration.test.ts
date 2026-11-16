// @vitest-environment node
import { readFileSync } from "node:fs";
import { PGlite } from "@electric-sql/pglite";

const migration = readFileSync(new URL("../../prisma/migrations/20261013120000_add_service_statuses/migration.sql", import.meta.url), "utf8");
const initialStatus = new URL("../../../deploy/vps/initial-service-status.sql", import.meta.url);

describe("private installation status initialization", () => {
  let db: PGlite;
  beforeEach(async () => {
    db = new PGlite();
    await db.exec(migration);
    await db.exec("CREATE TABLE users (id TEXT PRIMARY KEY)");
  });
  afterEach(async () => { await db.close(); });

  it("does not report an upstream incident on a fresh installation", async () => {
    await db.exec(readFileSync(initialStatus, "utf8"));
    expect((await db.query("SELECT status, headline FROM service_statuses")).rows).toEqual([{ status: "operational", headline: "No incident reported" }]);
  });

  it("preserves an existing owner's status even when it matches the old seed", async () => {
    await db.exec("INSERT INTO users VALUES ('owner')");
    await db.exec(readFileSync(initialStatus, "utf8"));
    expect((await db.query("SELECT status FROM service_statuses")).rows).toEqual([{ status: "degraded" }]);
  });

  it("preserves a custom incident on an unclaimed installation", async () => {
    await db.exec("UPDATE service_statuses SET headline = 'Local maintenance'");
    await db.exec(readFileSync(initialStatus, "utf8"));
    expect((await db.query("SELECT headline FROM service_statuses")).rows).toEqual([{ headline: "Local maintenance" }]);
  });
});

describe("service status migration", () => {
  let db: PGlite;
  beforeAll(async () => { db = new PGlite(); await db.exec(migration); });
  afterAll(async () => { await db.close(); });

  it("seeds degraded downloads and preserves an operator's resolution when reapplied", async () => {
    expect((await db.query("SELECT id, status FROM service_statuses")).rows).toEqual([{ id: "video-downloads", status: "degraded" }]);
    await db.exec("UPDATE service_statuses SET status = 'operational', headline = 'Resolved', description = 'Downloads are working normally.', updated_at = CURRENT_TIMESTAMP WHERE id = 'video-downloads'");
    await db.exec(migration);
    expect((await db.query("SELECT status, headline FROM service_statuses")).rows).toEqual([{ status: "operational", headline: "Resolved" }]);
  });

  it("rejects unsupported status values", async () => {
    await expect(db.exec("UPDATE service_statuses SET status = 'typo' WHERE id = 'video-downloads'")).rejects.toThrow();
  });
});
