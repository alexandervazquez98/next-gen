import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MetricsManager from './MetricsManager';
import type { MetricDef } from '../types';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('../services/api', () => ({
  api: {
    get: mocks.apiGet,
    post: mocks.apiPost,
    delete: mocks.apiDelete,
  },
}));

const metricA: MetricDef = {
  id: 'cpu.load',
  protocol: 'SNMP',
  oid: '.1.3.6.1.4.1.9.2.1.57.0',
  warning: 70,
  critical: 90,
  dataType: 'INTEGER',
  description: 'CPU load metric',
  criticality: 2,
  applicable_to: {
    brands: ['Cisco'],
    models: ['ASR1001'],
    layers: ['INFRASTRUCTURE'],
    names: ['router-01'],
    excluded_names: ['router-02'],
  },
};

const metricADetail: MetricDef = {
  ...metricA,
  operator: '<=',
  warning: 55,
  critical: 25,
  unit: 'ms',
  polling_interval: 300,
};

const metricB: MetricDef = {
  id: 'mem.usage',
  protocol: 'SNMP',
  oid: '.1.3.6.1.4.1.2021.4.6.0',
  warning: 80,
  critical: 95,
  dataType: 'FLOAT',
  description: 'Memory usage metric',
  criticality: 3,
  applicable_to: {
    brands: ['Dell'],
    models: ['R740'],
  },
};

const hardwareModels = [
  { brand: 'Cisco', model: 'ASR1001' },
  { brand: 'Dell', model: 'R740' },
  { brand: 'Dell', model: 'R750' },
];

const usageData = {
  count: 2,
  cis: [
    { id: 'ci-1', name: 'router-01', ip: '10.0.0.1', brand: 'Cisco', model: 'ASR1001' },
    { id: 'ci-2', name: 'router-02', ip: '10.0.0.2', brand: 'Cisco', model: 'ASR1001' },
  ],
};

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const setupApiGet = (options?: {
  metrics?: MetricDef[];
  hardware?: Array<{ brand: string; model: string }>;
  usage?: Record<string, any>;
  nodes?: Array<{ id: string; name: string; label?: string; ip?: string }>;
}) => {
  const metrics = options?.metrics ?? [metricA, metricB];
  const hardware = options?.hardware ?? hardwareModels;
  const usage = options?.usage ?? {
    'cpu.load': usageData,
    'mem.usage': { count: 0, cis: [] },
  };
  const metricDetails = {
    'cpu.load': metricADetail,
    'mem.usage': metricB,
  };
  const nodes = options?.nodes ?? [
    { id: 'ci-1', name: 'router-01', label: 'router-01', ip: '10.0.0.1' },
    { id: 'ci-2', name: 'router-02', label: 'router-02', ip: '10.0.0.2' },
    { id: 'ci-3', name: 'switch-01', label: 'switch-01', ip: '10.0.1.1' },
  ];

  mocks.apiGet.mockImplementation(async (endpoint: string) => {
    if (endpoint === '/metrics') return metrics;
    if (endpoint === '/metrics/cpu.load') return metricDetails['cpu.load'];
    if (endpoint === '/metrics/mem.usage') return metricDetails['mem.usage'];
    if (endpoint === '/hardware') return hardware;
    if (endpoint === '/metrics/cpu.load/usage') return usage['cpu.load'];
    if (endpoint === '/metrics/mem.usage/usage') return usage['mem.usage'];
    if (endpoint === '/nodes') return nodes;
    throw new Error(`Unhandled GET ${endpoint}`);
  });
};

const renderMetricsManager = () => render(<MetricsManager />);

const getInputByLabel = (label: string | RegExp) => {
  const labelNode = screen.getByText(label);
  return labelNode.parentElement?.querySelector('input, select') as HTMLInputElement | HTMLSelectElement;
};

const clickSaveMetric = () => {
  fireEvent.click(screen.getByText('SAVE METRIC'));
};

const clickDeleteMetric = () => {
  const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
  fireEvent.click(deleteButtons[deleteButtons.length - 1]);
};

const openCreateForm = async () => {
  renderMetricsManager();
  await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/metrics'));
  fireEvent.click(screen.getByRole('button', { name: /add/i }));
};

