# Contexto del Sistema: Plataforma de Gestión de Operaciones IT (NEX-GEN)

## 1. Visión General
NEX-GEN es una plataforma avanzada de gestión de operaciones de TI (ITOM) que integra una CMDB basada en grafos (Neo4j), telemetría en tiempo real y diagnósticos asistidos. Su objetivo es proporcionar una visión holística de la infraestructura, permitiendo visualizar dependencias, monitorear el estado de los componentes y gestionar incidentes de manera eficiente.

## 2. Arquitectura del Sistema

El sistema sigue una arquitectura de microservicios moderna:

### 2.1 Backend (API & Lógica de Negocio)
- **Tecnología**: Python 3.10+ con FastAPI.
- **Ubicación**: `backend/main.py`
- **Funciones Principales**:
    - **API REST**: Expone endpoints para el Frontend.
    - **Gestor de Grafos**: Interactúa con Neo4j para gestionar CIs (Configuration Items) y sus relaciones.
    - **Colector SNMP**: Servicio en segundo plano (`snmp_collector_loop`) que consulta dispositivos periódicamente.
    - **Gestor de Eventos**: Procesa alertas, correlaciona incidentes y gestiona el ciclo de vida de los eventos (Open, Ack, Closed).
    - **Gestión de Autenticación**: Utiliza PostgreSQL como fuente principal de verdad (Primary Auth Store) apoyado en JWT asimétrico, requiriendo el uso mandatorio de credenciales rotadas expuestas desde un `.env` local.

### 2.2 Frontend (Interfaz de Usuario)
- **Tecnología**: React 18, Vite, TypeScript, TailwindCSS.
- **Librerías Clave**: `react-leaflet` (Mapas), `d3-force` (Grafos), `framer-motion` (Animaciones).
- **Funciones Principales**:
    - Visualización topológica de la infraestructura.
    - Consola de monitoreo en tiempo real.
    - Gestión administrativa de CIs, Métricas y Usuarios.
    - Interceptor Auth que fuerza el cambio de contraseña genérica "admin" en el primer login.

### 2.3 Capa de Datos
- **Base de Datos**: Neo4j (Graph Database).
- **Modelo de Datos**:
    - **Nodos**: `CI` (Dispositivos/Apps), `MetricDef` (Definiciones de Métricas), `Event` (Alertas), `Category`, `OwnerGroup`.
    - **Relaciones**: `DEPENDS_ON`, `HOSTED_ON`, `CONNECTS_TO`, `HAS_METRIC`, `TRIGGERED_BY`.
    - **Grafo (Neo4j)**: Gestiona el Inventario (CIs) y sus dependencias. Responde a: "¿A quién afecta esta caída?".
    - **Series Temporales (TimescaleDB)**: Almacena el histórico de telemetría recogido por SNMP. Responde a: "¿Cómo se ha comportado este dispositivo en las últimas 24 horas?".
## 3. Módulos y Alcance


### 3.1 Módulos del Backend (`main.py` & Services)

| Módulo | Descripción | Alcance |
| :--- | :--- | :--- |
| **Nodes CRUD** | Gestión de Items de Configuración (CIs). | Crear, Leer, Actualizar y Eliminar dispositivos. Incluye **Reconciliación Automática de Métricas** al modificar propiedades del CI. |
| **Links Operations** | Gestión de relaciones topológicas. | Definir dependencias (`DEPENDS_ON`, `HOSTED_ON`) entre nodos. |
| **Metrics Engine** | Motor de Definición y Asignación de Métricas. | **(MEJORADO)** Definición de métricas con criterios de aplicabilidad granulares y lógicas de evaluación avanzadas: <br> - **Operadores de Umbral**: Selector de regla de evaluación (`>=`, `<=`, `==`, `!=`) previniendo falsas alarmas en OIDs de estados discretos. <br> - **Por Grupo**: Marca, Modelo, Capa de Red. <br> - **Por Nombre**: Asignación explícita a Hosts/IDs específicos (corrección de bug de borrado silencioso). <br> - **Exclusiones**: Lista negra de CIs (`excluded_names`) que no deben recibir la métrica aunque coincidan por grupo. <br> - **Promoción**: Capacidad de convertir una métrica en un Nodo del grafo. |
| **SNMP Worker** | Motor de sondeo y simulación. | Ejecuta consultas y simulaciones de valores. Ya no crea métricas genéricas automáticamente; respeta el grafo definido. |
| **Event Management** | Ciclo de vida de incidentes. | API para gestión de eventos. |

