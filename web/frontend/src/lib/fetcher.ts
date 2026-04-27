export const fetcher = async <T = unknown>(url: string): Promise<T> => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000); // 30s timeout
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(res.statusText);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
};
