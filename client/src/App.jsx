import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import L from "leaflet";
import {
  autocompleteAuthors,
  fetchMapSnapshot,
  refreshFocalAffiliation,
  selectFocalScholar,
  staticMapSvgUrl,
} from "./api";

const CENTER = [20, 10];
const RECENCY_COLORS = {
  recent: "#1f9d55",
  warm: "#f59e0b",
  older: "#e11d48",
  unknown: "#64748b",
};

function useDebounced(value, delayMs = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

function recencyColor(bucket) {
  return RECENCY_COLORS[bucket] || RECENCY_COLORS.unknown;
}

function markerRadius(collaboratorCount) {
  return Math.max(8, Math.round(7 + Math.sqrt(collaboratorCount) * 3));
}

function formatSuggestion(item) {
  const affiliation = item.affiliation || "Affiliation unknown";
  const country = item.country ? `, ${item.country}` : "";
  const metrics = `Works ${item.works_count ?? 0} | Cited ${item.cited_by_count ?? 0}`;
  return `${item.display_name} - ${affiliation}${country} - ${metrics}`;
}

export default function App() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [selectedAuthor, setSelectedAuthor] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedBlobKey, setSelectedBlobKey] = useState(null);
  const [filters, setFilters] = useState({
    collaboratorName: "",
    yearMin: "",
    yearMax: "",
    minJointPapers: 1,
    country: "",
    betterThanOpenAlexOnly: false,
  });
  const inputRef = useRef(null);
  const debouncedQuery = useDebounced(query);
  const [copyStatus, setCopyStatus] = useState("");
  const [searchStatus, setSearchStatus] = useState("");

  const dynamicPermalink = useMemo(() => {
    const url = new URL(window.location.href);
    if (selectedAuthor?.id) {
      url.searchParams.set("focal", selectedAuthor.id);
    }
    if (filters.collaboratorName) url.searchParams.set("name", filters.collaboratorName);
    if (filters.yearMin) url.searchParams.set("ymin", String(filters.yearMin));
    if (filters.yearMax) url.searchParams.set("ymax", String(filters.yearMax));
    if (filters.minJointPapers) url.searchParams.set("minjp", String(filters.minJointPapers));
    if (filters.country) url.searchParams.set("country", filters.country);
    if (filters.betterThanOpenAlexOnly) url.searchParams.set("better", "1");
    return url.toString();
  }, [selectedAuthor, filters]);

  const staticPermalink = useMemo(
    () => (selectedAuthor?.id ? staticMapSvgUrl(selectedAuthor.id) : ""),
    [selectedAuthor]
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const focal = params.get("focal");
    const nextFilters = {
      collaboratorName: params.get("name") || "",
      yearMin: params.get("ymin") || "",
      yearMax: params.get("ymax") || "",
      minJointPapers: params.get("minjp") || 1,
      country: params.get("country") || "",
      betterThanOpenAlexOnly: params.get("better") === "1",
    };
    setFilters(nextFilters);
    if (!focal) return;
    const load = async () => {
      try {
        setLoading(true);
        const data = await fetchMapSnapshot(focal, false);
        setSelectedAuthor({ id: focal, display_name: data?.focal_author?.display_name || focal });
        setQuery(data?.focal_author?.display_name || "");
        setSnapshot(data);
        setSelectedBlobKey(data.blobs?.[0]?.institution_key || null);
      } catch (loadError) {
        setError(loadError.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  useEffect(() => {
    if (!selectedAuthor?.id) return;
    const url = new URL(dynamicPermalink);
    window.history.replaceState({}, "", `${url.pathname}${url.search}`);
  }, [dynamicPermalink, selectedAuthor]);

  useEffect(() => {
    async function runAutocomplete() {
      if (debouncedQuery.length < 4) {
        setSuggestions([]);
        setActiveIndex(0);
        setSearchStatus("");
        return;
      }
      try {
        setError("");
        const payload = await autocompleteAuthors(debouncedQuery);
        const results = payload.results || [];
        setSuggestions(results);
        setActiveIndex(0);
        if (payload.remote_error) {
          setSearchStatus(payload.remote_error);
        } else {
          setSearchStatus(
            results.length
              ? `Found ${results.length} suggestion(s) via ${payload.remote_source || "search"}.`
              : "No suggestions found for this query yet."
          );
        }
      } catch (fetchError) {
        setError(fetchError.message);
      }
    }
    runAutocomplete();
  }, [debouncedQuery]);

  const runManualSearch = async (value, autoSelectTop = false) => {
    const q = (value || "").trim();
    if (q.length < 4) {
      setSearchStatus("Type at least 4 characters.");
      return;
    }
    try {
      setLoading(true);
      setError("");
      const payload = await autocompleteAuthors(q);
      const results = payload.results || [];
      setSuggestions(results);
      setActiveIndex(0);
      if (payload.remote_error) {
        setSearchStatus(payload.remote_error);
        return;
      }
      if (!results.length) {
        setSearchStatus("No suggestions found. Try another spelling or an OpenAlex author ID.");
        return;
      }
      setSearchStatus(`${results.length} suggestion(s) found via ${payload.remote_source || "search"}.`);
      if (autoSelectTop) {
        await submitSelection(results[0]);
      }
    } catch (manualError) {
      setError(manualError.message);
    } finally {
      setLoading(false);
    }
  };

  const filteredBlobs = useMemo(() => {
    if (!snapshot?.blobs) return [];
    const minYear = Number(filters.yearMin || 0);
    const maxYear = Number(filters.yearMax || 9999);
    const minJointPapers = Number(filters.minJointPapers || 1);

    return snapshot.blobs
      .map((blob) => {
        const people = blob.people.filter((person) => {
          const namePass =
            !filters.collaboratorName ||
            person.display_name.toLowerCase().includes(filters.collaboratorName.toLowerCase());
          const year = Number(person.last_collaboration_year || 0);
          const yearPass = year >= minYear && year <= maxYear;
          const jointPass = Number(person.joint_paper_count || 0) >= minJointPapers;
          const countryPass = !filters.country || (blob.country_name || "").toLowerCase() === filters.country.toLowerCase();
          const betterLinkPass = !filters.betterThanOpenAlexOnly || person.available_links.length > 1;
          return namePass && yearPass && jointPass && countryPass && betterLinkPass;
        });
        return { ...blob, people, collaborator_count: people.length };
      })
      .filter((blob) => blob.collaborator_count > 0);
  }, [snapshot, filters]);

  const selectedBlob = useMemo(
    () => filteredBlobs.find((blob) => blob.institution_key === selectedBlobKey) || null,
    [filteredBlobs, selectedBlobKey]
  );

  const countries = useMemo(() => {
    const unique = new Set();
    (snapshot?.blobs || []).forEach((blob) => {
      if (blob.country_name) unique.add(blob.country_name);
    });
    return [...unique].sort();
  }, [snapshot]);

  const submitSelection = async (candidate) => {
    try {
      setLoading(true);
      setError("");
      setSuggestions([]);
      setQuery(candidate.display_name);
      await selectFocalScholar(candidate.id);
      const data = await fetchMapSnapshot(candidate.id, true);
      setSelectedAuthor(candidate);
      setSnapshot(data);
      setSelectedBlobKey(data.blobs?.[0]?.institution_key || null);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setLoading(false);
    }
  };

  const handleInputKeyDown = (event) => {
    if (loading) return;
    if (event.key === "ArrowDown" && suggestions.length) {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % suggestions.length);
    } else if (event.key === "ArrowUp" && suggestions.length) {
      event.preventDefault();
      setActiveIndex((index) => (index - 1 + suggestions.length) % suggestions.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const candidate = suggestions[activeIndex];
      if (candidate) {
        submitSelection(candidate);
      } else {
        runManualSearch(query, true);
      }
    } else if (event.key === "Escape") {
      setSuggestions([]);
    }
  };

  const handleRefreshAffiliation = async () => {
    if (!selectedAuthor?.id) return;
    try {
      setLoading(true);
      await refreshFocalAffiliation(selectedAuthor.id);
      const data = await fetchMapSnapshot(selectedAuthor.id, false);
      setSnapshot(data);
    } catch (refreshError) {
      setError(refreshError.message);
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = async (value, label) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopyStatus(`${label} copied`);
      setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Clipboard permission blocked");
      setTimeout(() => setCopyStatus(""), 1800);
    }
  };

  useEffect(() => {
    delete L.Icon.Default.prototype._getIconUrl;
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: "",
      iconUrl: "",
      shadowUrl: "",
    });
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="title-wrap">
          <h1>Person-Centric Collaboration Atlas</h1>
          <p>
            OpenAlex-powered map placement from each collaborator&apos;s institution on their most recent joint paper with
            the selected focal scholar.
          </p>
        </div>
        <div className={`search-wrap ${loading ? "search-locked" : ""}`}>
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Type 4+ characters to search OpenAlex authors"
            aria-label="Search scholar"
            disabled={loading}
          />
          <button
            type="button"
            className="search-button"
            onClick={() => runManualSearch(query, false)}
            disabled={loading}
          >
            Search
          </button>
          {suggestions.length > 0 && (
            <ul className="suggestions" role="listbox">
              {suggestions.map((item, index) => (
                <li
                  key={item.id}
                  className={index === activeIndex ? "active" : ""}
                  onMouseDown={() => {
                    if (!loading) submitSelection(item);
                  }}
                  role="option"
                  aria-selected={index === activeIndex}
                >
                  {formatSuggestion(item)}
                </li>
              ))}
            </ul>
          )}
          {searchStatus && <p className="search-status">{searchStatus}</p>}
        </div>
      </header>

      <section className="controls">
        <label>
          Collaborator name
          <input
            value={filters.collaboratorName}
            onChange={(event) => setFilters((prev) => ({ ...prev, collaboratorName: event.target.value }))}
            placeholder="Filter people"
          />
        </label>
        <label>
          Year min
          <input
            type="number"
            value={filters.yearMin}
            onChange={(event) => setFilters((prev) => ({ ...prev, yearMin: event.target.value }))}
          />
        </label>
        <label>
          Year max
          <input
            type="number"
            value={filters.yearMax}
            onChange={(event) => setFilters((prev) => ({ ...prev, yearMax: event.target.value }))}
          />
        </label>
        <label>
          Min joint papers
          <input
            type="number"
            min={1}
            value={filters.minJointPapers}
            onChange={(event) => setFilters((prev) => ({ ...prev, minJointPapers: event.target.value }))}
          />
        </label>
        <label>
          Country
          <select
            value={filters.country}
            onChange={(event) => setFilters((prev) => ({ ...prev, country: event.target.value }))}
          >
            <option value="">All countries</option>
            {countries.map((country) => (
              <option key={country} value={country}>
                {country}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={filters.betterThanOpenAlexOnly}
            onChange={(event) => setFilters((prev) => ({ ...prev, betterThanOpenAlexOnly: event.target.checked }))}
          />
          Has better-than-OpenAlex link
        </label>
        <button onClick={handleRefreshAffiliation} disabled={!selectedAuthor || loading}>
          Refresh focal affiliation
        </button>
        <button onClick={() => copyToClipboard(dynamicPermalink, "Dynamic permalink")} disabled={!selectedAuthor}>
          Copy dynamic permalink
        </button>
        <button onClick={() => copyToClipboard(staticPermalink, "Static image link")} disabled={!selectedAuthor}>
          Copy static image link
        </button>
        <a
          className={`download-btn ${!selectedAuthor ? "disabled-link" : ""}`}
          href={selectedAuthor ? staticPermalink : "#"}
          download={selectedAuthor ? `collab-map-${selectedAuthor.id.split("/").pop()}.svg` : undefined}
          onClick={(event) => {
            if (!selectedAuthor) event.preventDefault();
          }}
        >
          Download static SVG
        </a>
      </section>
      {copyStatus && <p className="copy-status">{copyStatus}</p>}
      {loading && (
        <div className="loading-banner" role="status" aria-live="polite">
          <span className="spinner" />
          Generating map data, please wait...
        </div>
      )}

      {snapshot?.summary && (
        <section className="summary">
          <span>{snapshot.summary.unique_collaborators} unique collaborators</span>
          <span>{snapshot.summary.total_institution_placements} institution placements</span>
          <span>{snapshot.summary.unplaced_collaborators} unplaced collaborators</span>
        </section>
      )}

      {error && <p className="error">{error}</p>}

      <main className="content">
        <div className="map-panel">
          {loading && (
            <div className="map-loading-overlay" role="status" aria-live="polite">
              <span className="spinner large" />
              <span>Generating map...</span>
            </div>
          )}
          <MapContainer center={CENTER} zoom={2} minZoom={2} scrollWheelZoom className="map-root">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {filteredBlobs.map((blob) => {
              if (typeof blob.lat !== "number" || typeof blob.lon !== "number") return null;
              return (
                <CircleMarker
                  key={blob.institution_key}
                  center={[blob.lat, blob.lon]}
                  radius={markerRadius(blob.collaborator_count)}
                  pathOptions={{
                    fillOpacity: 0.75,
                    color: "#0f172a",
                    fillColor: recencyColor(blob.color_bucket),
                    weight: 1,
                  }}
                  eventHandlers={{ click: () => setSelectedBlobKey(blob.institution_key) }}
                >
                  <Popup>
                    <strong>{blob.institution_name}</strong>
                    <br />
                    {blob.country_name || "Country unknown"}
                    {blob.city_name ? (
                      <>
                        <br />
                        {`City fallback: ${blob.city_name} (${blob.city_lat?.toFixed?.(3)}, ${blob.city_lon?.toFixed?.(3)})`}
                      </>
                    ) : null}
                    <br />
                    {blob.collaborator_count} collaborators
                  </Popup>
                </CircleMarker>
              );
            })}
          </MapContainer>
          <div className="legend">
            <span className="legend-item"><i style={{ background: RECENCY_COLORS.recent }} />{"Recent (<=2 years)"}</span>
            <span className="legend-item"><i style={{ background: RECENCY_COLORS.warm }} />{"Warm (3-5 years)"}</span>
            <span className="legend-item"><i style={{ background: RECENCY_COLORS.older }} />{"Older (>5 years)"}</span>
            <span className="legend-item"><i style={{ background: RECENCY_COLORS.unknown }} />Unknown year</span>
            <span className="legend-note">Blob size = collaborators at institution</span>
          </div>
        </div>

        <aside className="side-panel">
          {!selectedBlob && <p>Select a blob to inspect collaborators.</p>}
          {selectedBlob && (
            <>
              <h2>{selectedBlob.institution_name}</h2>
              <p>
                {selectedBlob.country_name || "Country unknown"} - {selectedBlob.collaborator_count} collaborators
              </p>
              <div className="people-list">
                {selectedBlob.people.map((person) => (
                  <div className="person-row" key={person.openalex_author_id}>
                    <div>
                      <strong>{person.display_name}</strong> {person.is_joint_position ? "*" : ""}
                    </div>
                    <div className="person-meta">
                      <span className="badge">{person.last_collaboration_year || "Year n/a"}</span>
                      <span>{person.joint_paper_count} joint papers</span>
                    </div>
                    <a href={person.preferred_url} target="_blank" rel="noreferrer">
                      Open profile
                    </a>
                  </div>
                ))}
              </div>
            </>
          )}
          {snapshot?.unplaced_collaborators?.length > 0 && (
            <>
              <h3>Unplaced collaborators</h3>
              <div className="people-list">
                {snapshot.unplaced_collaborators.map((person) => (
                  <div className="person-row" key={person.openalex_author_id}>
                    <div>{person.display_name}</div>
                    <a href={person.preferred_url} target="_blank" rel="noreferrer">
                      Open profile
                    </a>
                  </div>
                ))}
              </div>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}
