export const AUTH_SESSION_CHANNEL = 'next-gen-auth-session';
export const AUTH_SESSION_STORAGE_KEY = 'next-gen-auth-session-event';
export const AUTH_SESSION_DEDUPE_MAX_KEYS = 256;
export const AUTH_SESSION_DEDUPE_TTL_MS = 10 * 60 * 1000;

export type AuthSessionEventType = 'logout' | 'session-expired';
export interface AuthSessionEvent {
  type: AuthSessionEventType;
  reason?: string;
  sessionId?: string;
  senderId?: string;
  timestamp?: number;
  eventId?: string;
}

type Handler = (event: AuthSessionEvent) => void;

const listeners = new Set<Handler>();
const deliveredEventKeys = new Map<string, number>();
const tabId = `tab-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
let eventSequence = 0;
let channel: BroadcastChannel | null = null;

const hasWindow = () => typeof window !== 'undefined';
const isEvent = (value: unknown): value is AuthSessionEvent => (
  !!value && typeof value === 'object' &&
  ((value as AuthSessionEvent).type === 'logout' || (value as AuthSessionEvent).type === 'session-expired')
);
const eventKey = (event: AuthSessionEvent) => event.eventId ?? [
  event.senderId ?? '',
  event.timestamp ?? '',
  event.type,
  event.reason ?? '',
  event.sessionId ?? '',
].join('|');
const notify = (event: AuthSessionEvent) => listeners.forEach(listener => listener(event));

function pruneDeliveredEventKeys(now = Date.now()) {
  for (const [key, deliveredAt] of deliveredEventKeys) {
    if (now - deliveredAt > AUTH_SESSION_DEDUPE_TTL_MS) {
      deliveredEventKeys.delete(key);
    }
  }

  while (deliveredEventKeys.size >= AUTH_SESSION_DEDUPE_MAX_KEYS) {
    const oldestKey = deliveredEventKeys.keys().next().value;
    if (!oldestKey) break;
    deliveredEventKeys.delete(oldestKey);
  }
}

const notifyRemoteOnce = (event: AuthSessionEvent) => {
  const now = Date.now();
  pruneDeliveredEventKeys(now);
  const key = eventKey(event);
  if (deliveredEventKeys.has(key)) return;
  deliveredEventKeys.set(key, now);
  notify(event);
};

function ensureChannel(): BroadcastChannel | null {
  if (!hasWindow() || !('BroadcastChannel' in window)) return null;
  if (channel) return channel;
  channel = new BroadcastChannel(AUTH_SESSION_CHANNEL);
  channel.onmessage = ({ data }: MessageEvent<AuthSessionEvent>) => {
    if (isEvent(data) && data.senderId !== tabId) notifyRemoteOnce(data);
  };
  return channel;
}

export function publishAuthSessionEvent(event: AuthSessionEvent): void {
  if (!hasWindow()) return;
  const message = {
    ...event,
    senderId: event.senderId ?? tabId,
    timestamp: event.timestamp ?? Date.now(),
    eventId: event.eventId ?? `${tabId}-${Date.now()}-${eventSequence += 1}`,
  };
  notify(message);
  ensureChannel()?.postMessage(message);
  try {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(message));
    window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
  } catch {
    // Ignore unavailable storage.
  }
}

export function subscribeAuthSessionEvents(handler: Handler): () => void {
  if (!hasWindow()) return () => undefined;
  listeners.add(handler);
  ensureChannel();

  const onStorage = (event: StorageEvent) => {
    if (event.key !== AUTH_SESSION_STORAGE_KEY || !event.newValue) return;
    try {
      const message = JSON.parse(event.newValue) as AuthSessionEvent;
      if (isEvent(message) && message.senderId !== tabId) notifyRemoteOnce(message);
    } catch {
      // Ignore malformed cross-tab payloads.
    }
  };

  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(handler);
    window.removeEventListener('storage', onStorage);
    if (listeners.size === 0 && channel) {
      channel.close();
      channel = null;
    }
  };
}
