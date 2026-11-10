"use client";
import { useCallback, useEffect, useState } from "react";
import { blobUrl } from "@/lib/api";

export function useBlobUrl(path: string | null | undefined) {
  const [retryCount, setRetryCount] = useState(0);
  const key = path ? `${path}:${retryCount}` : null;
  const [result, setResult] = useState<{
    key: string | null; url: string | null; error: string | null; loading: boolean;
  }>({ key: null, url: null, error: null, loading: false });
  useEffect(() => {
    if (!path || !key) {
      setResult({ key: null, url: null, error: null, loading: false });
      return;
    }
    let revoked: string | null = null;
    let cancelled = false;
    setResult({ key, url: null, error: null, loading: true });
    blobUrl(path)
      .then((url) => {
        if (cancelled) URL.revokeObjectURL(url);
        else {
          revoked = url;
          setResult({ key, url, error: null, loading: false });
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setResult({ key, url: null, error: e instanceof Error ? e.message : "The file could not be loaded.", loading: false });
        }
      });
    return () => { cancelled = true; if (revoked) URL.revokeObjectURL(revoked); };
  }, [key, path]);
  const retry = useCallback(() => setRetryCount((count) => count + 1), []);
  const current = result.key === key;
  return {
    url: current ? result.url : null,
    error: current ? result.error : null,
    loading: path ? !current || result.loading : false,
    retry,
  };
}
