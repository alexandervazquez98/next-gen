import React, { useState, useEffect } from 'react';
import { HashRouter as Router, Routes, Route, Link, useLocation, Navigate, useNavigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import LoginPage from './components/LoginPage';
import { GraphNode, GraphLink } from './types';

// Components
import GraphCMDB from './components/GraphCMDB';
import NetworkVisualizer from './components/NetworkVisualizer';
import AIAgentConsole from './components/AIAgentConsole';
import CIEditor from './components/CIEditor';
import AdminPage from './components/AdminPage';
import MonitoringConsole from './components/MonitoringConsole';
import SystemDashboard from './components/SystemDashboard';
import GlobalInventory from './components/GlobalInventory';
import ChangePasswordPage from './components/ChangePasswordPage';
import UserManager from './components/UserManager';
import RoleManager from './components/RoleManager';
import CIDetailModal from './components/CIDetailModal';
import MetricAnalytics from './components/MetricAnalytics';
import AgentManager from './components/AgentManager';

// --- Protected Route Helper ---
const ProtectedRoute = ({ children }: { children: React.ReactElement }) => {
  const { isAuthenticated, token, user } = useAuth();
  const location = useLocation();

  if (!isAuthenticated && !token) {
    return <Navigate to="/login" replace />;
  }

  if (user?.force_password_change && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  return children;
};

// --- Main Layout (Authenticated) ---
const MainLayout: React.FC = () => {
  const { user, logout, hasPermission } = useAuth();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  useEffect(() => {
    fetchNodes();
    fetchLinks();
  }, []);

  const fetchNodes = () => {
    fetch('/api/nodes', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    })
      .then(res => {
        if (res.status === 401) logout();
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(data => {
        if (Array.isArray(data)) setNodes(data);
      })
      .catch(err => console.error(err));
  };

  const fetchLinks = () => {
    fetch('/api/links', {
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    })
      .then(res => {
        if (!res.ok) throw new Error(res.statusText);
        return res.json();
      })
      .then(data => {
        if (Array.isArray(data)) setLinks(data);
      })
      .catch(err => console.error(err));
  };

  const [isEditing, setIsEditing] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showAIAgent, setShowAIAgent] = useState(false);

  // --- CRUD Functions ---
  const handleSaveCI = (newNode: GraphNode) => {
    fetch('/api/nodes', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      },
      body: JSON.stringify(newNode)
    })
      .then(res => res.json())
      .then(savedNode => {
        setNodes(prev => {
          const exists = prev.find(n => n.id === savedNode.id);
          if (exists) return prev.map(n => n.id === savedNode.id ? savedNode : n);
          return [...prev, savedNode];
        });
        setIsEditing(false);
        setSelectedNode(null);
      })
      .catch(err => console.error(err));
  };

  const handleDeleteCI = (id: string) => {
    fetch(`/api/nodes/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    })
      .then(() => {
        setNodes(prev => prev.filter(n => n.id !== id));
        setLinks(prev => prev.filter(l => l.source !== id && l.target !== id));
        setIsEditing(false);
        setSelectedNode(null);
      })
      .catch(err => console.error(err));
  };

  const exportToPythonAgent = () => {
    const data = JSON.stringify({ nodes, links }, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cmdb_inventory.json';
    a.click();
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface-950 font-sans text-neutral-200">
      {/* Sidebar Nav */}
      <nav className="w-20 lg:w-64 border-r border-white/5 flex flex-col glass z-50">
        <div className="p-6 flex items-center gap-3">
          <div className="w-10 h-10 bg-brand-600 rounded-xl flex items-center justify-center text-white neon-glow">
            <span className="material-symbols-outlined text-2xl">hub</span>
          </div>
          <span className="hidden lg:block font-black text-xl tracking-tighter text-white">NEX-GEN</span>
        </div>

        <div className="flex-1 flex flex-col py-6 space-y-2 px-3">
          <NavItem to="/" icon="dashboard" label="Architecture" />
          <NavItem to="/monitoring" icon="public" label="Monitoring" />
          <NavItem to="/cmdb" icon="mediation" label="Graph CMDB" />
          <NavItem to="/inventory" icon="inventory_2" label="CI Inventory" />
          <NavItem to="/network" icon="hub" label="Network Topology" />

          {(hasPermission('ADMIN') || hasPermission('METRICS_VIEW')) && (
            <NavItem to="/analytics" icon="monitoring" label="Analytics" />
          )}

          {(hasPermission('ADMIN') || hasPermission('CI_EDIT')) && (
            <NavItem to="/agents" icon="smart_toy" label="Agents" />
          )}

          {(hasPermission('ADMIN') || hasPermission('USER_MANAGE')) && (
            <NavItem to="/users" icon="manage_accounts" label="User Management" />
          )}
          {(hasPermission('ADMIN') || hasPermission('USER_MANAGE')) && (
            <NavItem to="/admin" icon="admin_panel_settings" label="Administration" />
          )}
        </div>

        <div className="p-6 space-y-4 border-t border-white/5">
          <button onClick={exportToPythonAgent} className="w-full flex items-center gap-3 px-4 py-2 text-[10px] font-black uppercase text-neutral-500 hover:text-white transition-colors">
            <span className="material-symbols-outlined text-sm">terminal</span>
            Python Export
          </button>
          <div className="flex items-center gap-3 group cursor-pointer" onClick={logout} title="Click to Logout">
            <div className="w-10 h-10 rounded-full bg-neutral-800 border border-white/10 overflow-hidden flex items-center justify-center">
              {/* Initials */}
              <span className="font-bold text-lg">{user?.username?.substring(0, 2).toUpperCase()}</span>
            </div>
            <div className="hidden lg:block text-left">
              <p className="text-xs font-bold text-white">{user?.username || 'Guest'}</p>
              <p className="text-[10px] text-neutral-500 uppercase tracking-widest">{user?.role || 'Viewer'}</p>
            </div>
            <span className="material-symbols-outlined text-neutral-500 group-hover:text-red-500 ml-auto text-sm">logout</span>
          </div>
        </div>
      </nav>

      {/* Main View Area */}
      <div className="flex-1 flex flex-col relative overflow-hidden">
        <header className="h-20 border-b border-white/5 flex items-center justify-between px-8 glass z-40">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold text-white tracking-tight uppercase tracking-widest">Platform Engine v3.2</h1>
            <div className="hidden md:flex items-center gap-2 bg-neutral-900 border border-white/5 px-3 py-1 rounded-full text-[10px] font-black text-accent-cyan">
              <span className="w-2 h-2 bg-accent-cyan rounded-full animate-pulse"></span>
              SNMP Polling: ACTIVE ({nodes.length} Nodes)
            </div>
          </div>

          <div className="flex items-center gap-4">
            {/* Header Actions */}
            <button
              onClick={() => setShowAIAgent(!showAIAgent)}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-black transition-all border ${showAIAgent ? 'bg-white/10 text-white border-white/20' : 'bg-transparent text-neutral-500 border-white/5 hover:text-white'}`}
            >
              <span className="material-symbols-outlined text-sm">{showAIAgent ? 'chat' : 'chat_bubble_outline'}</span>
              {showAIAgent ? 'HIDE AI' : 'SHOW AI'}
            </button>
          </div>
        </header>

        <main className="flex-1 flex overflow-hidden relative">
          <div className="flex-1 h-full relative overflow-hidden">
            <Routes>
              <Route index element={<SystemDashboard />} />
              <Route path="monitoring" element={<MonitoringConsole />} />
              <Route path="admin" element={<AdminPage />} />
              <Route path="users" element={<UserManager />} />
              <Route path="cmdb" element={<GraphCMDB nodes={nodes} links={links} onNodeClick={(n) => { setSelectedNode(n); setShowDetailModal(true); }} />} />
              <Route path="network" element={<NetworkVisualizer />} />
              <Route path="analytics" element={<MetricAnalytics />} />
              <Route path="agents" element={<AgentManager />} />
              <Route path="inventory" element={<GlobalInventory />} />
            </Routes>
          </div>

          {isEditing && (
            <CIEditor
              node={selectedNode}
              onSave={handleSaveCI}
              onDelete={handleDeleteCI}
              onClose={() => setIsEditing(false)}
            />
          )}

          {showDetailModal && (
            <CIDetailModal
              node={selectedNode}
              onClose={() => setShowDetailModal(false)}
            />
          )}

          <aside className={`w-96 border-l border-white/5 glass flex flex-col transition-all duration-500 ${isEditing || !showAIAgent ? 'opacity-0 translate-x-full absolute right-0' : 'relative opacity-100 translate-x-0'}`}>
            <AIAgentConsole />
          </aside>
        </main>
      </div>
    </div>
  );
};

// --- Helper Components ---
const NavItem: React.FC<{ to: string, icon: string, label: string, count?: number }> = ({ to, icon, label, count }) => {
  const location = useLocation();
  const active = location.pathname === to;
  return (
    <Link to={to} className={`flex items-center gap-4 px-4 py-3.5 rounded-2xl transition-all duration-300 group ${active ? 'bg-brand-600/15 text-brand-400 border border-brand-600/20' : 'text-neutral-500 hover:text-neutral-200 hover:bg-white/5'
      }`}>
      <span className={`material-symbols-outlined text-2xl ${active ? 'fill-1' : ''}`}>{icon}</span>
      <span className="hidden lg:block text-sm font-bold">{label}</span>
      {count && <span className="ml-auto bg-red-500/20 text-red-500 text-[10px] px-1.5 py-0.5 rounded">{count}</span>}
    </Link>
  );
};

// --- App Entry Point ---
const App: React.FC = () => {
  return (
    <Router>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/change-password" element={
            <ProtectedRoute>
              <ChangePasswordPage />
            </ProtectedRoute>
          } />
          <Route path="/*" element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          } />
        </Routes>
      </AuthProvider>
    </Router>
  );
};

export default App;
