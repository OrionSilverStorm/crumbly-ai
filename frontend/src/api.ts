// API client + data hooks. Every number on screen comes from these endpoints; nothing is hard-coded.
import { useCallback, useEffect, useState } from "react";

// Loose JSON shape from the backend (the backend owns the schema).
export type J = any; // eslint-disable-line @typescript-eslint/no-explicit-any

/** GET/POST JSON helper that throws on HTTP errors. */
export async function api(path: string, body?: unknown, method?: string): Promise<J> {
  const res = await fetch(path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

/** Fetch a resource, refetching on `reload()` and optionally every `everyMs`. */
export function useApi(path: string | null, everyMs?: number) {
  const [data, setData] = useState<J>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    if (path) api(path).then(setData, (e) => setError(String(e)));
  }, [path]);
  useEffect(() => {
    reload();
    if (!everyMs) return;
    const t = setInterval(reload, everyMs);
    return () => clearInterval(t);
  }, [reload, everyMs]);
  return { data, error, reload };
}

/** Live incident snapshot: refetches whenever the SSE stream reports a change. */
export function useIncident(id: string) {
  const { data, reload } = useApi(`/api/incidents/${id}`);
  useEffect(() => {
    const es = new EventSource(`/api/incidents/${id}/stream`);
    es.onmessage = () => reload();
    return () => es.close();
  }, [id, reload]);
  return { snap: data, reload };
}