### 3.2 Componentes del Frontend (`frontend/components/`)

| Componente | Descripción | Alcance |
| :--- | :--- | :--- |
| **MetricsManager** | **(NUEVO)** Gestor de Definiciones de Métricas. | Interfaz para crear/editar métricas. Incluye: <br> - Selector de Protocolos (SNMP, ICMP, HTTP...). <br> - Configuración de OIDs, Umbrales y **Reglas de Operación Lógica** con casos de uso en vivo. <br> - **Applicability Rules**: Asignación visual por Marca/Modelo y lista de CIs explícitos con buscador avanzado (corregido crash por variables UI nulas). <br> - **Preview & Exclude**: Tabla de CIs afectados con opción de eliminar (excluir) dispositivos individuales. |
| **RelationshipManager** | Gestor de Relaciones. | **(MEJORADO)** Permite crear enlaces manuales y **Promover Métricas**: Convertir un punto de datos (ej. "CPU Load") en un nodo visual conectado al CI. |
| **MonitoringConsole** | Panel principal. | Visualización de eventos y mapa. |
| **GraphCMDB** | Explorador del grafo. | Visualización de topología. Click en nodo abre detalles. |
| **GlobalInventory** | Inventario tabular. | Lista de CIs con estado en tiempo real. |

### 3.3 Lógica de Negocio Clave

#### Reconciliación Automática de Métricas
El sistema garantiza que las métricas asignadas a un CI estén siempre sincronizadas con sus propiedades (Modelo, Marca, etc.).
1.  **Trigger**: Al Crear o Actualizar un CI (`node_service.upsert_node`).
2.  **Evaluación**: El `metric_service` recalcula qué métricas aplican al CI basado en su *nuevo* estado.
3.  **Acción**:
    *   **Elimina**: Relaciones `HAS_METRIC` que ya no aplican (ej. si un servidor cambia de modelo y pierde compatibilidad con una métrica de hardware anterior), *a menos* que la métrica esté asignada explícitamente por nombre.
    *   **Agrega**: Nuevas relaciones para métricas que ahora sí aplican.
    *   **Respeta Exclusiones**: Si un CI está en la lista `excluded_names` de una métrica, esta nunca se le asignará automáticamente.

## 4. Flujo de Datos (Data Flow)

1.  **Definición**: El Admin define una métrica en `MetricsManager` (ej. "Cisco CPU") y la asigna a la marca "Cisco".
2.  **Reconciliación**: Al guardar un CI "Router-01" (Marca: Cisco), el sistema le asigna automáticamente la métrica.
3.  **Ingesta**: El `SNMP Worker` detecta la relación `HAS_METRIC` y comienza a sondear el OID.
4.  **Excepción**: Si el Admin decide que "Router-01" no debe tener esa métrica, lo excluye desde `MetricsManager`. La relación se borra y se impide su recreación automática.
5.  **Visualización**: Los datos aparecen en `CIDetailModal` o como nodos promovidos en el grafo.

## 5. Próximos Pasos (Roadmap)
- **Alertas Predictivas**: Usar IA para predecir fallos.
- **Agentes Remotos**: Soporte para agentes en OS.
- **Integración ITSM**: Jira/ServiceNow.

### 5.1 Mejoras Pendientes — Modal de Detalle de Evento (Fase 2)

