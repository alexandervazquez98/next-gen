import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  AUTH_SESSION_CHANNEL,
  AUTH_SESSION_DEDUPE_MAX_KEYS,
  AUTH_SESSION_DEDUPE_TTL_MS,
  AUTH_SESSION_STORAGE_KEY,
  publishAuthSessionEvent,
  subscribeAuthSessionEvents,
} from './sessionBus';

describe('sessionBus', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    delete (window as any).BroadcastChannel;
  });

  it('publishes logout events through BroadcastChannel when available', () => {
    const channels: Array<any> = [];
    class MockBroadcastChannel {
      postMessage = vi.fn();
      close = vi.fn();
      constructor(public name: string) { channels.push(this); }
    }
    (window as any).BroadcastChannel = MockBroadcastChannel;

    const handler = vi.fn();
    const unsubscribe = subscribeAuthSessionEvents(handler);
    publishAuthSessionEvent({ type: 'logout', reason: 'manual' });

    expect(channels[0].name).toBe(AUTH_SESSION_CHANNEL);
    expect(channels[0].postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'logout', reason: 'manual', senderId: expect.any(String), timestamp: expect.any(Number),
    }));
    expect(handler).toHaveBeenCalledWith(expect.objectContaining({ type: 'logout', reason: 'manual' }));

    unsubscribe();
    expect(channels[0].close).toHaveBeenCalled();
  });

  it('receives session-expired events through the localStorage fallback', () => {
    const handler = vi.fn();
    const unsubscribe = subscribeAuthSessionEvents(handler);
    const message = { type: 'session-expired' as const, reason: 'idle_timeout', senderId: 'other-tab', timestamp: Date.now() };

    window.dispatchEvent(new StorageEvent('storage', {
      key: AUTH_SESSION_STORAGE_KEY,
      newValue: JSON.stringify(message),
    }));

    expect(handler).toHaveBeenCalledWith(message);
    unsubscribe();
  });

  it('deduplicates the same remote event delivered by BroadcastChannel and localStorage', () => {
    const channels: Array<any> = [];
    class MockBroadcastChannel {
      onmessage: ((event: MessageEvent) => void) | null = null;
      postMessage = vi.fn();
      close = vi.fn();
      constructor(public name: string) { channels.push(this); }
    }
    (window as any).BroadcastChannel = MockBroadcastChannel;

    const handler = vi.fn();
    const unsubscribe = subscribeAuthSessionEvents(handler);
    const message = {
      type: 'session-expired' as const,
      reason: 'idle_timeout',
      sessionId: 'session-123',
      senderId: 'other-tab',
      timestamp: Date.now() + 1,
    };

    channels[0].onmessage?.({ data: message } as MessageEvent);
    window.dispatchEvent(new StorageEvent('storage', {
      key: AUTH_SESSION_STORAGE_KEY,
      newValue: JSON.stringify(message),
    }));

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(message);
    unsubscribe();
  });

  it('expires remote-event dedupe keys after the TTL', () => {
    vi.useFakeTimers();
    const handler = vi.fn();
    const unsubscribe = subscribeAuthSessionEvents(handler);

    try {
      const message = {
        type: 'session-expired' as const,
        eventId: 'remote-event-ttl',
        reason: 'idle_timeout',
        senderId: 'other-tab',
        timestamp: Date.now(),
      };

      window.dispatchEvent(new StorageEvent('storage', {
        key: AUTH_SESSION_STORAGE_KEY,
        newValue: JSON.stringify(message),
      }));
      window.dispatchEvent(new StorageEvent('storage', {
        key: AUTH_SESSION_STORAGE_KEY,
        newValue: JSON.stringify(message),
      }));
      expect(handler).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(AUTH_SESSION_DEDUPE_TTL_MS + 1);
      window.dispatchEvent(new StorageEvent('storage', {
        key: AUTH_SESSION_STORAGE_KEY,
        newValue: JSON.stringify(message),
      }));

      expect(handler).toHaveBeenCalledTimes(2);
    } finally {
      unsubscribe();
      vi.useRealTimers();
    }
  });

  it('caps remote-event dedupe keys to prevent unbounded growth', () => {
    const handler = vi.fn();
    const unsubscribe = subscribeAuthSessionEvents(handler);
    const firstMessage = {
      type: 'logout' as const,
      eventId: 'remote-event-0',
      reason: 'manual',
      senderId: 'other-tab',
      timestamp: Date.now(),
    };

    for (let index = 0; index <= AUTH_SESSION_DEDUPE_MAX_KEYS; index += 1) {
      window.dispatchEvent(new StorageEvent('storage', {
        key: AUTH_SESSION_STORAGE_KEY,
        newValue: JSON.stringify({ ...firstMessage, eventId: `remote-event-${index}` }),
      }));
    }
    expect(handler).toHaveBeenCalledTimes(AUTH_SESSION_DEDUPE_MAX_KEYS + 1);

    window.dispatchEvent(new StorageEvent('storage', {
      key: AUTH_SESSION_STORAGE_KEY,
      newValue: JSON.stringify(firstMessage),
    }));

    expect(handler).toHaveBeenCalledTimes(AUTH_SESSION_DEDUPE_MAX_KEYS + 2);
    unsubscribe();
  });
});
