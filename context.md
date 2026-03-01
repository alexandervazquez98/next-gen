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

### 2.2 Frontend (Interfaz de Usuario)
- **Tecnología**: React 18, Vite, TypeScript, TailwindCSS.
- **Librerías Clave**: `react-leaflet` (Mapas), `d3-force` (Grafos), `framer-motion` (Animaciones).
- **Funciones Principales**:
    - Visualización topológica de la infraestructura.
    - Consola de monitoreo en tiempo real.
    - Gestión administrativa de CIs, Métricas y Usuarios.

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
