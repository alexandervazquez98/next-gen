# 📋 Informe Ejecutivo de Consultoría AIOps & ITIL 4
**Dirigido a:** Junta Directiva y Dirección de Operaciones IT
**Plataforma Analizada:** NEX-GEN ITOM
**Autor:** CTO & Consultor Senior ITIL 4 / AIOps

---

## 📌 1. Diagnóstico de Operaciones Actuales (Resumen Ejecutivo)

Considerando la arquitectura implementada bajo el estándar de Antigravity (microservicios, Neo4j, TimescaleDB, React SPA), la base fundacional es extremadamente sólida, disruptiva y va por el camino correcto para habilitar operaciones AIOps. Sin embargo, requiere madurar en su alineación semántica operativa:

### 1.1 Gestión de CIs (Neo4j): Integridad del Grafo y Reconciliación
La integridad estructural de usar dependencias topológicas explícitas (`DEPENDS_ON`, `HOSTED_ON`, `CONNECTS_TO`) enriquece drásticamente la capacidad de análisis. La reconciliación automática mediante la lógica `HAS_METRIC` (asignación dinámica por Marca/Modelo o explícita) es muy robusta para **prevenir silos técnicos u operativos**. Al automatizar la telemetría se garantiza que lo que existe, se monitorea.
*   **Diagnóstico de Silos de Datos:** Aunque la parte inferior de la infraestructura está reconciliada, la abstracción topológica no es suficiente por sí misma para prevenir **silos a nivel de negocio**. Si estas cadenas de CIs estrictamente técnicos no terminan convergiendo formalmente en nodos que representen a los Servicios de Negocio (`Business Services`) o Productos, la operación continuará ciega frente a la criticidad real de las caídas.

### 1.2 Gestión de Eventos y Enriquecimiento
La plataforma adopta el ciclo de vida transaccional estándar de ITIL (Open, Ack, Closed); sin embargo, el enfoque actual presenta riesgos de "esquizofrenia de datos" en caso de incidentes masivos.
*   **Diagnóstico Contextual (TimescaleDB):** El diseño arquitectónico indica que los flujos AIOps (Worker) generan eventos en Neo4j, pero la traza profunda del evento reside en PostgreSQL/Timescale. Si durante un estado `Open` o `Ack` no se presenta automáticamente al operador una ingesta semántica de la telemetría previa a la caída, el equipo Tier 1 debe saltar a las consolas de gráficas para diagnosticar. Los eventos carecen del enriquecimiento forense vital que proporciona la Time-Series en el primer punto de contacto.

### 1.3 Visualización Situacional (UI: D3-Force y Leaflet)
La fusión de cartografía geográfica y topología relacional provee un panel operacional rico; no obstante, sufre de falta de enfoque prescriptivo bajo situaciones de alto estrés (P1/Incidentes Críticos).
*   **Falta de Identificación del "Radio de Explosión" (Blast Radius):** Mapear el grafo en D3-Force visualiza el ecosistema completo, pero cuando un nodo entra en modo crítico, sin un mecanismo analítico en cascada, provoca excesivo ruido visual cognitivo (efecto "Bola de pelo"). Las herramientas actuales dibujan infraestructuras completas en vez de proporcionar flujos guiados en torno de las ramas relacionales afectadas y filtrando lo irrelevante.

---

## 🔍 2. Análisis de Brechas (Gap Analysis)

| Analítica / Operación | Estado Actual (NEX-GEN v1) | Impacto / Riesgo del Gap (Flaquezas) | Solución Propuesta (Puntos a Mejorar) |
| :--- | :--- | :--- | :--- |
| **Correlación SNMP vs Impacto de Negocio** | El Worker realiza sondeo asíncrono sobre CIs físicos y levanta alarmas puramente técnicas (Ej. puerto de switch down). | **Flaqueza Crítica:** Imposibilidad de discernir instantáneamente si un OID SNMP caído es un componente ocioso o el core de transacciones bancarias. Priorización a ciegas. | Extender la ontología en Neo4j enlazando flujos de red hacia Módulos y Categorías de Servicio a nivel empresarial. |
| **Rendimiento de Consultas Híbridas (SQL + Cypher)** | El Frontend debe consultar primero a Neo4j para mapear dependencias y, en paralelo/síncrono, ir a TimescaleDB para las proyecciones. | **Punto a Mejorar:** Alta o latencia impredecible limitando renderizado instantáneo en los dashboards masivos como `GlobalInventory`. | **Federación de Datos:** Crear vistas materializadas en backend o implementar un patrón Gateway/Redis donde el estado híbrido de "Último Minuto" sea pre-procesado. |
| **AIOps Reactivo vs Predictivo** | El Analytics Worker sondea actualmente solo ante estado "CRITICAL" para proveer su simulación predictiva/Fix. | **Flaqueza:** Reacciona cuando el impacto o degradación total es inminente o ya sucedió, violando el principio 1 de AIOps. | Análisis de pendientes y microdegradaciones asíncronas de la tendencia en TimescaleDB. |

