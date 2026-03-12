# 01. Proposal: SVG Link Animations Fix (Issue #7)

## 1. Stack Tecnológico Descubierto

**Backend:**
- Framework: FastAPI (Python 3.10+)
- Lenguaje: Python
- BD: Neo4j (Graph Database), TimescaleDB (PostgreSQL 16)
- Dependencias: neo4j, pandas, pysnmp, sqlalchemy, pydantic

**Frontend:**
- Framework: React 18 + Vite + TypeScript
- Estilos: TailwindCSS
- Visualización: 
  - `react-leaflet` + `leaflet` (Mapas geoespaciales)
  - `d3` / `react-force-graph-3d` (Grafos)
  - `recharts` (Gráficos)
- HTTP: REST API

**Despliegue:**
- Docker + Docker Compose

---

## 2. Estructura del Proyecto (File Map)

```
next-gen/
├── backend/
│   ├── main.py                    # FastAPI entry point
│   ├── requirements.txt           # Dependencias Python
│   └── services/                 # Lógica de negocio
├── frontend/
│   ├── components/
│   │   ├── MonitoringConsole.tsx  # Panel principal con mapa Leaflet
│   │   ├── GraphCMDB.tsx          # Visualizador de grafos D3
│   │   ├── TopologyViewer.tsx     # Visor de topología
│   │   └── ...
│   ├── services/                 # API calls
│   └── App.tsx                   # Router principal
├── engines/
│   └── requirements.txt          # SNMP Workers
├── docker-compose.yml            # Orquestación
└── context.md                    # Documentación del sistema
```

---

## 3. Objetivo Principal del Cambio

El issue #7 reporta que las animaciones de enlace SVG (representando flujo de tráfico `DEPENDS_ON` y blasts `CONNECTS_TO`) están **congeladas visualmente** en dos componentes:
- `MonitoringConsole` (React-Leaflet)
- `GraphCMDB` (D3.js)

La telemetría y cálculos de "Blast Radius" funcionan correctamente, pero las animaciones de stroke (dashs moviéndose) son bloqueadas por los motores de renderizado de Leaflet y D3.

### Soluciones Previas Intentadas (FALLARON)
1. **CSS `stroke-dashoffset` Keyframes** — React re-renderiza los elementos SVG internamente, rompiendo la animación
2. **JS `requestAnimationFrame` / `d3.timer`** — Choca con el Virtual DOM de React y los ciclos de D3
3. **SVG nativo `<animate>` tags** — Leaflet SVG OverlayPane y D3 suppressan los frames

### Soluciones Recomendadas
- **Leaflet**: Usar plugin `leaflet-ant-path` (diseñado específicamente para animar vectores en Leaflet)
- **D3**: Decoupling total de las actualizaciones de link del estado de React para que los SVGs existan fuera del Virtual DOM

---

## 4. Propuesta: SVG Link Animations Fix (change-XXX)

### Intención
Habilitar animaciones visuales fluidas en los enlaces topológicos del grafo y el mapa geoespacial, mostrando el flujo de tráfico entre nodos.

### Alcance

**Dentro del alcance:**
- Implementar animaciones en `MonitoringConsole.tsx` usando `leaflet-ant-path`
- Implementar animaciones en `GraphCMDB.tsx` con D3 decoupling del Virtual DOM
- Mantener funcionalidad existente (telemetría, Blast Radius, status inheritances)

**Fuera del alcance:**
- Cambios en backend
- Modificaciones en el modelo de datos Neo4j
- Otras visualizaciones (TopologyViewer, NetworkVisualizer)

### Enfoque Técnico

1. **Para Leaflet (MonitoringConsole):**
   - Instalar `leaflet-ant-path`
   - Reemplazar los `<Polyline>` estáticos por `<AntPath>`
   - Configurar animación de flujo con `delay`, `pulse`, `dashArray`

2. **Para D3 (GraphCMDB):**
   - Usar `useRef` para crear referencias a los elementos SVG
   - Inicializar animaciones D3 en un `useEffect` que NO dependa del estado de React
   - Usar un contenedor separado (portal) para los SVGs animados fuera del Virtual DOM

### Riesgos

| Riesgo | Probabilidad | Mitigación |
|--------|-------------|------------|
| `leaflet-ant-path` no es compatible con la versión de Leaflet | Baja | Verificar versión en package.json antes de instalar |
| Decoupling D3 rompe la sincronización con datos reales | Media | Usar polling o subscriptions para actualizar datos sin re-renderizar |
| Performance al agregar animaciones en múltiples nodos | Media | Limitar animaciones a nodos visibles o en estado activo |

---
