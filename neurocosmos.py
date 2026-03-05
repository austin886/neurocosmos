import subprocess
import json
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# ================================
# DEFAULT CONFIGURATION
# ================================

DEFAULT_UNITS = 10000
DEFAULT_OPTIMIZATION_FACTOR = 0.82
DEFAULT_COST_PER_KWH = 0.12
HOURS_PER_YEAR = 24 * 365  # 8760


# ================================
# REAL GPU TELEMETRY
# ================================

def get_gpu_telemetry():
    """
    Pulls real GPU telemetry using nvidia-smi.
    Returns a dict with name, temperature, power, memory used/total, utilization.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,power.draw,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True,
            text=True,
            check=True
        )

        output = result.stdout.strip()
        parts = [p.strip() for p in output.split(",")]

        if len(parts) < 6:
            raise ValueError(f"Unexpected nvidia-smi output: {output}")

        return {
            "name": parts[0],
            "temperature": float(parts[1]),
            "power": float(parts[2]),
            "memory_used": float(parts[3]),
            "memory_total": float(parts[4]),
            "utilization": float(parts[5])
        }

    except FileNotFoundError:
        return {"error": "nvidia-smi not found. Install NVIDIA drivers / ensure nvidia-smi works in PowerShell."}
    except Exception as e:
        return {"error": f"Error getting GPU telemetry: {e}"}


# ================================
# IMPACT CALCS
# ================================

def calculate_enterprise_impact(watts_saved_per_gpu: float, units: int, cost_per_kwh: float):
    total_watts_saved = watts_saved_per_gpu * units      # W
    total_kw_saved = total_watts_saved / 1000.0          # kW
    annual_kwh_saved = total_kw_saved * HOURS_PER_YEAR   # kWh/year
    annual_dollar_savings = annual_kwh_saved * cost_per_kwh
    return annual_kwh_saved, annual_dollar_savings


def compute_snapshot(units: int, opt_factor: float, cost_per_kwh: float):
    gpu = get_gpu_telemetry()

    if "error" in gpu:
        return {"ok": False, "error": gpu["error"]}

    optimized_power = gpu["power"] * opt_factor
    optimized_temp = gpu["temperature"] * opt_factor
    watts_saved = gpu["power"] - optimized_power

    annual_kwh_saved, annual_dollar_savings = calculate_enterprise_impact(watts_saved, units, cost_per_kwh)

    idle_warning = (gpu["utilization"] < 10 and gpu["power"] < 80)

    return {
        "ok": True,
        "baseline": {
            "gpu": gpu["name"],
            "utilization_pct": gpu["utilization"],
            "temperature_c": gpu["temperature"],
            "power_w": gpu["power"],
            "vram_used_mib": gpu["memory_used"],
            "vram_total_mib": gpu["memory_total"],
        },
        "optimized": {
            "opt_factor": opt_factor,
            "optimized_power_w": optimized_power,
            "optimized_temp_c": optimized_temp,
            "watts_saved_per_gpu": watts_saved,
        },
        "enterprise": {
            "units": units,
            "cost_per_kwh": cost_per_kwh,
            "annual_kwh_saved": annual_kwh_saved,
            "annual_dollar_saved": annual_dollar_savings,
        },
        "idle_warning": idle_warning
    }


# ================================
# CONSOLE MODE
# ================================

def run_console(units: int, opt_factor: float, cost_per_kwh: float):
    snap = compute_snapshot(units, opt_factor, cost_per_kwh)

    if not snap["ok"]:
        print(snap["error"])
        return

    b = snap["baseline"]
    o = snap["optimized"]
    e = snap["enterprise"]

    print("\n" + "=" * 46)
    print("NEUROCOSMOS | HYBRID TELEMETRY + OPTIMIZATION")
    print("=" * 46)

    if snap["idle_warning"]:
        print("\nNOTE: GPU appears idle (low utilization/power).")
        print("For a stronger demo run: start a game, 4K video, or GPU workload, then re-run.")

    print("\n[BASELINE | REAL GPU TELEMETRY]")
    print(f"GPU                : {b['gpu']}")
    print(f"Utilization         : {b['utilization_pct']:.0f} %")
    print(f"Temperature         : {b['temperature_c']:.1f} °C")
    print(f"Power Draw          : {b['power_w']:.2f} W")
    print(f"VRAM                : {b['vram_used_mib']:.0f} / {b['vram_total_mib']:.0f} MiB")

    print("\n[OPTIMIZATION LAYER | SIMULATED POLICY]")
    print(f"Optimized Power     : {o['optimized_power_w']:.2f} W")
    print(f"Optimized Temp      : {o['optimized_temp_c']:.2f} °C")
    print(f"Watts Saved / GPU   : {o['watts_saved_per_gpu']:.2f} W")

    print("\n[ENTERPRISE IMPACT | FLEET PROJECTION]")
    print(f"Fleet Size          : {e['units']:,} GPUs")
    print(f"Annual Energy Saved : {e['annual_kwh_saved']:,.0f} kWh")
    print(f"Annual $ Saved      : ${e['annual_dollar_saved']:,.2f}")

    print("\n" + "=" * 46 + "\n")


# ================================
# WEB UI MODE (PORT 8787)
# ================================

HTML_PAGE = """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>NeuroCosmos | Web UI</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:24px; background:#0b0f17; color:#e8eefc;}
    .card{background:#121a2a; border:1px solid #223050; border-radius:14px; padding:16px; margin:12px 0;}
    .row{display:flex; gap:12px; flex-wrap:wrap;}
    .kpi{flex:1; min-width:240px;}
    .muted{color:#a9b7d6;}
    .big{font-size:28px; font-weight:700;}
    input{background:#0b0f17; color:#e8eefc; border:1px solid #223050; border-radius:10px; padding:10px; width:160px;}
    button{background:#2b63ff; color:white; border:none; border-radius:10px; padding:10px 14px; cursor:pointer; font-weight:600;}
    button:hover{opacity:.92;}
    code{background:#0b0f17; padding:2px 6px; border-radius:8px; border:1px solid #223050;}
    .warn{background:#2a1b12; border:1px solid #6b3a22;}
  </style>
</head>
<body>
  <h1 style="margin:0 0 6px 0;">NeuroCosmos</h1>
  <div class="muted">Hybrid Telemetry + Optimization • Live on <code>localhost:8787</code></div>

  <div class="card">
    <div class="row">
      <div class="kpi">
        <div class="muted">Fleet Size</div>
        <input id="units" type="number" value="10000" min="1" step="1" />
      </div>
      <div class="kpi">
        <div class="muted">$/kWh</div>
        <input id="cost" type="number" value="0.12" min="0" step="0.01" />
      </div>
      <div class="kpi">
        <div class="muted">Optimization Factor</div>
        <input id="opt" type="number" value="0.82" min="0.5" max="1.0" step="0.01" />
      </div>
      <div class="kpi" style="display:flex; align-items:flex-end; gap:10px;">
        <button onclick="refreshNow()">Refresh Now</button>
      </div>
    </div>
  </div>

  <div id="warning" class="card warn" style="display:none;">
    <b>NOTE:</b> GPU appears idle (low utilization/power). Start a game, 4K video, or GPU workload for a stronger demo run.
  </div>

  <div class="card">
    <div class="muted">Baseline • Real GPU Telemetry</div>
    <div class="big" id="gpuName">—</div>
    <div class="row">
      <div class="kpi"><div class="muted">Utilization</div><div class="big" id="util">—</div></div>
      <div class="kpi"><div class="muted">Power</div><div class="big" id="power">—</div></div>
      <div class="kpi"><div class="muted">Temp</div><div class="big" id="temp">—</div></div>
      <div class="kpi"><div class="muted">VRAM</div><div class="big" id="vram">—</div></div>
    </div>
  </div>

  <div class="card">
    <div class="muted">Optimization Layer • Simulated Policy</div>
    <div class="row">
      <div class="kpi"><div class="muted">Watts Saved / GPU</div><div class="big" id="saved">—</div></div>
      <div class="kpi"><div class="muted">Optimized Power</div><div class="big" id="opower">—</div></div>
      <div class="kpi"><div class="muted">Optimized Temp</div><div class="big" id="otemp">—</div></div>
    </div>
  </div>

  <div class="card">
    <div class="muted">Enterprise Impact • Fleet Projection</div>
    <div class="row">
      <div class="kpi"><div class="muted">Annual kWh Saved</div><div class="big" id="kwh">—</div></div>
      <div class="kpi"><div class="muted">Annual $ Saved</div><div class="big" id="dollars">—</div></div>
    </div>
  </div>

  <div class="muted" id="status">Loading…</div>

<script>
async function fetchData() {
  const units = document.getElementById('units').value || 10000;
  const cost = document.getElementById('cost').value || 0.12;
  const opt  = document.getElementById('opt').value  || 0.82;

  const url = `/api?units=${encodeURIComponent(units)}&cost=${encodeURIComponent(cost)}&opt=${encodeURIComponent(opt)}`;
  const res = await fetch(url);
  return await res.json();
}

function fmt(n, digits=0){
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString(undefined, {maximumFractionDigits:digits, minimumFractionDigits:digits});
}

async function refreshNow(){
  try{
    const data = await fetchData();
    if(!data.ok){
      document.getElementById('status').textContent = data.error || "Error";
      return;
    }

    document.getElementById('warning').style.display = data.idle_warning ? 'block' : 'none';

    const b = data.baseline;
    const o = data.optimized;
    const e = data.enterprise;

    document.getElementById('gpuName').textContent = b.gpu;
    document.getElementById('util').textContent = fmt(b.utilization_pct,0) + "%";
    document.getElementById('power').textContent = fmt(b.power_w,2) + " W";
    document.getElementById('temp').textContent = fmt(b.temperature_c,1) + " °C";
    document.getElementById('vram').textContent = fmt(b.vram_used_mib,0) + " / " + fmt(b.vram_total_mib,0) + " MiB";

    document.getElementById('saved').textContent  = fmt(o.watts_saved_per_gpu,2) + " W";
    document.getElementById('opower').textContent = fmt(o.optimized_power_w,2) + " W";
    document.getElementById('otemp').textContent  = fmt(o.optimized_temp_c,2) + " °C";

    document.getElementById('kwh').textContent    = fmt(e.annual_kwh_saved,0) + " kWh";
    document.getElementById('dollars').textContent= "$" + fmt(e.annual_dollar_saved,2);

    document.getElementById('status').textContent =
      "Live • Fleet " + fmt(e.units,0) + " • $/kWh " + fmt(e.cost_per_kwh,2) + " • Opt " + fmt(o.opt_factor,2);

  }catch(err){
    document.getElementById('status').textContent = "Error: " + err;
  }
}

refreshNow();
setInterval(refreshNow, 2000);
</script>
</body>
</html>
"""

class NeuroCosmosHandler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body_bytes: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self._send(200, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))
            return

        if parsed.path == "/api":
            qs = parse_qs(parsed.query)

            def get_float(name, default):
                try:
                    return float(qs.get(name, [default])[0])
                except Exception:
                    return float(default)

            def get_int(name, default):
                try:
                    return int(float(qs.get(name, [default])[0]))
                except Exception:
                    return int(default)

            units = max(1, get_int("units", DEFAULT_UNITS))
            cost = max(0.0, get_float("cost", DEFAULT_COST_PER_KWH))
            opt = get_float("opt", DEFAULT_OPTIMIZATION_FACTOR)
            opt = min(1.0, max(0.5, opt))

            snap = compute_snapshot(units, opt, cost)
            payload = json.dumps(snap).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", payload)
            return

        self._send(404, "text/plain; charset=utf-8", b"Not Found")


def run_web(port: int = 8787):
    server = HTTPServer(("127.0.0.1", port), NeuroCosmosHandler)
    print(f"\nNeuroCosmos Web UI running at http://127.0.0.1:{port}")
    print("Press CTRL+C to stop.\n")
    server.serve_forever()


# ================================
# ENTRY
# ================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", action="store_true", help="Run the web UI on port 8787")
    args = parser.parse_args()

    if args.web:
        run_web(8787)
    else:
        run_console(DEFAULT_UNITS, DEFAULT_OPTIMIZATION_FACTOR, DEFAULT_COST_PER_KWH)


if __name__ == "__main__":
    main()