
import React, { useState } from 'react';
import MetricsManager from './MetricsManager';
import CatalogManager from './CatalogManager';
import RelationshipManager from './RelationshipManager';
import MassLinkEditor from './MassLinkEditor';
import AdminInventory from './AdminInventory';

/**
 * AdminPage Component
 * Central administration interface orchestrator.
 */
const AdminPage: React.FC = () => {
    type AdminTab = 'METRICS' | 'CATALOG' | 'LINKS' | 'INVENTORY' | 'MASS_LINKS';
    const [activeTab, setActiveTab] = useState<AdminTab>('METRICS');

    return (
        <div className="flex flex-col h-screen bg-surface-950 overflow-hidden">
            {/* Admin Navigation Bar - Fixed Height */}
            <div className="bg-neutral-900/50 backdrop-blur-xl border-b border-white/5 px-8 py-4 flex justify-between items-center shrink-0 z-50">
                <div className="flex items-center gap-6">
                    <div>
                        <h1 className="text-xl font-black text-white tracking-tighter uppercase">Nexus Command</h1>
                        <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-widest">System Administration</p>
                    </div>

                    <nav className="flex gap-1 ml-8">
                        {[
                            { id: 'METRICS', label: 'Metrics Def', icon: 'analytics' },
                            { id: 'CATALOG', label: 'Catalog', icon: 'inventory_2' },
                            { id: 'LINKS', label: 'Links', icon: 'link' },
                            { id: 'MASS_LINKS', label: 'Mass Links', icon: 'dynamic_feed' },
                            { id: 'INVENTORY', label: 'Inventory', icon: 'list_alt' }
                        ].map((tab) => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id as AdminTab)}
                                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                                    activeTab === tab.id 
                                    ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20 shadow-lg shadow-brand-500/5' 
                                    : 'text-neutral-500 hover:text-neutral-300 hover:bg-white/5 border border-transparent'
                                }`}
                            >
                                <span className="material-symbols-outlined text-sm">{tab.icon}</span>
                                {tab.label}
                            </button>
                        ))}
                    </nav>
                </div>
            </div>

            {/* Content Area - Absolute Container to lock boundaries */}
            <div className="flex-1 relative overflow-hidden bg-black/20">
                <div className="absolute inset-0">
                    {activeTab === 'METRICS' && <MetricsManager />}
                    {activeTab === 'CATALOG' && <CatalogManager />}
                    {activeTab === 'LINKS' && <RelationshipManager />}
                    {activeTab === 'MASS_LINKS' && <MassLinkEditor />}
                    {activeTab === 'INVENTORY' && <AdminInventory />}
                </div>
            </div>
        </div>
    );
};

export default AdminPage;
