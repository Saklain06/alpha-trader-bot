const API_BASE = "http://localhost:8000";

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

// export async function runBacktest() {
//   const res = await fetch(`${API_BASE}/backtest`);
//   return res.json();
// }
// export async function runBacktest(params: any) {
//     const res = await fetch("http://localhost:8000/backtest", {
//       method: "POST",
//       headers: { "Content-Type": "application/json" },
//       body: JSON.stringify(params),
//     });
//     return res.json();
//   }

export async function runBacktest(params: any) {
    const res = await fetch("http://localhost:8000/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return res.json();
  }
  
  