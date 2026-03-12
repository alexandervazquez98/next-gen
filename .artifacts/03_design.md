# 03. Diseño de Software (Design)

## D1: MonitoringConsole - Leaflet Integration

### D1.1: leaflet-ant-path Implementation

**Responsabilidades:**
- Reemplazar componentes `<Polyline>` estáticos por `<AntPath>` animados
- Configurar patrones de animación según el estado del nodo
- Manejar lifecycle de las animaciones

**Firma Propuesta (TypeScript):**
```typescript
// En MonitoringConsole.tsx
import { AntPath } from 'leaflet-ant-path';

interface LinkProps {
  id: string;
  source: [number, number];  // lat, lng
  target: [number, number];
  status: 'normal' | 'warning' | 'critical';
  type: 'DEPENDS_ON' | 'CONNECTS_TO';
}

// Configuración de animación por estado
const getPulseOptions = (status: string) => {
  if (status === 'critical') {
    return { delay: 1000, pulseColor: '#ff0000', weight: 4 };
  } else if (status === 'warning') {
    return { delay: 2000, pulseColor: '#ffa500', weight: 3 };
  }
  return { delay: 3000, pulseColor: '#3388ff', weight: 2 };
};
```

---

## D2: GraphCMDB - D3 Decoupling

### D2.1: Portal Pattern para SVG Animations

**Decisión:** Usar React Portal para renderizar los SVGs animados fuera del Virtual DOM principal, permitiendo que D3 manipule el DOM directamente sin interferir con React.

**Rationale:** Las animaciones D3 necesitan acceso directo al DOM. El Virtual DOM de React interfiere porque re-renderiza los elementos, reseteando las animaciones. Un Portal permite que los SVGs existan fuera del tree de React mientras reciben datos actualizados.

**Pseudocódigo:**
```typescript
// En GraphCMDB.tsx
import { createPortal } from 'react-dom';

const AnimatedLinksLayer = ({ links, dataRef }) => {
  const svgRef = useRef(null);
  
  // Este effect NO depende del estado de React - solo de dataRef
  useEffect(() => {
    if (!svgRef.current) return;
    
    const svg = d3.select(svgRef.current);
    
    links.forEach(link => {
      // Animación D3 pura - no re-renders de React
      svg.select(`#link-${link.id}`)
        .transition()
        .duration(1000)
        .attrTween('stroke-dashoffset', /* ... */);
    });
  }, []); // Array vacío = solo una vez al montar
  
  // Render en un portal fuera del Virtual DOM
  return createPortal(
    <svg ref={svgRef} className="animated-links-layer">
      {links.map(link => (
        <path
          id={`link-${link.id}`}
          d={link.path}
          className={`link link-${link.status}`}
        />
      ))}
    </svg>,
    document.getElementById('d3-portal-root')
  );
};
```

---

## D3: API Integration

### D3.1: Sincronización de Datos

**Firma Propuesta:**
```typescript
// Polling hook para datos del grafo
const useGraphData = (pollInterval: number = 30000) => {
  const [data, setData] = useState({ nodes: [], links: [] });
  
  useEffect(() => {
    const fetchData = async () => {
      const response = await fetch('/api/topology');
      const result = await response.json();
      setData(result);
    };
    
    const interval = setInterval(fetchData, pollInterval);
    fetchData(); // Initial fetch
    
    return () => clearInterval(interval);
  }, [pollInterval]);
  
  return data;
};
```

---

## D4: Resumen de Cambios de Archivos

| Archivo | Acción | Descripción |
|---------|--------|-------------|
| `frontend/package.json` | MODIFICADO | Agregar dependencia `leaflet-ant-path` |
| `frontend/components/MonitoringConsole.tsx` | MODIFICADO | Reemplazar Polyline por AntPath con animaciones |
| `frontend/components/GraphCMDB.tsx` | MODIFICADO | Agregar Portal pattern y D3 animations decoupling |
| `frontend/index.html` | MODIFICADO | Agregar div raíz para el portal D3 |
