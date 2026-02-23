export const fetcher = async <T = unknown>(url: string): Promise<T> => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000); // 10s timeout
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(res.statusText);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
};