const openEditForm = async () => {
  renderMetricsManager();
  await screen.findByText('cpu.load');
  fireEvent.click(screen.getByText('cpu.load'));
  await screen.findByRole('button', { name: /save metric/i });
};

describe('MetricsManager', () => {
  beforeEach(() => {
    mocks.apiGet.mockReset();
    mocks.apiPost.mockReset();
    mocks.apiDelete.mockReset();
    setupApiGet();
    mocks.apiPost.mockResolvedValue({ ok: true });
    mocks.apiDelete.mockResolvedValue({ ok: true });
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('initial loading', () => {
    it('does not render metrics before the initial request resolves and then shows the metric list', async () => {
      const metricsDeferred = createDeferred<MetricDef[]>();
      mocks.apiGet.mockImplementation((endpoint: string) => {
        if (endpoint === '/metrics') return metricsDeferred.promise;
        if (endpoint === '/hardware') return Promise.resolve(hardwareModels);
        if (endpoint === '/metrics/cpu.load/usage') return Promise.resolve(usageData);
        if (endpoint === '/metrics/mem.usage/usage') return Promise.resolve({ count: 0, cis: [] });
        return Promise.reject(new Error(`Unhandled GET ${endpoint}`));
      });

      renderMetricsManager();

      expect(screen.queryByText('cpu.load')).not.toBeInTheDocument();
      expect(screen.getByText(/select a metric to edit/i)).toBeInTheDocument();

      metricsDeferred.resolve([metricA, metricB]);

      expect(await screen.findByText('cpu.load')).toBeInTheDocument();
      expect(screen.getByText('mem.usage')).toBeInTheDocument();
    });

    it('logs an error and keeps the editor empty when the initial metrics load fails', async () => {
      mocks.apiGet.mockImplementation(async (endpoint: string) => {
        if (endpoint === '/metrics') throw new Error('metrics failed');
        if (endpoint === '/hardware') return hardwareModels;
        throw new Error(`Unhandled GET ${endpoint}`);
      });

      renderMetricsManager();

      await waitFor(() => {
        expect(console.error).toHaveBeenCalled();
      });

      expect(screen.getByText(/select a metric to edit/i)).toBeInTheDocument();
      expect(screen.queryByText('cpu.load')).not.toBeInTheDocument();
    });
  });

  describe('create flow', () => {
    it('opens the create form with default values', async () => {
      await openCreateForm();

      expect(screen.getByText('New Metric')).toBeInTheDocument();
      expect((getInputByLabel(/protocol/i) as HTMLSelectElement).value).toBe('SNMP');
      expect((getInputByLabel(/data type/i) as HTMLSelectElement).value).toBe('INTEGER');
      expect(screen.getByText(/no models selected/i)).toBeInTheDocument();
    });

    it('creates a new metric on the happy path', async () => {
      await openCreateForm();

      fireEvent.change(getInputByLabel(/metric id/i), { target: { value: 'temp.sensor' } });
      fireEvent.change(getInputByLabel(/description/i), { target: { value: 'Temperature sensor metric' } });
      fireEvent.change(screen.getByPlaceholderText(/examples: \.1\.3\.6\.1/i), { target: { value: '.1.3.6.1.4.1.9.9.13.1' } });
      fireEvent.change(screen.getByPlaceholderText(/target brands/i), { target: { value: 'Cisco, Dell' } });
      fireEvent.change(screen.getByPlaceholderText(/target layers/i), { target: { value: 'INFRASTRUCTURE, EDGE' } });

      const numberInputs = screen.getAllByRole('spinbutton');
      fireEvent.change(numberInputs[0], { target: { value: '65' } });
      fireEvent.change(numberInputs[1], { target: { value: '85' } });

      fireEvent.change(getInputByLabel(/quick add model/i), { target: { value: 'ASR1001' } });

      clickSaveMetric();

      await waitFor(() => {
        expect(mocks.apiPost).toHaveBeenCalledWith('/metrics', expect.objectContaining({
          id: 'temp.sensor',
          protocol: 'SNMP',
          dataType: 'INTEGER',
          criticality: 1,
          description: 'Temperature sensor metric',
          oid: '.1.3.6.1.4.1.9.9.13.1',
          warning: 65,
          critical: 85,
          applicable_to: expect.objectContaining({
            brands: ['Cisco', 'Dell'],
            models: ['ASR1001'],
            layers: ['INFRASTRUCTURE', 'EDGE'],
            names: [],
            excluded_names: [],
          }),
        }));
      });

      expect(window.alert).toHaveBeenCalledWith('Metric Saved');
      await waitFor(() => {
        expect(mocks.apiGet).toHaveBeenCalledWith('/metrics');
      });
      await waitFor(() => {
        expect(mocks.apiGet).toHaveBeenCalledWith('/nodes');
      });
      expect(screen.getByText(/select a metric to edit/i)).toBeInTheDocument();
    });

    it('sends null thresholds when warning and critical are left blank', async () => {
      await openCreateForm();

      fireEvent.change(getInputByLabel(/metric id/i), { target: { value: 'disk.health' } });
      fireEvent.change(screen.getByPlaceholderText(/examples: \.1\.3\.6\.1/i), { target: { value: '.1.3.6.1.4.1.2021.9.1.9.1' } });

      clickSaveMetric();

      await waitFor(() => {
        expect(mocks.apiPost).toHaveBeenCalledWith('/metrics', expect.objectContaining({
          id: 'disk.health',
          warning: null,
          critical: null,
        }));
      });
    });

    it('shows an alert when saving fails', async () => {
      mocks.apiPost.mockRejectedValueOnce(new Error('save failed'));
      await openCreateForm();

      fireEvent.change(getInputByLabel(/metric id/i), { target: { value: 'packet.loss' } });
      clickSaveMetric();

      await waitFor(() => {
        expect(window.alert).toHaveBeenCalledWith('Error saving metric');
      });
      expect(screen.getByText('New Metric')).toBeInTheDocument();
    });

    it('shows save pending state, guards duplicate submission, and refetches metrics and nodes', async () => {
      const saveDeferred = createDeferred<{ ok: boolean }>();
      mocks.apiPost.mockReturnValueOnce(saveDeferred.promise);
      await openCreateForm();
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/nodes'));
      mocks.apiGet.mockClear();

      fireEvent.change(getInputByLabel(/metric id/i), { target: { value: 'temp.sensor' } });
      clickSaveMetric();

      expect(await screen.findByText(/saving metric and reconciling affected cis/i)).toBeInTheDocument();
      const saveButton = screen.getByRole('button', { name: /save metric/i });
      expect(saveButton).toBeDisabled();

      fireEvent.click(saveButton);
      expect(mocks.apiPost).toHaveBeenCalledTimes(1);

      saveDeferred.resolve({ ok: true });

      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/metrics'));
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/nodes'));
      expect(screen.getByText(/select a metric to edit/i)).toBeInTheDocument();
    });

    it('handles duplicate save responses with a clear message and refreshes metrics and nodes', async () => {
      mocks.apiPost.mockRejectedValueOnce({
        status: 409,
        message: { message: 'Metric operation already in progress', metric_id: 'temp.sensor' },
      });
      await openCreateForm();
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/nodes'));
      mocks.apiGet.mockClear();

      fireEvent.change(getInputByLabel(/metric id/i), { target: { value: 'temp.sensor' } });
      clickSaveMetric();

      expect(await screen.findByText(/metric operation already in progress/i)).toBeInTheDocument();
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/metrics'));
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/nodes'));
    });
  });

  describe('edit flow', () => {
    it('loads a metric into the editor and renders its applicability criteria', async () => {
      await openEditForm();

      expect(screen.getByText('Edit Metric')).toBeInTheDocument();
      expect(screen.getByDisplayValue('cpu.load')).toBeDisabled();
      expect(screen.getByDisplayValue('CPU load metric')).toBeInTheDocument();
      expect((getInputByLabel(/threshold rule/i) as HTMLSelectElement).value).toBe('<=');
      expect(screen.getByDisplayValue('55')).toBeInTheDocument();
      expect(screen.getByDisplayValue('25')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Cisco')).toBeInTheDocument();
      expect(screen.getByDisplayValue('INFRASTRUCTURE')).toBeInTheDocument();
      // router-01 is shown as a chip (Quick Add Explicit CIs), not as an input display value
      expect(screen.getAllByText('router-01').length).toBeGreaterThan(0);
      expect(screen.getAllByText(/cisco asr1001/i).length).toBeGreaterThan(0);
      expect(mocks.apiGet).toHaveBeenCalledWith('/metrics/cpu.load');
    });

    it('edits an existing metric and saves the updated payload', async () => {
      await openEditForm();

      fireEvent.change(screen.getByDisplayValue('CPU load metric'), { target: { value: 'Updated CPU metric' } });
      fireEvent.change(screen.getByPlaceholderText(/target brands/i), { target: { value: 'Cisco, Juniper' } });

      clickSaveMetric();

      await waitFor(() => {
        expect(mocks.apiPost).toHaveBeenCalledWith('/metrics', expect.objectContaining({
          id: 'cpu.load',
          description: 'Updated CPU metric',
          applicable_to: expect.objectContaining({
            brands: ['Cisco', 'Juniper'],
            models: ['ASR1001'],
          }),
        }));
      });

      expect(window.alert).toHaveBeenCalledWith('Metric Saved');
    });

    it('closes the editor when cancel is clicked', async () => {
      await openEditForm();

      fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

      expect(screen.getByText(/select a metric to edit/i)).toBeInTheDocument();
    });
  });

  describe('usage preview', () => {
    it('shows usage loading first and then renders the associated CIs table', async () => {
      const usageDeferred = createDeferred<typeof usageData>();
      mocks.apiGet.mockImplementation((endpoint: string) => {
        if (endpoint === '/metrics') return Promise.resolve([metricA, metricB]);
        if (endpoint === '/metrics/cpu.load') return Promise.resolve(metricADetail);
        if (endpoint === '/metrics/mem.usage') return Promise.resolve(metricB);
        if (endpoint === '/hardware') return Promise.resolve(hardwareModels);
        if (endpoint === '/metrics/cpu.load/usage') return usageDeferred.promise;
        if (endpoint === '/metrics/mem.usage/usage') return Promise.resolve({ count: 0, cis: [] });
        return Promise.reject(new Error(`Unhandled GET ${endpoint}`));
      });

      renderMetricsManager();
      fireEvent.click(await screen.findByText('cpu.load'));

      await screen.findByText('Edit Metric');
      expect(await screen.findByText(/loading coverage/i)).toBeInTheDocument();

      usageDeferred.resolve(usageData);

      expect(await screen.findByText('router-01')).toBeInTheDocument();
      expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
      expect(screen.getByText('router-02')).toBeInTheDocument();
    });

    it('shows the empty usage state when no CIs match the metric', async () => {
      setupApiGet({ usage: { 'cpu.load': { count: 0, cis: [] }, 'mem.usage': { count: 0, cis: [] } } });

      await openEditForm();

      expect(await screen.findByText(/no cis currently match these criteria/i)).toBeInTheDocument();
    });

    it('auto-detects the data type from the validation endpoint', async () => {
      mocks.apiPost.mockResolvedValueOnce({ success: true, value: '42', detectedType: 'FLOAT' });
      await openCreateForm();

      fireEvent.change(screen.getByPlaceholderText(/examples: \.1\.3\.6\.1/i), { target: { value: '.1.3.6.1.2.1.1.5.0' } });
      fireEvent.change(screen.getByPlaceholderText(/test ip/i), { target: { value: '192.168.0.10' } });
      fireEvent.change(screen.getByPlaceholderText(/community/i), { target: { value: 'private' } });
      fireEvent.click(screen.getByRole('button', { name: /auto-detect type/i }));

      await waitFor(() => {
        expect(mocks.apiPost).toHaveBeenCalledWith('/metrics/validate', {
          ip: '192.168.0.10',
          community: 'private',
          oid: '.1.3.6.1.2.1.1.5.0',
        });
      });

      expect(await screen.findByText(/value: 42 \(detected: float\)/i)).toBeInTheDocument();
      expect((getInputByLabel(/data type/i) as HTMLSelectElement).value).toBe('FLOAT');
    });

    it('requires both IP and OID before running validation', async () => {
      await openCreateForm();

      fireEvent.click(screen.getByRole('button', { name: /auto-detect type/i }));

      expect(window.alert).toHaveBeenCalledWith('IP and OID required');
      expect(mocks.apiPost).not.toHaveBeenCalled();
    });

    it('shows an alert when validation fails', async () => {
      mocks.apiPost.mockRejectedValueOnce(new Error('validation failed'));
      await openCreateForm();

      fireEvent.change(screen.getByPlaceholderText(/examples: \.1\.3\.6\.1/i), { target: { value: '.1.3.6.1.2.1.1.5.0' } });
      fireEvent.change(screen.getByPlaceholderText(/test ip/i), { target: { value: '192.168.0.10' } });
      fireEvent.click(screen.getByRole('button', { name: /auto-detect type/i }));

      await waitFor(() => {
        expect(window.alert).toHaveBeenCalledWith('Test Failed');
      });
    });
  });

  describe('delete and association removal', () => {
    it('deletes a metric when the user confirms the action', async () => {
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(true);
      mocks.apiGet.mockClear();

      clickDeleteMetric();

      await waitFor(() => {
        expect(mocks.apiGet).toHaveBeenCalledWith('/metrics/cpu.load/usage');
      });
      expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("This action cannot be undone."));

      await waitFor(() => {
        expect(mocks.apiDelete).toHaveBeenCalledWith('/metrics/cpu.load');
      });
    });

    it('shows delete pending state, guards duplicate deletion, clears stale selection, and refetches metrics and nodes', async () => {
      const usageDeferred = createDeferred<any>();
      const deleteDeferred = createDeferred<{ ok: boolean }>();
      mocks.apiGet.mockImplementation(async (endpoint: string) => {
        if (endpoint === '/metrics') return [metricA, metricB];
        if (endpoint === '/metrics/cpu.load') return metricADetail;
        if (endpoint === '/hardware') return hardwareModels;
        if (endpoint === '/metrics/cpu.load/usage') return usageDeferred.promise;
        if (endpoint === '/metrics/mem.usage/usage') return { count: 0, cis: [] };
        if (endpoint === '/nodes') return [];
        throw new Error(`Unhandled GET ${endpoint}`);
      });
      mocks.apiDelete.mockReturnValueOnce(deleteDeferred.promise);
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(true);
      mocks.apiGet.mockClear();

      clickDeleteMetric();

      expect(await screen.findByText(/checking metric usage before deletion/i)).toBeInTheDocument();
      const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
      const deleteButton = deleteButtons[deleteButtons.length - 1];
      expect(deleteButton).toBeDisabled();
      fireEvent.click(deleteButton);
      expect(mocks.apiGet).toHaveBeenCalledTimes(1);
      expect(mocks.apiDelete).not.toHaveBeenCalled();

      usageDeferred.resolve(usageData);
      expect(await screen.findByText(/deleting metric and removing assignments/i)).toBeInTheDocument();
      expect(mocks.apiDelete).toHaveBeenCalledTimes(1);

      deleteDeferred.resolve({ ok: true });

      await waitFor(() => expect(screen.getByText(/select a metric to edit/i)).toBeInTheDocument());
      expect(screen.queryByText('Edit Metric')).not.toBeInTheDocument();
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/metrics'));
      await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith('/nodes'));
    });

    it('clears delete pending state but keeps the selected metric when delete fails', async () => {
      const deleteDeferred = createDeferred<never>();
      mocks.apiDelete.mockReturnValueOnce(deleteDeferred.promise);
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(true);

      clickDeleteMetric();
      expect(await screen.findByText(/deleting metric and removing assignments/i)).toBeInTheDocument();

      deleteDeferred.reject(new Error('delete failed'));

      await waitFor(() => expect(window.alert).toHaveBeenCalledWith('Error deleting metric'));
      expect(screen.queryByText(/deleting metric and removing assignments/i)).not.toBeInTheDocument();
      expect(screen.getByText('Edit Metric')).toBeInTheDocument();
      expect(screen.getByDisplayValue('cpu.load')).toBeInTheDocument();
    });

    it('does not delete a metric when the user cancels the confirmation', async () => {
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(false);
      mocks.apiGet.mockClear();

      clickDeleteMetric();

      await waitFor(() => {
        expect(mocks.apiGet).toHaveBeenCalledWith('/metrics/cpu.load/usage');
      });
      expect(mocks.apiDelete).not.toHaveBeenCalled();
      await waitFor(() => expect(screen.queryByText(/checking metric usage before deletion/i)).not.toBeInTheDocument());
      const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
      expect(deleteButtons[deleteButtons.length - 1]).not.toBeDisabled();
    });

    it('shows an alert when checking metric usage for delete fails', async () => {
      await openEditForm();
      mocks.apiGet.mockImplementation(async (endpoint: string) => {
        if (endpoint === '/metrics') return [metricA, metricB];
        if (endpoint === '/hardware') return hardwareModels;
        if (endpoint === '/metrics/cpu.load/usage') throw new Error('usage failed');
        if (endpoint === '/metrics/mem.usage/usage') return { count: 0, cis: [] };
        throw new Error(`Unhandled GET ${endpoint}`);
      });

      clickDeleteMetric();

      await waitFor(() => {
        expect(window.alert).toHaveBeenCalledWith('Error checking metric usage');
      });
      await waitFor(() => expect(screen.queryByText(/checking metric usage before deletion/i)).not.toBeInTheDocument());
      const deleteButtons = screen.getAllByRole('button', { name: /delete/i });
      expect(deleteButtons[deleteButtons.length - 1]).not.toBeDisabled();
    });

    it('does not remove an associated CI when confirm returns false', async () => {
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(false);
      mocks.apiPost.mockClear();

      const deleteButtons = await screen.findAllByTitle('Remove specific association');
      fireEvent.click(deleteButtons[0]);

      expect(mocks.apiPost).not.toHaveBeenCalled();
    });

    it('removes an associated CI and persists excluded names when confirm returns true', async () => {
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(true);

      const deleteButtons = await screen.findAllByTitle('Remove specific association');
      fireEvent.click(deleteButtons[0]);

      await waitFor(() => {
        expect(mocks.apiPost).toHaveBeenCalledWith('/metrics', expect.objectContaining({
          id: 'cpu.load',
          applicable_to: {
            brands: ['Cisco'],
            models: ['ASR1001'],
            layers: ['INFRASTRUCTURE'],
            names: [],
            excluded_names: ['router-02', 'router-01', 'ci-1'],
          },
        }));
      });

      expect(window.alert).not.toHaveBeenCalledWith('Metric Saved');
      expect(screen.getByText('Edit Metric')).toBeInTheDocument();
    });

    it('keeps draft applicability edits when excluding an associated CI', async () => {
      await openEditForm();
      vi.mocked(window.confirm).mockReturnValueOnce(true);
      mocks.apiPost.mockClear();

      fireEvent.change(screen.getByDisplayValue('CPU load metric'), {
        target: { value: 'Unsaved draft description' },
      });
      fireEvent.change(screen.getByPlaceholderText(/target brands/i), {
        target: { value: 'Cisco, Juniper' },
      });
      fireEvent.change(screen.getByPlaceholderText(/target layers/i), {
        target: { value: 'INFRASTRUCTURE, EDGE' },
      });
      fireEvent.change(getInputByLabel(/quick add model/i), { target: { value: 'R750' } });

      const deleteButtons = await screen.findAllByTitle('Remove specific association');
      fireEvent.click(deleteButtons[0]);

      await waitFor(() => {
        expect(mocks.apiPost).toHaveBeenCalledWith('/metrics', expect.objectContaining({
          id: 'cpu.load',
          description: 'Unsaved draft description',
          applicable_to: {
            brands: ['Cisco', 'Juniper'],
            models: ['ASR1001', 'R750'],
            layers: ['INFRASTRUCTURE', 'EDGE'],
            names: [],
            excluded_names: ['router-02', 'router-01', 'ci-1'],
          },
        }));
      });

      expect(screen.getByText('Edit Metric')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Unsaved draft description')).toBeInTheDocument();
      expect(screen.getByDisplayValue('Cisco, Juniper')).toBeInTheDocument();
      expect(screen.getByDisplayValue('INFRASTRUCTURE, EDGE')).toBeInTheDocument();
      expect(window.alert).not.toHaveBeenCalledWith('Metric Saved');
    });
  });
});
