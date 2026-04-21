// --- Constraints & Indexes ---
CREATE CONSTRAINT ci_id_unique IF NOT EXISTS FOR (n:CI) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT metric_def_id_unique IF NOT EXISTS FOR (m:MetricDef) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT event_id_unique IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT category_name_unique IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE;
CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE;
CREATE CONSTRAINT user_username_unique IF NOT EXISTS FOR (u:User) REQUIRE u.username IS UNIQUE;

CREATE INDEX ci_name_indx IF NOT EXISTS FOR (n:CI) ON (n.name);
CREATE INDEX ci_ip_indx IF NOT EXISTS FOR (n:CI) ON (n.ip);
CREATE INDEX ci_location_indx IF NOT EXISTS FOR (n:CI) ON (n.location_name);
CREATE INDEX ci_layer_indx IF NOT EXISTS FOR (n:CI) ON (n.layer);
CREATE INDEX ci_owner_indx IF NOT EXISTS FOR (n:CI) ON (n.owner);
CREATE INDEX event_status_indx IF NOT EXISTS FOR (e:Event) ON (e.status);
CREATE INDEX event_severity_indx IF NOT EXISTS FOR (e:Event) ON (e.severity);
CREATE INDEX event_created_indx IF NOT EXISTS FOR (e:Event) ON (e.created_at);

// --- Sample Data Seeding (Matches SQL Scope) ---

// 1. Categories
MERGE (c1:Category {name: 'Server'})
MERGE (c2:Category {name: 'Network'})
MERGE (c3:Category {name: 'Application'})
MERGE (c4:Category {name: 'Database'})

// 2. CIs (Configuration Items)
MERGE (ci1:CI {id: 'CI-001', name: 'Core-Switch-01', ip: '192.168.1.1', layer: 'Hardware', status: 'Active', owner: 'NetOps'})
  ON CREATE SET ci1.location = point({latitude: 40.7128, longitude: -74.0060}), ci1.created_at = datetime()
MERGE (ci2:CI {id: 'CI-002', name: 'App-Server-01', ip: '10.0.0.5', layer: 'Application', status: 'Active', owner: 'DevOps'})
  ON CREATE SET ci2.location = point({latitude: 40.7128, longitude: -74.0060}), ci2.created_at = datetime()
MERGE (ci3:CI {id: 'CI-003', name: 'DB-Cluster-01', ip: '10.0.0.20', layer: 'Database', status: 'Active', owner: 'DBA'})
  ON CREATE SET ci3.location = point({latitude: 40.7128, longitude: -74.0060}), ci3.created_at = datetime()

// 3. Categorization
MATCH (c:CI {id: 'CI-001'}), (cat:Category {name: 'Network'}) MERGE (c)-[:CATEGORIZED_AS]->(cat);
MATCH (c:CI {id: 'CI-002'}), (cat:Category {name: 'Server'}) MERGE (c)-[:CATEGORIZED_AS]->(cat);
MATCH (c:CI {id: 'CI-003'}), (cat:Category {name: 'Database'}) MERGE (c)-[:CATEGORIZED_AS]->(cat);

// 4. Relationships (Topology)
// Replacing generic 'relationship' table with specific directed edges
MATCH (app:CI {name: 'App-Server-01'}), (db:CI {name: 'DB-Cluster-01'})
MERGE (app)-[:DEPENDS_ON {criticality: 'High'}]->(db);

MATCH (app:CI {name: 'App-Server-01'}), (sw:CI {name: 'Core-Switch-01'})
MERGE (app)-[:CONNECTS_TO]->(sw);

MATCH (db:CI {name: 'DB-Cluster-01'}), (sw:CI {name: 'Core-Switch-01'})
MERGE (db)-[:CONNECTS_TO]->(sw);

// 5. Users
MERGE (u:User {id: 1, role: 'Admin', access_level: 'Full', status: 'Active'});

// 6. Metrics Definitions
MERGE (m:MetricDef {id: 'M-CPU', protocol: 'SNMP', warning: 80, critical: 90})
WITH m
MATCH (ci:CI {name: 'App-Server-01'})
MERGE (ci)-[:HAS_METRIC]->(m);
