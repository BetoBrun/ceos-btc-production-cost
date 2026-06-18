#!/usr/bin/env python3
"""
CEOS BTC Production Cost — atualizador diario.

DATA_MODE (env):
  compute  (default) — hashrate real do mempool.space + curva de eficiencia
                       calibrada nos dados publicados pelo Cambridge CBECI.
  cbeci              — CSV externo configurado via CBECI_DATA_URL (potencia GW).
  demo               — dados sinteticos (somente para testes locais).

Formula Cambridge:
  consumo_diario_kWh = potencia_rede[GW] * 1e6 * 24
  custo_energia_dia  = consumo_diario_kWh * ENERGY_PRICE_USD_KWH
  custo_por_BTC      = custo_energia_dia / btc_emitidos_no_dia

BTC emitidos/dia = 144 blocos * subsidio_por_bloco (sem fees — producao de moeda).

Licenca dos dados Cambridge: CC BY-NC-SA 4.0 (nao comercial).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
import datetime as dt
import urllib.request

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DATA_MODE = os.getenv("DATA_MODE", "compute").strip().lower()
ENERGY_PRICE_USD_KWH = float(os.getenv("ENERGY_PRICE_USD_KWH", "0.05"))

# Usado apenas quando DATA_MODE=cbeci
CBECI_DATA_URL = os.getenv("CBECI_DATA_URL", "").strip()
CBECI_DATE_COL = os.getenv("CBECI_DATE_COL", "Date and Time")
CBECI_POWER_GW_COL = os.getenv("CBECI_POWER_GW_COL", "power_gw")

OUTPUT_CSV = os.getenv(
    "OUTPUT_CSV",
    os.path.join(os.path.dirname(__file__), "..", "docs", "data", "btc_production_cost.csv"),
)

MEMPOOL_HASHRATE_URL = "https://mempool.space/api/v1/mining/hashrate/1y"
BLOCKS_PER_DAY = 144

HALVING_SCHEDULE = [
    (dt.date(2009,  1,  3), 50.000),
    (dt.date(2012, 11, 28), 25.000),
    (dt.date(2016,  7,  9), 12.500),
    (dt.date(2020,  5, 11),  6.250),
    (dt.date(2024,  4, 20),  3.125),
    (dt.date(2028,  1,  1),  1.5625),
]

# Curva de eficiencia calibrada nos dados CBECI (J/TH) — interpolacao linear.
EFFICIENCY_CURVE: list[tuple[dt.date, float]] = [
    (dt.date(2019,  1,  1), 115.0),
    (dt.date(2020,  1,  1),  95.0),
    (dt.date(2021,  1,  1),  79.0),
    (dt.date(2022,  1,  1),  69.0),
    (dt.date(2023,  1,  1),  55.0),
    (dt.date(2024,  1,  1),  34.0),
    (dt.date(2025,  1,  1),  28.0),
    (dt.date(2026,  1,  1),  24.0),
    (dt.date(2027,  1,  1),  22.0),
]

HEADER = [
    "date", "production_cost_usd", "power_gw", "annualized_twh",
    "energy_price_usd_kwh", "btc_issued_per_day", "source",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def block_subsidy(on: dt.date) -> float:
    subsidy = HALVING_SCHEDULE[0][1]
    for start, value in HALVING_SCHEDULE:
        if on >= start:
            subsidy = value
        else:
            break
    return subsidy


def btc_issued_per_day(on: dt.date) -> float:
    return BLOCKS_PER_DAY * block_subsidy(on)


def efficiency_j_per_th(on: dt.date) -> float:
    if on <= EFFICIENCY_CURVE[0][0]:
        return EFFICIENCY_CURVE[0][1]
    for i in range(len(EFFICIENCY_CURVE) - 1):
        d0, e0 = EFFICIENCY_CURVE[i]
        d1, e1 = EFFICIENCY_CURVE[i + 1]
        if d0 <= on < d1:
            t = (on - d0).days / (d1 - d0).days
            return e0 + (e1 - e0) * t
    return EFFICIENCY_CURVE[-1][1]


def hashrate_to_gw(hashrate_hs: float, eff_j_per_th: float) -> float:
    th_per_s = hashrate_hs / 1e12
    watts = th_per_s * eff_j_per_th
    return watts / 1e9


def production_cost_usd(power_gw: float, price_kwh: float, on: dt.date) -> float:
    daily_kwh = power_gw * 1_000_000.0 * 24.0
    daily_energy_cost = daily_kwh * price_kwh
    issued = btc_issued_per_day(on)
    return daily_energy_cost / issued if issued > 0 else float("nan")


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "ceos-btc-production-cost/2.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _parse_date(s: str) -> dt.date:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return dt.datetime.utcfromtimestamp(int(float(s))).date()
    except (ValueError, OverflowError, OSError):
        raise ValueError(f"data nao reconhecida: {s!r}")


# --------------------------------------------------------------------------- #
# Fontes de potencia
# --------------------------------------------------------------------------- #
def fetch_compute() -> tuple[dt.date, float, str]:
    """Hashrate real do mempool.space + curva de eficiencia Cambridge."""
    print(f"[compute] Buscando hashrate: {MEMPOOL_HASHRATE_URL}")
    raw = _http_get(MEMPOOL_HASHRATE_URL)
    data = json.loads(raw)
    hashrates = data.get("hashrates", [])
    if not hashrates:
        raise ValueError("mempool.space retornou lista de hashrates vazia")

    # Ultimo ponto disponivel
    latest = hashrates[-1]
    ts = int(latest["timestamp"])
    hr_hs = float(latest["avgHashrate"])
    date = dt.date.fromtimestamp(ts)

    eff = efficiency_j_per_th(date)
    power_gw = hashrate_to_gw(hr_hs, eff)
    print(f"[compute] {date}: hashrate={hr_hs:.3e} H/s  eff={eff:.1f} J/TH  power={power_gw:.3f} GW")
    return date, power_gw, "compute-mempool"


def fetch_cbeci() -> tuple[dt.date, float, str]:
    """CSV externo (CBECI_DATA_URL) com coluna de potencia GW."""
    if not CBECI_DATA_URL:
        raise ValueError("DATA_MODE=cbeci mas CBECI_DATA_URL nao foi definida")
    print(f"[cbeci] Baixando: {CBECI_DATA_URL}")
    raw = _http_get(CBECI_DATA_URL).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV CBECI veio vazio")
    for row in reversed(rows):
        date_raw = (row.get(CBECI_DATE_COL) or "").strip()
        power_raw = (row.get(CBECI_POWER_GW_COL) or "").strip()
        if not date_raw or not power_raw:
            continue
        try:
            return _parse_date(date_raw), float(power_raw), "cbeci"
        except ValueError:
            continue
    raise ValueError(
        f"Nao achei colunas '{CBECI_DATE_COL}' / '{CBECI_POWER_GW_COL}' no CSV. "
        f"Cabecalho real: {list((rows[0] if rows else {}).keys())}"
    )


def fetch_demo() -> tuple[dt.date, float, str]:
    today = dt.date.today()
    base = 19.0
    wobble = 1.5 * math.sin(today.toordinal() / 9.0)
    return today, round(base + wobble, 3), "demo"


def fetch_power_gw() -> tuple[dt.date, float, str]:
    if DATA_MODE == "cbeci":
        return fetch_cbeci()
    if DATA_MODE == "demo":
        return fetch_demo()
    # default: compute
    try:
        return fetch_compute()
    except Exception as exc:
        print(f"[WARN] compute falhou ({exc}). Caindo para demo.", file=sys.stderr)
        return fetch_demo()


# --------------------------------------------------------------------------- #
# CSV upsert
# --------------------------------------------------------------------------- #
def upsert_row(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing: list[dict] = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            existing = list(csv.DictReader(fh))
    by_date = {r["date"]: r for r in existing}
    by_date[row["date"]] = row
    ordered = sorted(by_date.values(), key=lambda r: r["date"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(ordered)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    print(f"DATA_MODE={DATA_MODE}  ENERGY_PRICE={ENERGY_PRICE_USD_KWH} USD/kWh")
    date, power_gw, source = fetch_power_gw()
    annualized_twh = power_gw * 24 * 365 / 1000.0
    cost = production_cost_usd(power_gw, ENERGY_PRICE_USD_KWH, date)

    if math.isnan(cost):
        print("[ERROR] custo NaN — emissao zero?", file=sys.stderr)
        return 1

    row = {
        "date": date.isoformat(),
        "production_cost_usd": f"{cost:.2f}",
        "power_gw": f"{power_gw:.3f}",
        "annualized_twh": f"{annualized_twh:.2f}",
        "energy_price_usd_kwh": f"{ENERGY_PRICE_USD_KWH:.4f}",
        "btc_issued_per_day": f"{btc_issued_per_day(date):.4f}",
        "source": source,
    }
    upsert_row(OUTPUT_CSV, row)

    demo_tag = "  [DEMO — sintetico]" if source == "demo" else ""
    print(
        f"OK  {row['date']}: US$ {float(row['production_cost_usd']):,.0f}/BTC "
        f"| {row['power_gw']} GW | {row['annualized_twh']} TWh/ano "
        f"| fonte: {source}{demo_tag}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
