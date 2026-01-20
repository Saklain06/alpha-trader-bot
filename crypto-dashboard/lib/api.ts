const API_BASE = "/api";
// FORCE_CACHE_BUST: 1768846755

export async function getStatus() {
  const res = await fetch(`${API_BASE}/status`);
  return res.json();
}

export async function startBot() {
  await fetch(`${API_BASE}/start`, { method: "POST" });
}

export async function stopBot() {
  await fetch(`${API_BASE}/stop`, { method: "POST" });
}

export async function getTrades() {
  const res = await fetch(`${API_BASE}/trades`);
  return res.json();
}



