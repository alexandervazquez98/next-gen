import React, { useState, useEffect, useRef } from 'react';
import { GraphNode } from '../types';
import { fetchNodesSearch } from '../services/queryResources';

interface MultiSelectCIsProps {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  availableNodes?: GraphNode[];
  maxCIs?: number;
}

const MultiSelectCIs: React.FC<MultiSelectCIsProps> = ({
  selectedIds,
  onChange,
  availableNodes = [],
  maxCIs = 10,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState<GraphNode[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced search effect
  useEffect(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    if (!searchTerm.trim()) {
      setSearchResults([]);
      setIsSearching(false);
      setSearchError(null);
      return;
    }

    if (searchTerm.length < 2) {
      setSearchResults([]);
      setIsSearching(false);
      setSearchError(null);
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    debounceTimerRef.current = setTimeout(() => {
      setIsSearching(true);
      setSearchError(null);

      fetchNodesSearch({ q: searchTerm, signal: controller.signal })
        .then((results) => {
          // Filter out already selected nodes
          const filtered = results.filter(r => !selectedIds.includes(r.id));
          setSearchResults(filtered);
          setIsSearching(false);
        })
        .catch((err) => {
          if (err.name !== 'AbortError') {
            console.error('Search failed:', err);
            setSearchError(err.message || `Error`);
            setSearchResults([]);
          }
          setIsSearching(false);
        });
    }, 300);

    return () => {
      controller.abort();
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [searchTerm, selectedIds]);

  const handleAddNode = (nodeId: string) => {
    if (selectedIds.length >= maxCIs) return;
    if (selectedIds.includes(nodeId)) return;
    onChange([...selectedIds, nodeId]);
    setSearchTerm('');
    setSearchResults([]);
  };

  const handleRemoveNode = (nodeId: string) => {
    onChange(selectedIds.filter(id => id !== nodeId));
  };

  const displayNodes = searchResults.length > 0 ? searchResults : availableNodes;
  const selectedNodesMap = new Map(selectedIds.map(id => [id, availableNodes.find(n => n.id === id)]));

  return (
    <div className="space-y-3">
      {/* Search Input */}
      <div className="relative">
        <input
          type="text"
          role="searchbox"
          name="ci-multi-search"
          aria-label="Search CIs to add"
          placeholder="Search CIs..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          maxLength={200}
          className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 text-sm text-white focus:border-brand-500 outline-none transition-colors placeholder-neutral-500"
          disabled={selectedIds.length >= maxCIs}
        />
        {searchTerm && (
          <button
            onClick={() => { setSearchTerm(''); setSearchResults([]); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-white transition-colors p-1"
            title="Clear search"
          >
            <span className="material-symbols-outlined text-sm">close</span>
          </button>
        )}
      </div>

      {/* Search Status Messages */}
      {isSearching && (
        <p className="text-xs text-neutral-500">Loading...</p>
      )}
      {searchError && (
        <p className="text-xs text-red-400">{searchError}</p>
      )}
      {!isSearching && searchTerm.length >= 2 && searchResults.length === 0 && !searchError && (
        <p className="text-xs text-neutral-500">No results found</p>
      )}

      {/* Search Results Dropdown */}
      {searchResults.length > 0 && (
        <div className="max-h-48 overflow-y-auto bg-black/20 rounded-lg border border-white/5">
          {searchResults.map(n => (
            <button
              key={n.id}
              onClick={() => handleAddNode(n.id)}
              className="w-full text-left p-3 hover:bg-white/5 border-b border-white/5 last:border-b-0 flex items-center gap-2"
            >
              <span className={`w-2 h-2 rounded-full ${n.status === 'OK' ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
              <span className="text-sm text-white">{n.label || n.id}</span>
              <span className="text-[10px] text-neutral-500 font-mono ml-auto">{n.ip || 'No IP'}</span>
            </button>
          ))}
        </div>
      )}

      {/* Available Nodes (when not searching) */}
      {!isSearching && searchResults.length === 0 && availableNodes.length > 0 && (
        <div className="max-h-48 overflow-y-auto bg-black/20 rounded-lg border border-white/5">
          {availableNodes
            .filter(n => !selectedIds.includes(n.id))
            .slice(0, 20)
            .map(n => (
              <button
                key={n.id}
                onClick={() => handleAddNode(n.id)}
                className="w-full text-left p-3 hover:bg-white/5 border-b border-white/5 last:border-b-0 flex items-center gap-2"
                disabled={selectedIds.length >= maxCIs}
              >
                <span className={`w-2 h-2 rounded-full ${n.status === 'OK' ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                <span className="text-sm text-white">{n.label || n.id}</span>
                <span className="text-[10px] text-neutral-500 font-mono ml-auto">{n.ip || 'No IP'}</span>
              </button>
            ))}
        </div>
      )}

      {/* Selected CIs Chips */}
      {selectedIds.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {selectedIds.map(id => {
            const node = selectedNodesMap.get(id);
            return (
              <div
                key={id}
                className="flex items-center gap-2 bg-brand-500/20 border border-brand-500/40 rounded-full px-3 py-1.5 text-sm"
              >
                <span className="w-2 h-2 rounded-full bg-brand-500"></span>
                <span className="text-white font-bold">{node?.label || id}</span>
                <button
                  onClick={() => handleRemoveNode(id)}
                  className="text-neutral-400 hover:text-white transition-colors ml-1"
                  title="Remove"
                >
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Counter */}
      <div className="text-xs text-neutral-500 text-right">
        {selectedIds.length} / {maxCIs} CIs selected
      </div>
    </div>
  );
};

export default MultiSelectCIs;