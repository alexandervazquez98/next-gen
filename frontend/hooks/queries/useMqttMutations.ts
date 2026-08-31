/**
 * MQTT Monitoring Frontend (Issue #385) — mutation hooks.
 *
 * PR1 ships all five mutators so PR2 (`MqttMappingsTab` / confirm modal /
 * threshold form) can land without touching `useMqttMutations.ts`. Each
 * mutation:
 *   - issues the API call declared in `services/queryResources.ts`,
 *   - invalidates the `mqtt*` cache keys listed in
 *     `openspec/changes/feat-mqtt-385-frontend-ux/design.md` §State Management,
 *   - on `403`, surfaces a sonner toast that names the missing permission
 *     (`MQTT_MAPPING_MANAGE`) so the operator can request access; the prior
 *     list state is preserved because we never optimistically update.
 *
 * `systemStatus` is invalidated only on approve/revoke — per design §State
 * Management — because the KPI cards on the System Dashboard may derive from
 * mapping state downstream.
 */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  approveMqttMapping,
  createMqttMapping,
  revokeMqttMapping,
  updateMqttMapping,
  updateMqttMappingThresholds,
  type MqttMappingCreatePayload,
  type MqttMappingUpdatePayload,
} from "../../services/queryResources";
import { queryKeys } from "../../services/queryKeys";
import { ApiError } from "../../services/api";
import type { MqttMappingResponse, MqttMappingThresholds } from "../../types";

const MISSING_PERMISSION_MESSAGE = "Permission denied: MQTT_MAPPING_MANAGE";

type InvalidateKind = "approve" | "revoke" | "mapping" | "threshold";

const invalidateMqttCaches = async (queryClient: QueryClient, kind: InvalidateKind) => {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["mqtt", "mappings"] }),
    queryClient.invalidateQueries({ queryKey: ["mqtt", "mappings", undefined, "thresholds"] }),
    queryClient.invalidateQueries({ queryKey: ["mqtt", "readings"] }),
    queryClient.invalidateQueries({ queryKey: ["mqtt", "status"] }),
  ]);
  if (kind === "approve" || kind === "revoke") {
    await queryClient.invalidateQueries({ queryKey: queryKeys.systemStatus() });
  }
};

const reportPermissionError = (err: unknown): void => {
  if (err instanceof ApiError && err.status === 403) {
    toast.error(MISSING_PERMISSION_MESSAGE);
    return;
  }
  const message = err instanceof Error ? err.message : "MQTT mutation failed";
  toast.error(message);
};

export const useCreateMqttMapping = () => {
  const queryClient = useQueryClient();
  return {
    mutateAsync: async (payload: MqttMappingCreatePayload): Promise<MqttMappingResponse> => {
      try {
        const result = await createMqttMapping(payload);
        await invalidateMqttCaches(queryClient, "mapping");
        return result;
      } catch (err) {
        reportPermissionError(err);
        throw err;
      }
    },
  };
};

export const useUpdateMqttMapping = () => {
  const queryClient = useQueryClient();
  return {
    mutateAsync: async (
      mappingId: string,
      payload: MqttMappingUpdatePayload,
    ): Promise<MqttMappingResponse> => {
      try {
        const result = await updateMqttMapping(mappingId, payload);
        await invalidateMqttCaches(queryClient, "mapping");
        return result;
      } catch (err) {
        reportPermissionError(err);
        throw err;
      }
    },
  };
};

export const useApproveMqttMapping = () => {
  const queryClient = useQueryClient();
  return {
    mutateAsync: async (mappingId: string): Promise<MqttMappingResponse> => {
      try {
        const result = await approveMqttMapping(mappingId);
        await invalidateMqttCaches(queryClient, "approve");
        return result;
      } catch (err) {
        reportPermissionError(err);
        throw err;
      }
    },
  };
};

export const useRevokeMqttMapping = () => {
  const queryClient = useQueryClient();
  return {
    mutateAsync: async (mappingId: string): Promise<MqttMappingResponse> => {
      try {
        const result = await revokeMqttMapping(mappingId);
        await invalidateMqttCaches(queryClient, "revoke");
        return result;
      } catch (err) {
        reportPermissionError(err);
        throw err;
      }
    },
  };
};

export const useUpdateMqttMappingThresholds = () => {
  const queryClient = useQueryClient();
  return {
    mutateAsync: async (
      mappingId: string,
      payload: MqttMappingThresholds,
    ): Promise<MqttMappingResponse> => {
      try {
        const result = await updateMqttMappingThresholds(mappingId, payload);
        await invalidateMqttCaches(queryClient, "threshold");
        return result;
      } catch (err) {
        reportPermissionError(err);
        throw err;
      }
    },
  };
};

export const __test__ = { invalidateMqttCaches, MISSING_PERMISSION_MESSAGE };
