export const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

export function autocompleteAuthors(query) {
  return request(`/api/autocomplete/authors?q=${encodeURIComponent(query)}`);
}

export function selectFocalScholar(openalexAuthorId) {
  return request("/api/focal/select", {
    method: "POST",
    body: JSON.stringify({ openalex_author_id: openalexAuthorId }),
  });
}

export function fetchMapSnapshot(openalexAuthorId, forceRefresh = false) {
  return request(
    `/api/map?focal_author_id=${encodeURIComponent(openalexAuthorId)}&force_refresh=${forceRefresh}`
  );
}

export function refreshFocalAffiliation(openalexAuthorId) {
  return request(`/api/focal/${encodeURIComponent(openalexAuthorId)}/refresh-affiliation`, {
    method: "POST",
  });
}

export function staticMapSvgUrl(openalexAuthorId) {
  return `${API_BASE}/api/map/static.svg?focal_author_id=${encodeURIComponent(openalexAuthorId)}`;
}
