import { optimizeForPool } from "./pool.js";

self.onmessage = (e) => {
  const { key, input } = e.data;
  try {
    self.postMessage({ key, result: optimizeForPool(input) });
  } catch (err) {
    self.postMessage({ key, error: String(err?.message ?? err) });
  }
};
