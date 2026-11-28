const workflow = "https://api.github.com/repos/Rkperdana/gempa-bumi-bmkg/actions/workflows/dataloka-wp-cuaca.yml";

export default {
  async scheduled(event, env) {
    const headers = {
      Authorization: `Bearer ${env.DATALOKA_ACTIONS_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "Dataloka-weather-scheduler",
      "Content-Type": "application/json",
    };
    const recent = await fetch(workflow + "/runs?branch=main&per_page=15", { headers });
    if (!recent.ok) throw new Error(`GitHub run list HTTP ${recent.status}`);
    const { workflow_runs: runs } = await recent.json();
    if (runs.some(run => run.event !== "pull_request" && run.status !== "completed")) return;
    const response = await fetch(workflow + "/dispatches", {
      method: "POST", headers, body: JSON.stringify({ ref: "main", inputs: { mode: "live" } }),
    });
    if (!response.ok) throw new Error(`GitHub dispatch HTTP ${response.status}`);
  },
};
