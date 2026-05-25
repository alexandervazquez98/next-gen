# Manual del Operador — Plataforma NEX-GEN ITOM

> **Versión**: 1.0 | **Última actualización**: Abril 2026
> **Audiencia**: Operadores NOC, administradores IT, equipos de soporte T1/T2/T3
> **No es para desarrolladores.** Si buscás documentación técnica de APIs o arquitectura, consultá `CONTEXT.md` y `docs/`.

---

## Tabla de Contenidos

1. [Primeros Pasos](#1-primeros-pasos)
2. [Consola de Monitoreo](#2-consola-de-monitoreo-monitoringconsole)
3. [Modal de Detalle de Evento](#3-modal-de-detalle-de-evento)
4. [GraphCMDB — Explorador de Topología](#4-graphcmdb--explorador-de-topología)
5. [GlobalInventory — Inventario Global](#5-globalinventory--inventario-global)
6. [MetricsManager — Gestor de Métricas](#6-metricsmanager--gestor-de-métricas)
7. [RelationshipManager — Gestor de Relaciones](#7-relationshipmanager--gestor-de-relaciones)
8. [Panel de Administración](#8-panel-de-administración)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Primeros Pasos

### 1.1 Login

1. Abrí el navegador e ingresá a `http://localhost:3000` (o la URL que te haya dado tu administrador).
2. Ingresá tu **username** y **password**.
3. Hacé click en **AUTHENTICATE**.

### 1.2 Cambio de contraseña obligatoria

Si es tu primer ingreso o un administrador reseteó tu contraseña, vas a ver la pantalla **"Change Password"** con un mensaje amarillo: *"You must change your password to proceed."*

- **Current Password**: ingresá la contraseña temporal (la que te dieron).
- **New Password**: elegí una contraseña segura.
- **Confirm New Password**: repetila.
- Hacé click en **Update Password**.

> **Importante**: No podés usar la plataforma hasta que cambies la contraseña. Si la contraseña genérica es "admin", el sistema te va a forzar este cambio sí o sí.

### 1.3 Navegación principal

Una vez logueado, vas a ver la barra lateral con los módulos principales:

| Módulo | ¿Para qué sirve? |
| :--- | :--- |
| **Dashboard** | Vista general del estado de la infraestructura |
| **Monitoring Console** | Consola de eventos en tiempo real + mapa geográfico |
| **Graph CMDB** | Mapa topológico de dependencias entre CIs |
| **Global Inventory** | Tabla completa de todos los dispositivos |
| **Admin** | Gestión de métricas, relaciones, catálogo e inventario |
| **User Manager** | Gestión de usuarios, roles y permisos (solo admins) |

---

## 2. Consola de Monitoreo (MonitoringConsole)

### 2.1 ¿Qué ves?

La Consola de Monitoreo tiene **dos vistas**:

| Vista | Descripción |
| :--- | :--- |
| **Stream** | Tabla de eventos activos con KPIs arriba |
| **Geo View** | Mapa geográfico con los dispositivos ubicados por sede |

Usá los botones **Stream** / **Geo View** en la barra superior para cambiar.

### 2.2 KPIs (tarjetas superiores)

| KPI | Qué significa |
| :--- | :--- |
| **Critical Events** | Eventos abiertos con severidad CRITICAL (rojo, parpadea si hay activos) |
| **Warnings** | Eventos abiertos con severidad WARNING (amarillo) |
| **Acknowledged** | Eventos que alguien ya tomó en carga (ACK) |
| **Total Active** | Total de eventos activos (todos los estados) |

### 2.3 Tabla de eventos (Live Event Stream)

Cada fila es un evento. Columnas:

| Columna | Qué muestra |
| :--- | :--- |
| **Sev** | Ícono de severidad: 🔴 CRITICAL, 🟡 WARNING, 🔵 INFO |
| **Time** | Hora y fecha de creación del evento |
| **CI Name** | Nombre del dispositivo afectado |
| **Message** | Descripción de la alerta. Si dice "X Correlated Events", hay eventos relacionados agrupados |
| **Status** | `OPEN` (nuevo), `ACK` (en atención), `RECOVERED` (se recuperó) |
| **Actions** | Botones de acción |

### 2.4 Acciones sobre eventos

| Acción | ¿Qué hace? | Permiso necesario |
| :--- | :--- | :--- |
| **Details** | Abre el modal de detalle completo del evento | `EVENT_VIEW` |
| **Ack** | Reconoce el evento (pasa a estado ACK). Indica que alguien está trabajando en ello | `EVENT_ACK` |
| **Tomar caso** | Dentro del modal, asigna el evento a tu usuario | `EVENT_ACK` |

### 2.5 Filtros

- **Filter by Category**: dropdown arriba a la derecha. Filtra eventos por categoría de CI (ej. "ROUTER", "SERVER", "SWITCH").
- **Clean recovered**: botón que cierra en lote todos los eventos `RECOVERED` que no tienen Ack ni comentarios. Te pide confirmación antes de ejecutar.

### 2.6 Vista Geo (Mapa)

El mapa muestra:

- **Puntos azules**: CIs saludables
- **Puntos amarillos**: con warning (más grandes cuantos más warnings)
- **Puntos rojos**: críticos (más grandes cuantos más críticos)
- **Aura punteada**: anillo alrededor de CIs con alertas — indica el radio de impacto geográfico
- **Líneas punteadas**: dependencias (`DEPENDS_ON`) — se animan más rápido cuanto más grave es el estado
- **Líneas verdes continuas**: conexiones de red (`CONNECTS_TO`) con pulso de tráfico
- **Líneas grises finas**: contención (`HOSTED_ON`)

> **Nota**: Las animaciones de las líneas pueden verse estáticas en algunos navegadores. Esto es un problema visual conocido — la telemetría funciona correctamente, solo el efecto visual de movimiento está limitado. Ver [`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md) para más detalle.

### 2.7 Panel "Live Status" (esquina superior derecha del mapa)

Muestra un resumen rápido de alertas críticas y warnings mientras estás en la vista de mapa.

---

## 3. Modal de Detalle de Evento

Se abre al hacer click en **Details** en un evento. Es la herramienta principal de diagnóstico.

### 3.1 Cabecera (información del CI)

| Campo | Qué es |
| :--- | :--- |
| **Severidad** | Badge rojo/amarillo/azul con CRITICAL, WARNING o INFO |
| **Mensaje** | Descripción de la alerta |
| **CI ID** | Identificador único del dispositivo en la CMDB |
| **Host** | Nombre del host + IP entre paréntesis |
| **Ubicación** | Sede física (ej. "Madrid HQ") |
| **Métrica** | Nombre de la métrica que disparó el evento |
| **Protocolo** | SNMP, ICMP, HTTP, etc. |
| **Inicio** | Fecha y hora cuando se detectó el problema |

### 3.2 Banda de Contexto de Negocio

Son 5 tarjetas que dan contexto operacional:

| Tarjeta | Qué muestra |
| :--- | :--- |
| **Servicio de negocio** | A qué servicio pertenece el CI (ej. "Corp-WAN"). Si dice *"No configurado"*, el CI aún no fue vinculado a un servicio |
| **Usuarios impactados** | Cantidad estimada de usuarios afectados. *"No configurado"* = falta definir |
| **Sede** | Ubicación física del dispositivo |
| **Categoría CI** | Tipo de dispositivo (router, server, etc.) |
| **SLA Restante** | Minutos restantes para cumplir el SLA. Se pone **rojo** cuando quedan ≤ 30 min. *"No configurado"* = no hay SLA definido para este servicio |

> **Importante**: Si ves *"No configurado"* en Servicio de negocio, Usuarios impactados o SLA, no es un error. Significa que el CI aún no fue vinculado al catálogo de servicios. Contactá al administrador para que lo configure.

Debajo de las tarjetas, una línea indica la **fuente del contexto**:
- `snapshot` = datos guardados al momento del evento (histórico preciso)
- `resolved` = datos resueltos en tiempo real desde el grafo
- `mixed` = combinación de ambos
- `summary-only` = solo datos básicos disponibles

### 3.3 Barra de Ownership (Asignación)

Muestra quién tiene el caso:

| Elemento | Qué significa |
| :--- | :--- |
| **Sin asignar** (rojo parpadeante) | Nadie tomó el caso todavía |
| **Tomar caso** | Botón verde — te asigna el evento a vos |
| **Tier del evento** | Nivel de soporte esperado (T1, T2, T3) |
| **Estado** | Nuevo / En atención / Cerrado |

Cuando hacés click en **Tomar caso**, el botón queda temporalmente bloqueado mientras se procesa la asignación. Si la operación falla por red, permisos o estado del evento, la consola muestra un error inline en la misma barra de ownership para que no parezca que el click fue ignorado.

### 3.4 Contexto ITSM

Muestra información de gestión de incidentes:

| Campo | Qué es |
| :--- | :--- |
| **Asignación** | Si el evento está asignado y a quién |
| **Abierto por** | Quién o qué sistema generó el evento |
| **Tier de escalación** | T1, T2 o T3 |
| **Ticket externo** | Si hay integración con Jira/ServiceNow, muestra el ticket vinculado (pendiente de implementación) |

### 3.5 Timeline (historial del evento)

Lista cronológica de todas las acciones sobre el evento. Cada entrada tiene un ícono:

| Ícono | Tipo | Color |
| :--- | :--- | :--- |
| 🔧 | Diagnóstico ejecutado | Azul |
| 👤 | Cambio de ownership | Verde |
| ✓ | Cierre (normal o forzado) | Gris |
| 💬 | Nota/comentario | Azul |

### 3.6 Acciones dentro del modal

| Acción | Cómo se hace |
| :--- | :--- |
| **Agregar comentario** | Escribí en el campo de texto y hacé click en "Add Comment" |
| **Ejecutar diagnóstico** | Botón "Run Diagnostics" — ejecuta un chequeo on-demand del CI y el resultado se agrega al timeline |
| **Cerrar evento** | Botón "Close Event" — abre el formulario de cierre |

### 3.7 Cierre de eventos

Hay **dos modos** de cierre:

#### Cierre normal
- **Causa raíz** (obligatorio): describí qué causó el problema
- **Nota** (mínimo 20 caracteres): detallá la resolución
- Se registra como `[AUDIT][CLOSE]` en el timeline

#### Cierre forzado
- Activá el switch **"Forced Close"**
- **Motivo** (obligatorio): explicá por qué cerrás sin resolución completa
- Se registra como `[AUDIT][FORCED_CLOSE]` en el timeline — queda marca explícita de auditoría
- Requiere permiso `EVENT_FORCED_CLOSE`

> **Cuándo usar cierre forzado**: cuando el evento es un falso positivo, cuando se duplica con otro incidente mayor, o cuando la condición se resolvió por sí sola pero el evento no pasó a RECOVERED automáticamente.

---

## 4. GraphCMDB — Explorador de Topología

### 4.1 ¿Qué es?

Es un grafo interactivo que muestra cómo se relacionan todos los dispositivos (CIs) entre sí. Usá D3.js para la visualización.

### 4.2 Tipos de nodos

| Color del borde | Significado |
| :--- | :--- |
| 🔵 Azul | CI saludable |
| 🟠 Naranja | Warning de performance |
| 🔴 Rojo | Impacto crítico |

### 4.3 Tipos de relaciones (líneas)

| Tipo de línea | Apariencia | Qué significa |
| :--- | :--- | :--- |
| `DEPENDS_ON` | Línea punteada `-----→` | El source depende del target. Si el target cae, el source se afecta |
| `HOSTED_ON` | Línea punteada fina `- - -→` | Contención: el source está alojado en el target (ej. una VM en un host) |
| `CONNECTS_TO` | Línea sólida verde con pulso | Conexión de red directa entre dos CIs |

### 4.4 Blast Radius (Radio de Explosión)

Cuando hay incidentes críticos, el grafo **automáticamente**:

- **Opaca** (>60% transparencia) los CIs que NO están afectados
- **Resalta** el CI crítico y toda la cadena de dependencias que impacta
- Los nodos afectados pulsan con borde naranja

Esto te permite ver de un vistazo **a quién afecta** una caída.

### 4.5 Cómo navegar

| Acción | Cómo |
| :--- | :--- |
| **Ver detalle de un CI** | Hacé click en cualquier nodo — se abre el modal de detalle |
| **Mover nodos** | Arrastrá y soltá cualquier nodo para reorganizar el grafo |
| **Zoom** | Usá la rueda del mouse |
| **Leyenda** | Está abajo a la izquierda del grafo |

---

## 5. GlobalInventory — Inventario Global

### 5.1 ¿Qué ves?

Una vista de dos paneles:

- **Izquierda**: lista de todos los CIs con indicador de estado
- **Derecha**: detalle del CI seleccionado con sus métricas en tiempo real

### 5.2 Indicadores de estado

| Indicador | Significado |
| :--- | :--- |
| 🟢 Punto verde | Sin alertas activas |
| 🔴 Punto rojo (parpadeante) | Tiene alertas CRITICAL |

### 5.3 Búsqueda y filtros

| Control | Qué hace |
| :--- | :--- |
| **SEARCH CI** | Buscá por nombre o IP |
| **ALL CATEGORIES** | Filtrá por categoría (router, server, switch, etc.) |

### 5.4 Detalle de un CI

Al seleccionar un CI, el panel derecho muestra:

- **Nombre**, **ID**, **Categoría**, **IP**
- **Active Metrics**: cantidad de métricas configuradas
- **Tarjetas de métricas**: cada una muestra protocolo, nombre, valor actual, estado y última actualización

> **Qué hacer si un CI no tiene métricas**: vas a ver un mensaje "No Metrics Configured". Necesitás asignarle métricas desde el MetricsManager (ver sección 6).

---

## 6. MetricsManager — Gestor de Métricas

### 6.1 ¿Para qué sirve?

Acá creás y editás las **definiciones de métricas** que el sistema usa para monitorear los dispositivos. Una métrica define qué dato recolectar (OID SNMP, ping, etc.), cuándo alertar y a qué dispositivos aplicar.

### 6.2 Estructura de la pantalla

- **Panel izquierdo**: lista de métricas existentes
- **Panel derecho**: editor de la métrica seleccionada

### 6.3 Crear una métrica nueva

1. Hacé click en el botón **+** arriba del panel izquierdo.
2. Completá los campos:

| Campo | Descripción | Ejemplo |
| :--- | :--- | :--- |
| **Metric ID** | Nombre único (no se puede cambiar después) | `cisco_cpu_load` |
| **Protocol** | Tipo de recolección | SNMP, ICMP, HTTP, TOKEN, API, SSH |
| **Criticality** | Nivel de alerta | 1=Info, 2=Warning, 3=Critical |
| **Description** | Descripción legible | "CPU Load percentage on Cisco devices" |

### 6.4 Configuración de OID

| Campo | Descripción |
| :--- | :--- |
| **OID** | El OID SNMP o referencia técnica (ej. `.1.3.6.1.2.1.25.3.3.1.2`) |
| **Auto-Detect Type** | Botón que prueba el OID contra un dispositivo y detecta automáticamente el tipo de dato |
| **Test IP** | IP del dispositivo para probar |
| **Community** | Comunidad SNMP (por defecto: `public`) |

### 6.5 Reglas de umbral (Threshold Rules)

| Operador | Cuándo usarlo | Ejemplo |
| :--- | :--- | :--- |
| **≥ (Greater/Eq)** | Límites superiores | CPU ≥ 90 → Critical |
| **≤ (Less/Eq)** | Límites inferiores | Free Space ≤ 10 → Critical |
| **== (Equals)** | Estados discretos exactos | Status == 0 → Critical (0 = DOWN) |
| **!= (Not Equals)** | Desviaciones de estado normal | Status != 200 → Critical |

> **Tip**: Warning Threshold se desactiva automáticamente cuando usás `==` o `!=`, porque no tiene sentido para estados discretos.

### 6.6 Reglas de aplicabilidad (Applicability)

Determiná **a qué dispositivos** se aplica la métrica:

#### Por modelo de hardware
- Usá el dropdown **Filter by Brand** para filtrar marcas
- Usá **Quick Add Model** para agregar modelos específicos
- Los modelos seleccionados aparecen como **chips** azules que podés remover con la X

#### Por criterios avanzados
| Campo | Qué filtra |
| :--- | :--- |
| **Target Brands** | Por marca (ej. "Cisco, Dell") |
| **Target Layers** | Por capa de red (ej. "INFRASTRUCTURE") |

#### Por CIs explícitos
- Usá el dropdown **Quick Add Explicit CIs** para agregar dispositivos específicos por nombre
- Aparecen como chips azules removibles

#### Exclusiones
> **Importante**: Si un CI coincide por modelo/marca pero no querés que tenga esta métrica, podés excluirlo desde la **tabla de Associated CIs** (ver abajo). El botón de eliminar (🗑️) lo agrega a la lista de `excluded_names` y el sistema nunca le asignará esta métrica automáticamente.

### 6.7 Tabla de Associated CIs (Preview)

Muestra todos los CIs que **actualmente** coinciden con los criterios de aplicabilidad:

| Columna | Qué muestra |
| :--- | :--- |
| **NAME** | Nombre del CI |
| **IP** | Dirección IP |
| **MODEL** | Marca y modelo |
| **ACTION** | Botón de eliminar (excluye el CI de esta métrica) |

### 6.8 Guardar y eliminar

| Botón | Qué hace |
| :--- | :--- |
| **SAVE METRIC** | Guarda la métrica y dispara la reconciliación automática (asigna/desasigna a los CIs que correspondan) |
| **DELETE** | Elimina la métrica. Te avisa cuántos dispositivos están afectados antes de confirmar |
| **CANCEL** | Descarta los cambios |

---

## 7. RelationshipManager — Gestor de Relaciones

### 7.1 ¿Para qué sirve?

Permite **crear relaciones manuales** entre CIs y **promover métricas a nodos** del grafo.

### 7.2 Modo LINKS — Crear relaciones

1. **Seleccioná el Source (Parent/Host)**: filtrá por categoría y elegí el CI origen
2. **Elegí el tipo de relación**:

| Tipo | Cuándo usarlo |
| :--- | :--- |
| `DEPENDS_ON` | El source depende del target para funcionar. Es el que impulsa el análisis de impacto |
| `HOSTED_ON` | El source está alojado dentro del target (VM en host, app en servidor) |
| `CONNECTED_TO` | Conexión de red directa entre dos dispositivos |

3. **Seleccioná los Targets**: podés elegir varios a la vez (multi-select)
4. Hacé click en **Create X Links**

### 7.3 Modo METRICS — Promover métricas a nodos

**¿Qué es promover una métrica?** Convierte un punto de datos (ej. "CPU Load") en un **nodo visual** conectado al CI en el grafo. Esto permite ver la métrica como un componente más de la topología.

1. Cambiá al modo **METRICS** (toggle arriba)
2. Seleccioná un **Source Node**
3. Elegí las métricas que querés promover (multi-select)
4. Hacé click en **Promote X Metrics**

### 7.4 Tabla de relaciones existentes

- **CI Relationships**: lista todas las relaciones entre CIs (excluye HAS_METRIC)
- **Promoted Metrics**: lista las métricas que fueron promovidas a nodos

Cada fila tiene dos acciones:
| Ícono | Qué hace |
| :--- | :--- |
| 🔗 (hub) | Abre el **Correlation Explorer** — muestra el subgrafo centrado en esa relación |
| 🗑️ (delete) | Elimina la relación (pide confirmación) |

### 7.5 Correlation Explorer

Modal de pantalla completa que muestra el grafo de dependencias alrededor de un CI específico. Útil para ver el **blast radius** de un dispositivo. Cerralo con la X de la esquina.

---

## 8. Panel de Administración

### 8.1 Estructura

El panel Admin tiene varias pestañas:

| Pestaña | Qué gestiona |
| :--- | :--- |
| **METRICS** | Definiciones de métricas (acceso rápido al MetricsManager) |
| **CATALOG** | Catálogo de hardware, categorías y grupos de propietarios |
| **LINKS** | Relaciones entre CIs |
| **INVENTORY** | Vista avanzada del inventario de CIs con editor |

### 8.2 Gestión de Usuarios (User Manager)

Accesible desde la navegación principal o desde Admin.

#### Crear un usuario nuevo

1. Hacé click en **Add User**
2. Completá:

| Campo | Descripción |
| :--- | :--- |
| **Username** | Nombre de usuario (único) |
| **Password** | Contraseña inicial (el usuario deberá cambiarla en su primer login) |
| **Role** | Rol predefinido (VIEWER, OPERATOR, ADMIN, etc.) |
| **Permissions** | Permisos individuales (se pueden agregar/quitar manualmente) |
| **Phone / Email** | Datos de contacto opcionales |

#### Permisos disponibles

| Categoría | Permisos | Qué permiten |
| :--- | :--- | :--- |
| **Event Management** | `EVENT_VIEW` | Ver detalle de eventos |
| | `EVENT_ACK` | Reconocer/tomar eventos |
| | `EVENT_CLOSE` | Cerrar eventos |
| **CI Management** | `CI_VIEW` | Ver CIs |
| | `CI_EDIT` | Editar CIs |
| | `CI_DELETE` | Eliminar CIs |
| **Diagnostics** | `RUN_DIAGNOSTICS` | Ejecutar diagnósticos on-demand |
| **System** | `USER_MANAGE` | Gestionar usuarios |
| | `ROLE_MANAGE` | Gestionar roles |

> **Nota**: `EVENT_FORCED_CLOSE` es un permiso adicional que permite cerrar eventos en modo forzado. No aparece en la lista estándar porque es sensible.

### 8.3 Gestión de Roles (Role Manager)

Los roles son **conjuntos de permisos** que se asignan a usuarios.

| Acción | Cómo |
| :--- | :--- |
| **Crear rol** | Botón "Create Role" — elegí nombre, descripción y permisos |
| **Editar rol** | Click en el rol → modificá permisos → Save |
| **Eliminar rol** | Botón delete (pide confirmación) |

> **Cuidado**: Los roles marcados como **system** no se pueden eliminar.

---

## 9. Troubleshooting

### 9.1 Estados de eventos — qué significa cada uno

| Estado | Significado | ¿Qué hacer? |
| :--- | :--- | :--- |
| **OPEN** | Evento nuevo, nadie lo tomó | Si te toca, hacé click en **Ack** o **Tomar caso** |
| **ACK** | Alguien está trabajando en ello | Si sos el asignado, diagnosticá y resolvé. Si no, podés ver el detalle |
| **RECOVERED** | La condición técnica desapareció | Puede cerrarse automáticamente con "Clean recovered" o manualmente |
| **CLOSED** | Evento cerrado | Queda como registro de auditoría. No se reabre |

### 9.2 Errores comunes

| Problema | Causa probable | Solución |
| :--- | :--- | :--- |
| **"No configurado" en Servicio de negocio** | El CI no está vinculado a un BusinessService | Contactá al admin para que ejecute el mapeo Cypher |
| **"No configurado" en SLA Restante** | No hay ServiceCatalog definido para la categoría del CI | El admin debe crear el catálogo con SLA |
| **"No Metrics Configured" en un CI** | No hay métricas aplicables a ese dispositivo | Creá una métrica en MetricsManager con criterios que matcheen al CI |
| **Evento no se cierra** | Falta completar causa raíz o nota (mínimo 20 caracteres) | Completá todos los campos obligatorios |
| **No puedo ver el detalle de un evento** | No tenés el permiso `EVENT_VIEW` | Pedile al admin que te lo asigne |
| **No puedo cerrar eventos** | No tenés `EVENT_CLOSE` | Pedile al admin que te lo asigne |
| **No puedo hacer cierre forzado** | No tenés `EVENT_FORCED_CLOSE` | Este permiso es restringido — consultá con tu lead |

### 9.3 Cuándo escalar

| Situación | Escalar a |
| :--- | :--- |
| Evento CRITICAL en un CI de un servicio de negocio crítico | T2/T3 inmediatamente |
| Múltiples eventos correlacionados en la misma zona | T2 — puede ser un incidente mayor |
| SLA a punto de vencerse (< 30 min, indicado en rojo) | T2/T3 — riesgo de breach |
| Dispositivo sin métricas que debería monitorearse | Admin del equipo de monitoreo |
| Usuario sin acceso a funciones que necesita | Admin del sistema |

### 9.4 Problemas conocidos

| Problema | Impacto | Workaround |
| :--- | :--- | :--- |
| **Animaciones de líneas estáticas en el mapa** | Las líneas de dependencia no muestran el efecto de movimiento animado | La telemetría y los colores funcionan correctamente. Solo el efecto visual está limitado. Ver [`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md) para detalle técnico |

### 9.5 Referencias útiles

| Documento | Qué encontrás |
| :--- | :--- |
| [`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md) | Bugs activos y handovers de desarrollo |
| `docs/domain/business-model.md` | Modelo de negocio: cómo se relacionan CIs, servicios y SLAs |
| `docs/itsm/event-flow.md` | Flujo completo de eventos: lifecycle, ownership, escalación |

---

## Glosario rápido

| Término | Definición |
| :--- | :--- |
| **CI** (Configuration Item) | Cualquier dispositivo, servidor, app o componente registrado en la CMDB |
| **CMDB** | Base de datos de configuración — el inventario de tu infraestructura |
| **OID** | Identificador de objeto SNMP — la "dirección" de un dato específico en un dispositivo |
| **SLA** | Acuerdo de nivel de servicio — tiempo máximo permitido para resolver un incidente |
| **Tier** | Nivel de soporte: T1 (primera línea), T2 (especializado), T3 (arquitectura/expertos) |
| **Blast Radius** | Cadena de CIs afectados por la caída de un dispositivo |
| **Snapshot** | Foto del contexto de negocio guardada al momento de crear un evento |
| **Promover métrica** | Convertir un dato de telemetría en un nodo visual del grafo |
