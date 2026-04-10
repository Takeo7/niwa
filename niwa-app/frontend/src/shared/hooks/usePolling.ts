import { useEffect, useRef, useState, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

export function usePolling() {
  const qc = useQueryClient();
  const [disconnected, setDisconnected] = useState(false);
  const failCount = useRef(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const res = await fetch('/api/stats', { credentials: 'same-origin' });
      if (res.ok) {
        failCount.current = 0;
        if (disconnected) setDisconnected(false);
        // Silently invalidate key queries
        qc.invalidateQueries({ queryKey: ['tasks'] });
        qc.invalidateQueries({ queryKey: ['projects'] });
        qc.invalidateQueries({ queryKey: ['dashboard'] });
        qc.invalidateQueries({ queryKey: ['stats'] });
        qc.invalidateQueries({ queryKey: ['kanban'] });
      } else {
        failCount.current++;
      }
    } catch {
      failCount.current++;
    }
    if (failCount.current >= 3) {
      setDisconnected(true);
    }
  }, [qc, disconnected]);

  useEffect(() => {
    intervalRef.current = setInterval(poll, 15000);

    const onFocus = () => {
      if (!intervalRef.current) {
        intervalRef.current = setInterval(poll, 15000);
      }
      // Immediate refresh on tab focus
      poll();
    };
    const onBlur = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    window.addEventListener('focus', onFocus);
    window.addEventListener('blur', onBlur);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('blur', onBlur);
    };
  }, [poll]);

  return { disconnected };
}
