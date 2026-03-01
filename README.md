# NEX-GEN Platform (NEX-GEN ITOM)

## Descripción General
NEX-GEN es una plataforma avanzada de gestión de operaciones de TI (ITOM) diseñada bajo los más altos estándares de arquitectura. Su núcleo está centrado en una CMDB basada en grafos (Neo4j), que permite no solo un inventario preciso, sino una visualización y gestión relacional profunda de la infraestructura. Integra telemetría en tiempo real, recolección de métricas dinámicas vía SNMP, y diagnósticos asistidos mediante un motor de analítica (AIOps). Su propósito es brindar una visión holística de la salud tecnológica, gestionando incidentes de forma proactiva y ofreciendo correlación visual y lógica de dependencias.

## Arquitectura
El sistema operativo se estructura bajo el estándar de microservicios de Antigravity, garantizando escalabilidad, resiliencia y separación de responsabilidades:

- **Backend (API & Lógica de Negocio)**: Desarrollado en Python (FastAPI). Centraliza la lógica de negocio, expone la API RESTful para la interfaz de usuario, interactúa directamente con la base de datos de grafos para la gestión de topología, y coordina los ciclos de vida de eventos/incidentes (alineado con ITIL 4).
- **Frontend (Interfaz de Usuario)**: Aplicación SPA (Single Page Application) construida estáticamente con React 18, Vite, TypeScript y TailwindCSS. Incorpora representaciones en 2D/3D (D3/Force Graph) y mapas geoespaciales (Leaflet) para un control situacional en tiempo real.
- **Capa de Datos**:
  - **Neo4j**: Base de datos de grafos para la topología, CMDB, y relaciones lógicas complejas.
  - **TimescaleDB (PostgreSQL 16)**: Repositorio optimizado para métricas de series temporales y persistencia de autenticación/roles.
- **Motores/Workers (AIOps & Sondeo)**:
  - **SNMP Worker**: Proceso asíncrono para recolección continua de telemetría de red.
  - **Analytics Worker (AIOps)**: Motor que busca proactivamente estados críticos en la topología, con capacidad heurística para simular diagnósticos o resolución automática de incidentes (Auto-Fix).

## Instalación y Configuración

El proyecto está completamente contenerizado, facilitando un despliegue ágil "Zero-Config" en entornos de desarrollo.

**Requisitos Previos:**
- Docker y Docker Compose instalados.

**Pasos de Despliegue Rápidos:**
1. Clona el repositorio en tu máquina local.
2. Navega al directorio raíz del proyecto (`zero-co`).
3. Construye e inicializa todo el stack de contenedores:
   ```bash
   docker-compose up --build -d
   ```
4. **Accesos:**
   - **Frontend Console**: [http://localhost:3000](http://localhost:3000)
   - **Backend API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Neo4j Browser**: [http://localhost:7474](http://localhost:7474) (Auth: `neo4j` / `nexgen_password`)

## Stack Tecnológico

| Componente | Tecnologías |
| :--- | :--- |
| **Backend** | Python 3.10+, FastAPI, Uvicorn, SQLAlchemy, Pydantic, PySNMP, Pandas |
| **Frontend** | React 18, TypeScript, Vite, TailwindCSS, React Leaflet, D3-Force, Recharts, @google/genai |
| **Base de Datos** | Neo4j 5.15.0, TimescaleDB (PostgreSQL 16) |
| **Infraestructura** | Docker, Docker Compose |
| **Protocolos** | HTTP/REST, SNMP (Polling), Bolt (Neo4j) |

## Identificación de Entidades (Graph DB Modelo)
Las principales entidades que alimentan la base de datos Neo4j para mapear el ecosistema ITIL son:

- **`CI` (Configuration Item)**: Representa activos, dispositivos de red, servidores o aplicaciones.
- **`MetricDef`**: Definición de métricas de telemetría asignables dinámicamente.
- **`Event`**: Incidentes, Alertas o Cambios de estado en la infraestructura.
- **`Category`**: Clasificaciones lógicas de inventario de hardware y software.
- **`OwnerGroup`**: Agrupaciones lógicas de responsables o usuarios de soporte.

*Principales Relaciones (Edges):* `DEPENDS_ON`, `HOSTED_ON`, `CONNECTS_TO`, `HAS_METRIC`, `TRIGGERED_BY`.

## Estado del Proyecto (Roadmap & Features)

**Funcionalidades Implementadas:**
- CMDB relacional y topológica en tiempo real (Visualización en Grafo Integrada).
- CRUD de Nodos y Operaciones de Enlaces (Links).
- Reconciliación Automática de Métricas (Asigna sondas basándose en marca/modelo del CI).
- **Asignación de Métricas de Alta Granularidad**: Soporte para reglas lógicas (`>=`, `==`, `!=`, etc.) en umbrales y asignación explícita (Opt-In/Opt-Out) por CIs individuales.
- Monitorización activa vía SNMP Worker para la recolección de datos de red e infraestructura.
- Event Management básico API (Estados: Open, Ack, Closed).
- Agente AIOps Simulador: Un script que sondea nodos en estado "CRITICAL" e inyecta resoluciones asistidas simuladas.

**Pendiente de Definición / Roadmap Futuro:**
- **Alertas Predictivas Nativas**: Integración profunda del SDK de @google/genai para predecir fallos basándose en patrones anómalos de series temporales (descrito en roadmap pero requiere clarificación en el flujo de backend).
- **Agentes Remotos**: Compatibilidad confirmada en contexto, pero el mecanismo de despliegue y push-telemetry (vs polling) está *Pendiente de Definición*.
- **Integración ITSM**: Conectores bidireccionales formales para Jira / ServiceNow *Pendientes de Definición* arquitectónica.
