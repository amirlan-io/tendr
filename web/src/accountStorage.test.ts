import { afterEach, describe, expect, it, vi } from "vitest";
import { accountLocalStorage, setAccountStorageScope } from "./accountStorage";
import { hydrateCabinetFromServer, saveLot, loadSavedLots } from "./dashboard/dashboard.data";
vi.mock("./workspaceState", () => ({ loadWorkspaceState: vi.fn().mockResolvedValue(null), saveWorkspaceState: vi.fn().mockResolvedValue(undefined) }));
afterEach(() => { setAccountStorageScope(null); localStorage.clear(); });
describe("account isolation", () => {
  it("does not inherit private data after account switch or logout", () => {
    setAccountStorageScope("account-A");
    saveLot({ id: 1, title: "Private A", savedAt: "2026-10-13" });
    accountLocalStorage.setItem("tendr_ai_chat_sessions:v2", "secret chat");
    setAccountStorageScope("account-B");
    expect(loadSavedLots()).toEqual([]);
    expect(accountLocalStorage.getItem("tendr_ai_chat_sessions:v2")).toBeNull();
    setAccountStorageScope(null);
    expect(loadSavedLots()).toEqual([]);
    expect(Object.values(localStorage)).not.toContain("secret chat");
  });
  it("an empty server workspace never imports cached data", async () => {
    setAccountStorageScope("account-B");
    saveLot({ id: 1, title: "stale", savedAt: "2026-10-13" });
    expect((await hydrateCabinetFromServer()).savedLots).toEqual([]);
  });
});
