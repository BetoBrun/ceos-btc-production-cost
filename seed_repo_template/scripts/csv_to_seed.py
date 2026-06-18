#!/usr/bin/env python3
"""
Converte docs/data/btc_production_cost.csv (formato do dashboard) para o formato
exigido pelo Pine Seeds da TradingView.

Formato de saida (data/BTC_PRODUCTION_COST.csv), SEM cabecalho:
    YYYYMMDDT,open,high,low,close,volume
Serie de valor unico => open=high=low=close=custo, volume=0.
Linhas ordenadas por data ascendente, sem duplicatas.

Uso:
    python scripts/csv_to_seed.py /caminho/do/btc_production_cost.csv
Saida default: data/BTC_PRODUCTION_COST.csv (relativo a este repo seed).
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(__file__)
DEFAULT_IN = os.path.join(HERE, "..", "..", "docs", "data", "btc_production_cost.csv")
DEFAULT_OUT = os.path.join(HERE, "..", "data", "BTC_PRODUCTION_COST.csv")


def main(argv: list[str]) -> int:
    src = argv[1] if len(argv) > 1 else DEFAULT_IN
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT
    if not os.path.exists(src):
        print(f"[ERRO] entrada nao encontrada: {src}", file=sys.stderr)
        return 1

    rows = {}
    with open(src, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            date = (r.get("date") or "").strip()
            val = (r.get("production_cost_usd") or "").strip()
            if not date or not val:
                continue
            ymd = date.replace("-", "") + "T"   # 2026-06-17 -> 20260617T
            rows[ymd] = f"{ymd},{val},{val},{val},{val},0"

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        fh.write("\n".join(rows[k] for k in sorted(rows)) + "\n")

    print(f"OK: {len(rows)} linhas -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
