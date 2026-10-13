import { api } from "./clientId";
import { storageGeneration, assertStorageGeneration } from "./accountStorage";

type WorkspaceEnvelope<T> = {
  namespace: string;
  payload: T | null;
  updated_at: string | null;
};

export async function loadWorkspaceState<T>(namespace: string): Promise<T | null> {
  const generation = storageGeneration();
  const response = await api<WorkspaceEnvelope<T>>(
    `/api/account/workspace/${encodeURIComponent(namespace)}`,
  );
  assertStorageGeneration(generation);
  return response.payload ?? null;
}

export async function saveWorkspaceState<T extends Record<string, unknown> | unknown[]>(
  namespace: string,
  payload: T,
): Promise<void> {
  await api(`/api/account/workspace/${encodeURIComponent(namespace)}`, {
    method: "PUT",
    body: JSON.stringify({ payload }),
  });
}
