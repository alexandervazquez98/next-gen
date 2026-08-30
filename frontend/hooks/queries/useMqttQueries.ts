/**
 * MQTT Monitoring Frontend (Issue #385) — read hooks.
 *
 * PR1 scope: six read hooks that mirror the API surface declared in
 * `services/queryResources.ts`. The two polling hooks (`useMqttReadingsQuery`
 * and `useMqttStatusQuery`) opt into the same `refetchInterval` cadence used
 * by `useSystemStatusQuery` and `useActiveEventsQuery` (5000 ms for Bridge
 * Status, 5000 ms for latest readings — see design §State Management).
 *
 * Disabled hooks — `useMqttDeviceMetricsQuery` and
 * `useMqttMappingThresholdsQuery` — accept an `enabled` flag so callers can
 * prevent fetching until a row is expanded or until the mapping reaches
 * `APPROVED` status. PR1 only exercises the read hooks; the disabled
 * thresholds hook is wired in PR2.
 */
import { useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { queryKeys } from "../../services/queryKeys";
import {
  fetchMqttDevices,
  fetchMqttDeviceMetrics,
  fetchMqttReadings,
  fetchMqttMappingThresholds,
  fetchMqttMappings,
  fetchMqttStatus,
} from "../../services/queryResources";
import type {
  MqttMappingResponse,
  MqttMappingThresholds,
  MqttRawDeviceResponse,
  MqttRawMetricResponse,
  MqttRuntimeStatus,
} from "../../types";

const MQTT_READINGS_REFETCH_MS = 5_000;
const MQTT_STATUS_REFETCH_MS = 5_000;

export const useMqttDevicesQuery = (
  options?: Partial<UseQueryOptions<MqttRawDeviceResponse[]>>,
) =>
  useQuery({
    queryKey: queryKeys.mqttDevices(),
    queryFn: ({ signal }) => fetchMqttDevices({ signal }),
    ...options,
  });

export const useMqttDeviceMetricsQuery = (
  deviceId: string | null,
  options?: Partial<UseQueryOptions<MqttRawMetricResponse[]>> & { enabled?: boolean },
) =>
  useQuery({
    queryKey: queryKeys.mqttDeviceMetrics(deviceId),
    queryFn: ({ signal }) => {
      if (!deviceId) {
        return Promise.resolve([] as MqttRawMetricResponse[]);
      }
      return fetchMqttDeviceMetrics(deviceId, { signal });
    },
    enabled: options?.enabled ?? Boolean(deviceId),
    ...options,
  });

export interface UseMqttReadingsQueryOptions {
  limit?: number;
  refetchInterval?: number | false;
}

export const useMqttReadingsQuery = ({
  limit = 100,
  refetchInterval = MQTT_READINGS_REFETCH_MS,
}: UseMqttReadingsQueryOptions = {}) =>
  useQuery({
    queryKey: queryKeys.mqttReadings({ limit }),
    queryFn: ({ signal }) => fetchMqttReadings({ limit, signal }),
    refetchInterval,
  });

export interface UseMqttStatusQueryOptions {
  refetchInterval?: number | false;
}

export const useMqttStatusQuery = ({
  refetchInterval = MQTT_STATUS_REFETCH_MS,
}: UseMqttStatusQueryOptions = {}) =>
  useQuery({
    queryKey: queryKeys.mqttStatus(),
    queryFn: ({ signal }) => fetchMqttStatus({ signal }),
    refetchInterval,
  });

export interface UseMqttMappingsQueryOptions {
  status?: string;
}

export const useMqttMappingsQuery = ({ status }: UseMqttMappingsQueryOptions = {}) =>
  useQuery({
    queryKey: queryKeys.mqttMappings({ status }),
    queryFn: ({ signal }) => fetchMqttMappings({ status, signal }),
  });

export const useMqttMappingThresholdsQuery = (
  mappingId: string | null,
  options?: Partial<UseQueryOptions<MqttMappingThresholds>> & { enabled?: boolean },
) =>
  useQuery({
    queryKey: queryKeys.mqttMappingThresholds(mappingId),
    queryFn: ({ signal }) => {
      if (!mappingId) {
        return Promise.resolve({} as MqttMappingThresholds);
      }
      return fetchMqttMappingThresholds(mappingId, { signal });
    },
    enabled: options?.enabled ?? Boolean(mappingId),
    ...options,
  });

export type {
  MqttMappingResponse,
  MqttMappingThresholds,
  MqttRawDeviceResponse,
  MqttRawMetricResponse,
  MqttRuntimeStatus,
};