---

## 🚀 3. Roadmap de Evolución (Hacia ITIL & Automatización AIOps)

El diseño propuesto busca maximizar el valor de la arquitectura híbrida hacia una matriz autónoma:

### 3.1 CMDB de Próxima Generación: Análisis de Impacto Automático Preemptivo
Dado el poder del motor de dependencias intrínseco en la base de `Grafos`, estableceremos preanálisis antes de cruzar los umbrales de interrupción absolutos. 
Cuando el sondeo identifique métricas degradadas con un vector predictivo negativo persistente, disparará el **Análisis de Impacto Topológico**:
```cypher
MATCH (source:CI)-[:DEPENDS_ON|CONNECTS_TO*1..5]->(affected:Service)
WHERE source.health = 'DEGRADED'
RETURN affected.name, affected.criticality
```
*   **Objetivo:** Esto prealertará al respectivo `OwnerGroup` para escalar un proceso de mitigación sin el disparo en firme de una caída "Down".

### 3.2 Gestión de Incidentes y Ticketing Automático (Auto-Ticketing)
Transformar `Event Management` simple en una canalización de ITIL Service Operation:
*   **Nueva Entidad Estructural (`Ticket`)**: Un evento prolongado creará un nodo representativo de incidente en Neo4j bajo la nomenclatura `(t:Ticket)-[:RESOLVES]->(e:Event)`. La entidad `Ticket` se conectará dinámicamente mediante `[:ASSIGNED_TO]` al `OwnerGroup` responsable calculado a partir del CI.
*   **Empaquetamiento de Evidencias de Diagnóstico (TimescaleDB)**: Al momento milisegundo en que se crea el Auto-Ticket, el backend (`Analytics Worker`) interrogará TimescaleDB por los datos desde T-15 minutos a T+1 minuto. Estos datos (ej. curva paramétrica de SNMP) conformarían un JSON Inmutable que se inyectará como propiedad estática `diagnostic_evidence_snapshot` directamente en el nodo `(t:Ticket)`. Esto bloquea el estado exacto del evento aislando a L1/L2 de latencias extrañas si se elimina la retención histórica del recolector.

### 3.3 Visualización Avanzada: El Blast Radius Topológico y Capas Técnicas
El Control de Mando visual dejará de ser pasivo para convertirse en orientador mediante filtrado heurístico:
*   **Mapas de Calor Activos (Leaflet Heatmaps)**: Utilizar los incidentes activos ponderados por su severidad para alimentar motores de polígonos o WebGL sobre Leaflet. En vez de iconografía aislada, mostrar áreas "al rojo vivo" para denotar fallas troncales de infraestructura geográfica que colateralizan muchos CIs.
*   **Topological Dimming (D3-Force)**: Al abrirse un incidente mayor, el frontend aplicará filtrado topológico opacando automáticamente (>90% de transparencia) cualquier parte del grafo no impactada directamente y resaltará lumínicamente el CI de origen junto con toda la estructura de árbol derivada usando bordes en pulsación roja y amarilla para clarificar instantáneamente el verdadero Radio de Explosión.

---

## ☑️ Checklist del Roadmap de Implementación Estructurado

### Fase 1: Arquitectura Ontológica e Indexado (Semanas 1-2)
- [ ] Incorporar el metanodo tipado `BusinessService` a la base de datos de grafos Neo4j.
- [ ] Relacionar los `CIs` críticos subyacentes con `BusinessService` usando el Edge `[:DEPENDS_ON]`.
- [ ] Implementar la consulta híbrida Cypher de "Blast Radius Recursivo" para exponer los clústers impactados en una única llamada API `(/api/v1/topology/blast-radius)`.

### Fase 2: Automatización y Enriquecimiento (Semanas 3-5)
- [ ] Actualizar Event Management para invocar el "Auto-Ticketing" basado en un temporizador de gravedad/permanencia.
- [ ] Configurar entidad `(t:Ticket)` y sus metadatos ITIL en el modelo Pydantic del Backend.
- [ ] Desarrollar la sub-función asíncrona que extraiga fragmentos históricos pre-error de TimescaleDB y los incruste como payload JSON estático (`diagnostic_evidence_snapshot`) dentro del nodo Ticket en Neo4j.

### Fase 3: Visualización Táctica de Alertas (Semanas 6-7)
- [ ] Refactorizar el componente `GraphCMDB` (D3) para admitir la funcionalidad "Topological Focus" (Dimming a nodos sanos o no relacionados al path en error).
- [ ] Interfazar el módulo `MonitoringConsole` e instalar plugin de "Heatmap" (e.g. `leaflet.heat`) atado al feed streaming/websockets de eventos para generar mapas calientes según la saturación de los incidentes en determinadas sucursales.
