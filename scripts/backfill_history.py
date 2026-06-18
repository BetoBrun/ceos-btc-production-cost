#!/usr/bin/env python3
"""
CEOS BTC Production Cost — Backfill historico 5 anos.

Fonte de hashrate : mempool.space API publica (sem auth, ~1825 dias diarios)
Eficiencia J/TH  : curva calibrada nos dados publicados pelo Cambridge CBECI
                   (central estimate, pontos trimestrais validados)
Energia          : US$ 0,05/kWh (mesmo default do pipeline diario)

Os valores gerados sao uma RECONSTRUCAO HISTORICA — nao dados reais do CBECI.
Use como referencia analitica, nao como serie oficial Cambridge.

Pontos de calibracao da curva de eficiencia (J/TH):
  2021-Q1 : 130 EH/s  -> ~90 TWh/ano  -> 79 J/TH
  2022-Q1 : 200 EH/s  -> ~120 TWh/ano -> 69 J/TH
  2023-Q1 : 310 EH/s  -> ~150 TWh/ano -> 55 J/TH
  2024-Q1 : 580 EH/s  -> ~175 TWh/ano -> 34 J/TH
  2025-Q1 : 750 EH/s  -> ~185 TWh/ano -> 28 J/TH

Formula (Cambridge):
  daily_kWh   = power_GW x 1_000_000 x 24
  cost_day    = daily_kWh x energy_price_usd_kwh
  cost_per_BTC = cost_day / btc_issued_per_day
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
import urllib.request

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
ENERGY_PRICE_USD_KWH = float(os.getenv("ENERGY_PRICE_USD_KWH", "0.05"))
BACKFILL_DAYS = int(os.getenv("BACKFILL_DAYS", "1825"))  # 5 anos

OUTPUT_CSV = os.getenv(
    "OUTPUT_CSV",
    os.path.join(os.path.dirname(__file__), "..", "docs", "data", "btc_production_cost.csv"),
)

HASHRATE_API = f"https://mempool.space/api/v1/mining/hashrate/{BACKFILL_DAYS // 365}y"

BLOCKS_PER_DAY = 144

HALVING_SCHEDULE = [
    (dt.date(2009,  1,  3), 50.000),
    (dt.date(2012, 11, 28), 25.000),
    (dt.date(2016,  7,  9), 12.500),
    (dt.date(2020,  5, 11),  6.250),
    (dt.date(2024,  4, 20),  3.125),
    (dt.date(2028,  1,  1),  1.5625),
]

# Curva de eficiencia calibrada nos dados Cambridge CBECI (J/TH)
# Interpolacao linear entre pontos trimestrais validados.
EFFICIENCY_CURVE: list[tuple[dt.date, float]] = [
    (dt.date(2019,  1,  1), 115.0),  # era S9 ainda dominante
    (dt.date(2020,  1,  1),  95.0),  # S17/T17 chegando
    (dt.date(2021,  1,  1),  79.0),  # calibrado: 130 EH/s -> 90 TWh/ano
    (dt.date(2022,  1,  1),  69.0),  # calibrado: 200 EH/s -> 120 TWh/ano
    (dt.date(2023,  1,  1),  55.0),  # calibrado: 310 EH/s -> 150 TWh/ano
    (dt.date(2024,  1,  1),  34.0),  # calibrado: 580 EH/s -> 175 TWh/ano
    (dt.date(2025,  1,  1),  28.0),  # calibrado: 750 EH/s -> 185 TWh/ano
    (dt.date(2026,  1,  1),  24.0),  # projecao: novos ASICs S21 XP / T21 Ultra
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


def btc_per_day(on: dt.date) -> float:
    return BLOCKS_PER_DAY * block_subsidy(on)


def efficiency_j_per_th(on: dt.date) -> float:
    """Interpolacao linear entre os pontos de calibracao Cambridge."""
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
    """H/s + J/TH -> potencia em GW."""
    th_per_s = hashrate_hs / 1e12
    watts = th_per_s * eff_j_per_th
    return watts / 1e9


def cost_per_btc(power_gw: float, price_kwh: float, on: dt.date) -> float:
    daily_kwh = power_gw * 1_000_000.0 * 24.0
    daily_cost = daily_kwh * price_kwh
    issued = btc_per_day(on)
    return daily_cost / issued if issued > 0 else float("nan")


# --------------------------------------------------------------------------- #
# Hashrate fetch
# --------------------------------------------------------------------------- #
def fetch_hashrate() -> list[tuple[dt.date, float]]:
    """Retorna lista de (data, hashrate_H_s) do mempool.space."""
    print(f"Buscando hashrate: {HASHRATE_API}")
    req = urllib.request.Request(
        HASHRATE_API,
        headers={"User-Agent": "ceos-btc-production-cost/backfill"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    rows: list[tuple[dt.date, float]] = []
    for entry in data.get("hashrates", []):
        ts = entry.get("timestamp")
        hr = entry.get("avgHashrate")
        if ts is None or hr is None:
            continue
        date = dt.date.fromtimestamp(int(ts))
        rows.append((date, float(hr)))

    rows.sort(key=lambda x: x[0])
    print(f"  {len(rows)} pontos diarios de {rows[0][0]} a {rows[-1][0]}")
    return rows


# --------------------------------------------------------------------------- #
# CSV upsert
# --------------------------------------------------------------------------- #
def load_existing(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["date"]: r for r in csv.DictReader(fh)}


def save_csv(path: str, by_date: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ordered = sorted(by_date.values(), key=lambda r: r["date"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(ordered)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    hashrate_series = fetch_hashrate()
    existing = load_existing(OUTPUT_CSV)

    added = updated = skipped = 0
    insights: list[tuple[str, str, float, float]] = []  # (date, label, cost, notes)

    prev_cost = None
    for date, hr_hs in hashrate_series:
        eff = efficiency_j_per_th(date)
        power_gw = hashrate_to_gw(hr_hs, eff)
        twh = power_gw * 24 * 365 / 1000.0
        cost = cost_per_btc(power_gw, ENERGY_PRICE_USD_KWH, date)

        if math.isnan(cost):
            skipped += 1
            continue

        key = date.isoformat()
        is_new = key not in existing
        existing[key] = {
            "date": key,
            "production_cost_usd": f"{cost:.2f}",
            "power_gw": f"{power_gw:.3f}",
            "annualized_twh": f"{twh:.2f}",
            "energy_price_usd_kwh": f"{ENERGY_PRICE_USD_KWH:.4f}",
            "btc_issued_per_day": f"{btc_per_day(date):.4f}",
            "source": "backfill-mempool",
        }
        if is_new:
            added += 1
        else:
            updated += 1

        # Detecta pontos de inflexao relevantes para insights
        if prev_cost is not None:
            # Halving: subsidy muda
            subsidy = block_subsidy(date)
            prev_subsidy = block_subsidy(date - dt.timedelta(days=1))
            if subsidy != prev_subsidy:
                insights.append((key, f"HALVING {prev_subsidy:.3f}->{subsidy:.3f} BTC/bloco", cost, 0))

            # Custo cruzou levels redondos importantes ($10k, $20k, $30k, $40k, $50k, $60k, $70k, $80k, $90k)
            for lvl in [10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 90000]:
                if (prev_cost < lvl <= cost) or (cost <= lvl < prev_cost):
                    direction = "^" if prev_cost < lvl else "v"
                    insights.append((key, f"custo cruzou US$ {lvl//1000}k [{direction}]", cost, lvl))

        prev_cost = cost

    save_csv(OUTPUT_CSV, existing)

    total = len(existing)
    print(f"\nCSV: {added} adicionados | {updated} atualizados | {skipped} pulados")
    print(f"Total de linhas no CSV: {total}")
    print(f"Periodo: {sorted(existing)[0]}  ->  {sorted(existing)[-1]}")

    # Relatorio de insights
    if insights:
        print("\n" + "=" * 70)
        print("PONTOS DE INFLEXAO — SUPORTE / INSIGHTS DE ENTRADA")
        print("=" * 70)
        print(f"{'Data':<12} {'Custo (US$)':>14}  Evento")
        print("-" * 70)
        for date_s, label, cost_val, _ in insights:
            print(f"{date_s:<12} {cost_val:>14,.0f}  {label}")

        # Analise estatistica dos niveis de custo historicos
        all_costs = sorted(
            float(r["production_cost_usd"])
            for r in existing.values()
            if r.get("source") == "backfill-mempool"
        )
        if all_costs:
            n = len(all_costs)
            print("\n" + "=" * 70)
            print("ESTATISTICAS DO CUSTO DE PRODUCAO (5 anos)")
            print("=" * 70)
            print(f"  Minimo historico : US$ {all_costs[0]:,.0f}")
            print(f"  Maximo historico : US$ {all_costs[-1]:,.0f}")
            print(f"  Mediana          : US$ {all_costs[n//2]:,.0f}")
            print(f"  Percentil 25     : US$ {all_costs[n//4]:,.0f}  <- zona de acumulacao historica")
            print(f"  Percentil 75     : US$ {all_costs[3*n//4]:,.0f}")
            print(f"  Atual (ultimo)   : US$ {all_costs[-1]:,.0f}")

    print(f"\nCSV salvo em: {os.path.abspath(OUTPUT_CSV)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