Estos campos están marcados como **🚧 En Desarrollo** porque dependen de infraestructura de datos que aún no existe:

#### SLA Restante (Funcional — post catálogo de servicios)
- **Bloqueado por**: Catálogo de servicios con SLAs definidos por categoría de CI y tier de atención.
- **Plan**: Crear entidad `ServiceCatalog` en Neo4j con campo `sla_minutes` por categoría y tier. Vincular al evento en el momento en que se dispara. Actualmente el campo se lee de `node.metadata.sla_minutes` (fallback manual).
- **Impacto**: Sin catálogo, el SLA Restante muestra "No configurado" para la mayoría de los CIs.

#### Servicio de negocio + Usuarios impactados (Fase 2 — post catálogo)
- **Bloqueado por**: Mapeo manual CI → servicio de negocio y definición de responsables T1/T2/T3 por servicio.
- **Plan**: Crear entidad `BusinessService` en Neo4j. Relación `(ci:CI)-[:BELONGS_TO]->(bs:BusinessService)`. El `BusinessService` contiene: `name`, `owner_t1`, `owner_t2`, `owner_t3`, `impacted_users_count`.
- **Query sugerida**:
  ```cypher
  MATCH (ci:CI {id: $ci_id})-[:BELONGS_TO]->(bs:BusinessService)
  RETURN bs.name, bs.impacted_users_count
  ```

---

## 6. Estado de Desarrollo por Campo — Modal de Detalle de Evento (MonitoringConsole)

> Leyenda: ✅ Funcional | 🚧 En Desarrollo (Fase 2) | ❌ No implementado

### 6.1 Cabecera del Modal (Información del CI)

| Campo | Estado | Fuente de datos | Notas |
| :--- | :---: | :--- | :--- |
| **CI ID** | ✅ Funcional | `ci.id` — Neo4j (backend query) | Identificador único del nodo CI en el grafo. |
| **Nombre del Host** | ✅ Funcional | `ci.label` — Neo4j (backend query) | Label del CI tal como está registrado en la CMDB. |
| **Hostname / IP** | ✅ Funcional | `ci.ip` — Neo4j (backend query) | Dirección IP o nombre de host del dispositivo. Puede ser `null` si no se configuró. |
| **Location Name** | ✅ Funcional | `ci.locationName` — Neo4j (backend query) | Nombre de la ubicación física (ej. "Madrid HQ"). Puede ser `null`. |
| **Categoría CI** | ✅ Funcional | `node.category` / `node.type` — CMDB | Tipo de dispositivo (router, server, app, etc.). |

### 6.2 Banda de Contexto de Negocio (Business Context Band)

| Campo | Estado | Bloqueado por | Plan |
| :--- | :---: | :--- | :--- |
| **Servicio de negocio** | 🚧 En Desarrollo — Fase 2 | Requiere catálogo de servicios con mapeo manual CI → servicio de negocio y definición de responsables T1/T2/T3 por servicio. | Crear entidad `BusinessService` en Neo4j y relación `CI -[:BELONGS_TO]-> BusinessService`. |
| **Usuarios impactados** | 🚧 En Desarrollo — Fase 2 | Requiere mapeo CI → servicio de negocio y definición de número de usuarios por servicio. | Depende de la implementación del catálogo de servicios. |
| **Sede** | ✅ Funcional | — | Se muestra `ci.locationName` si está disponible; coordenadas como fallback. |
| **Categoría CI** | ✅ Funcional | — | Extraído de `node.category` / `node.type`. |
| **SLA Restante** | 🚧 En Desarrollo — Fase 2 | Requiere catálogo de servicios con SLAs definidos por categoría de CI y tier de atención. Sin este catálogo no hay SLA objetivo con qué calcular el tiempo restante. | Crear entidad `ServiceCatalog` con campo `sla_minutes` por categoría y tier. Vincular al evento al dispararse. |
