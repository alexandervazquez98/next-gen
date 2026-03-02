# Known Issues & Development Handovers

## Active Bug: SVG Link Animations Frozen in React-Leaflet and D3 (CMDB Graph)

### Description
The topology link animations (representing `DEPENDS_ON` traffic flow and `CONNECTS_TO` traffic blasts) are visually static in both the `MonitoringConsole` (React-Leaflet) and the `GraphCMDB` (D3.js). The underlying telemetry correlation and "Blast Radius" geographical calculations function perfectly, but the visual stroke animations (moving dashes) are blocked by the mapping rendering engines.

### Attempted Solutions (Context for AI Agents / Next Dev)
To avoid redundant work, please note that the following 3 approaches have already been attempted. They all succeed in isolated plain HTML/SVG test panels, but fail inside the component tree:

1. **Pure CSS `stroke-dashoffset` Keyframes**: Failed. Vite/React-Leaflet/D3 continuously re-render the internal SVG `<path>` elements, stripping or freezing the CSS animation loop timing.
2. **Native JS `requestAnimationFrame` and `d3.timer` loops**: Failed. Manually pushing mathematics to the DOM attributes clashes with React's Virtual DOM reconciliation and D3's internal force simulation tick cycles. 
3. **Declarative Native SVG `<animate>` tags**: Failed. Appending native declarative definitions (`<AnimatedPolyline>`) works in the DOM, but the Leaflet SVG OverlayPane and D3 canvas engines suppress their frame ticks.

### Current Functional Status
- The UI accurately paints the links based on the Neo4j relationships.
- Warning/Critical nodes correctly cast a geographical Ping Aura and expand their size.
- Status inheritances and correlated event modals work 100%.

### Recommended Next Steps for AI Agent
- For **Leaflet**: Do not attempt native SVG manipulation. Investigate migrating the links to a specialized plugin like `leaflet-ant-path` which is specifically built to bypass leaflet's vector limitations.
- For **D3**: Investigate detaching the link updates completely from React state variables so the SVGs can breathe outside the Virtual DOM.
