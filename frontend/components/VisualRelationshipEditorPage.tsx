import type React from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import VisualRelationshipEditor from './VisualRelationshipEditor';
import { useNodesQuery } from '../hooks/queries/useNodesQuery';
import { useLinksQuery } from '../hooks/queries/useLinksQuery';
import { queryKeys } from '../services/queryKeys';
import { useAuth } from '../context/AuthContext';

const AccessDenied = () => (
  <section className="flex h-full items-center justify-center bg-neutral-950 p-8 text-neutral-300" aria-label="Visual relationship editor access denied">
    <div className="max-w-lg rounded-2xl border border-amber-500/30 bg-amber-500/10 p-6 text-center">
      <p className="text-sm font-black uppercase tracking-widest text-amber-200">Access denied</p>
      <p className="mt-2 text-xs text-neutral-400">You need CI edit permissions to open the visual relationship editor.</p>
      <Link to="/admin" className="mt-4 inline-flex rounded-xl border border-white/10 px-4 py-2 text-xs font-black uppercase text-white hover:bg-white/10">
        Back to admin
      </Link>
    </div>
  </section>
);

const VisualRelationshipEditorPageContent: React.FC = () => {
  const queryClient = useQueryClient();
  const nodesQuery = useNodesQuery();
  const linksQuery = useLinksQuery();

  const nodes = nodesQuery.data ?? [];
  const links = linksQuery.data ?? [];
  const isLoading = nodesQuery.isLoading || linksQuery.isLoading;
  const error = nodesQuery.error ?? linksQuery.error;

  const refreshRelationshipData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.nodes() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.links() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.graphTopology() }),
    ]);
  };

  if (isLoading) {
    return (
      <section className="flex h-full items-center justify-center bg-neutral-950 text-neutral-300" aria-label="Loading visual relationship editor">
        <div className="text-center">
          <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-brand-600 border-t-transparent" />
          <p className="text-xs font-black uppercase tracking-widest text-neutral-500">Loading visual editor...</p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="flex h-full items-center justify-center bg-neutral-950 p-8 text-neutral-300" aria-label="Visual relationship editor error">
        <div className="max-w-lg rounded-2xl border border-red-500/30 bg-red-500/10 p-6 text-center">
          <p className="text-sm font-black uppercase tracking-widest text-red-300">Could not load visual editor data</p>
          <p className="mt-2 text-xs text-neutral-400">Refresh the page or return to relationship management.</p>
          <Link to="/admin" className="mt-4 inline-flex rounded-xl border border-white/10 px-4 py-2 text-xs font-black uppercase text-white hover:bg-white/10">
            Back to admin
          </Link>
        </div>
      </section>
    );
  }

  return (
    <VisualRelationshipEditor
      nodes={nodes}
      links={links}
      onClose={() => window.close()}
      onMutated={refreshRelationshipData}
    />
  );
};

const VisualRelationshipEditorPage: React.FC = () => {
  const { hasPermission } = useAuth();
  const canEditRelationships = hasPermission('CI_EDIT') || hasPermission('CI_DELETE');

  return canEditRelationships ? <VisualRelationshipEditorPageContent /> : <AccessDenied />;
};

export default VisualRelationshipEditorPage;
