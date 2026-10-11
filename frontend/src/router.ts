// Tiny path router: /{sport} and /{sport}/game/{id}. vercel.json rewrites
// every path to index.html, so deep links work without a router library.
export type Route = { sport: string; gameId: string | null };

export function parseRoute(sports: string[]): Route {
  const [sport, kind, id] = window.location.pathname.split("/").filter(Boolean);
  const s = sports.includes((sport ?? "").toLowerCase()) ? sport.toLowerCase() : sports[0];
  return { sport: s, gameId: kind === "game" && id ? id : null };
}

export function navigate(path: string) {
  if (window.location.pathname === path) return;
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0 });
}
