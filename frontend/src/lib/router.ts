// A two-route router: `/` (agent list) and `/agents/:id` (editor).

import { useSyncExternalStore } from "react";

export type Route = { page: "list" } | { page: "editor"; agentId: string };

function parse(path: string): Route {
  const m = path.match(/^\/agents\/([a-z0-9-]+)\/?$/);
  return m ? { page: "editor", agentId: m[1] } : { page: "list" };
}

const listeners = new Set<() => void>();

function subscribe(fn: () => void) {
  listeners.add(fn);
  window.addEventListener("popstate", fn);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("popstate", fn);
  };
}

export function navigate(path: string) {
  if (path === window.location.pathname) return;
  window.history.pushState(null, "", path);
  listeners.forEach((fn) => fn());
}

export function useRoute(): Route {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname);
  return parse(path);
}
