# 02. Especificaciones Técnicas (Specs)

## S1: MonitoringConsole (Leaflet - React-Leaflet)

### S1.1: Animaciones de Enlaces con leaflet-ant-path

#### Requisito: Visualización de flujo de tráfico
- El sistema DEBE mostrar animaciones de flujo en los enlaces que representan relaciones `DEPENDS_ON` y `CONNECTS_TO`.
- Con estado `normal`: El enlace debe mostrar un flujo continuo de dashes animados.
- Con estado `warning` o `critical`: El enlace debe mostrar un patrón de pulso/ráfaga más rápido para indicar alertas.

#### Escenarios Verificables

| ID | Dado | Cuando | Entonces |
|----|------|--------|----------|
| S1.1.1 | Un enlace entre dos nodos existe en Neo4j | Se renderiza el mapa en MonitoringConsole | El enlace muestra animación de flujo constante |
| S1.1.2 | Un nodo cambia a estado `critical` | El enlace conectado muestra animación de pulso rápido | El patrón de dash se acelera visualmente |
| S1.1.3 | Se agrega un nuevo enlace dinámicamente | El usuario crea un nuevo `DEPENDS_ON` | El nuevo enlace aparece con animación en el mapa |

---

## S2: GraphCMDB (D3 Force Graph)

### S2.1: Animaciones de Enlaces con D3 Decoupling

#### Requisito: Animación de tráfico sin re-renders de React
- El sistema DEBE mostrar animaciones en los enlaces del grafo D3 sin depender del Virtual DOM.
- Con datos actualizados: Los enlaces deben mantener su animación mientras los datos se actualizan en background.
- Con enlaces agregados/eliminados: Las animaciones deben comenzar/detener sin reconstruir todo el grafo.

#### Escenarios Verificables

| ID | Dado | Cuando | Entonces |
|----|------|--------|----------|
| S2.1.1 | El grafo D3 se renderiza con nodos y enlaces | Se carga GraphCMDB | Los enlaces muestran dashes animados fluyendo |
| S2.1.2 | Los datos del grafo se actualizan (polling) | Llegan nuevos datos de la API | Las animaciones continúan sin interrupciones |
| S2.1.3 | Un enlace se elimina | Se remueve una relación en Neo4j | El enlace desaparece suavemente sin re-render completo |

---

### S2.2: Sincronización de Estado

#### Requisito: Datos en tiempo real
- El sistema DEBE mantener los datos del grafo sincronizados con Neo4j.
- Con polling cada 30s: Los nodos y enlaces deben reflejar el estado actual.
- Con errores de conexión: El sistema debe mantener la última versión conocida del grafo.

#### Escenarios Verificables

| ID | Dado | Cuando | Entonces |
|----|------|--------|----------|
| S2.2.1 | Un nodo cambia de estado | Poll de la API | El nodo cambia de color en el grafo |
| S2.2.2 | Conexión a Neo4j falla | Error de red | Se muestra mensaje de error, grafo permanece legible |

---

## S3: Rendimiento

### S3.1: Performance con muchos nodos

#### Requisito: Animaciones fluidas
- El sistema DEBE mantener 60fps en animaciones con hasta 100 nodos visibles.
- Con más de 100 nodos: Las animaciones pueden deshabilitarse automáticamente para nodos no visibles.

#### Escenarios Verificables

| ID | Dado | Cuando | Entonces |
|----|------|--------|----------|
| S3.1.1 | 50 nodos y 80 enlaces | Se renderiza el grafo | Las animaciones son fluidas (60fps) |
| S3.1.2 | 200 nodos | Zoom out del grafo | Las animaciones se deshabilitan en nodos fuera del viewport |
