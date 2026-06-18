#!/usr/bin/env python3
"""
CEOS BTC Production Cost — atualizador diario.

O que ele calcula
-----------------
Custo de producao do BTC considerando APENAS energia (piso energetico).
NAO inclui capex de ASIC, cooling, manutencao, pool fees nem mao de obra.
E o mesmo conceito que a Cambridge chama de "BTC production cost" no CBECI.

Logica (Cambridge):
    consumo diario (kWh) = potencia_da_rede[GW] * 1e6 * 24
    custo de energia/dia  = consumo_diario_kWh * ENERGY_PRICE_USD_KWH
    custo por BTC         = custo_de_energia/dia / btc_emitidos_no_dia

A emissao diaria vem do cronograma de halving (subsidio por bloco * ~144 blocos/dia).
Fees NAO entram: producao de moeda = subsidio.

IMPORTANTE — voce PRECISA confirmar a fonte de dados
----------------------------------------------------
Eu (o autor original deste script) NAO consegui verificar ao vivo o endpoint
exato/atual do CBECI a partir do ambiente em que isto foi gerado. Por isso a
URL e o mapeamento de colunas sao CONFIGURAVEIS via variaveis de ambiente, e
ha um modo DEMO que gera dados sinteticos para o pipeline rodar de imediato.

Antes de confiar nos numeros:
  1. Abra https://ccaf.io/cbnsi/cbeci  ->  secao de download (CSV).
  2. A Cambridge ja publica um "BTC production cost index" proprio. Voce pode:
       (a) apontar este script para a serie de POTENCIA/consumo e calcular voce
           mesmo com o seu ENERGY_PRICE_USD_KWH (controle do preco da energia), ou
       (b) ignorar o calculo e ingerir direto o CSV de production cost da Cambridge
           (nesse caso ENERGY_PRICE_USD_KWH nao tem efeito, pois a Cambridge fixa
           o preco — historicamente US$ 0,05/kWh).
  3. Cole a URL real em CBECI_DATA_URL e ajuste CBECI_DATE_COL / CBECI_POWER_COL.

Licenca dos dados: o CBECI e CC BY-NC-SA 4.0 (NAO comercial). Se este projeto
for comercial, redistribuir a serie publicamente pode violar a licenca. Avalie.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import math
import datetime as dt
import urllib.request

# --------------------------------------------------------------------------- #
# Configuracao (via env, com defaults seguros)
# --------------------------------------------------------------------------- #
ENERGY_PRICE_USD_KWH = float(os.getenv("ENERGY_PRICE_USD_KWH", "0.05"))

# URL da serie do CBECI. Vazio => modo DEMO (dados sinteticos).
CBECI_DATA_URL = os.getenv("CBECI_DATA_URL", "").strip()

# Nomes das colunas no CSV do CBECI (ajuste conforme o arquivo real).
CBECI_DATE_COL = os.getenv("CBECI_DATE_COL", "Date and Time")
# Coluna de POTENCIA da rede em GW (best-guess). Se a sua fonte trouxer consumo
# anualizado em TWh, troque para CBECI_TWH_COL e ajuste o calculo abaixo.
CBECI_POWER_GW_COL = os.getenv("CBECI_POWER_GW_COL", "power GW, guess")

OUTPUT_CSV = os.getenv(
    "OUTPUT_CSV",
    os.path.join(os.path.dirname(__file__), "..", "docs", "data", "btc_production_cost.csv"),
)

BLOCKS_PER_DAY = 144  # aproximacao (alvo do protocolo: 1 bloco / 10 min)

# Cronograma de halving (data de inicio -> subsidio por bloco, em BTC).
# Fonte: regras do protocolo Bitcoin. Datas dos halvings sao historicas.
HALVING_SCHEDULE = [
    (dt.date(2009, 1, 3), 50.0),
    (dt.date(2012, 11, 28), 25.0),
    (dt.date(2016, 7, 9), 12.5),
    (dt.date(2020, 5, 11), 6.25),
    (dt.date(2024, 4, 20), 3.125),
    # proximo halving ~2028 -> 1.5625 (o script ja lida quando a data chegar)
    (dt.date(2028, 1, 1), 1.5625),
]


def block_subsidy(on: dt.date) -> float:
    """Subsidio por bloco vigente em uma data."""
    subsidy = HALVING_SCHEDULE[0][1]
    for start, value in HALVING_SCHEDULE:
        if on >= start:
            subsidy = value
        else:
            break
    return subsidy


def btc_issued_per_day(on: dt.date) -> float:
    return BLOCKS_PER_DAY * block_subsidy(on)


def production_cost_usd(power_gw: float, price_kwh: float, on: dt.date) -> float:
    """Custo de energia por BTC emitido (piso energetico)."""
    daily_kwh = power_gw * 1_000_000.0 * 24.0       # GW -> kW, * 24h
    daily_energy_cost = daily_kwh * price_kwh
    issued = btc_issued_per_day(on)
    if issued <= 0:
        return float("nan")
    return daily_energy_cost / issued


# --------------------------------------------------------------------------- #
# Fontes de potencia da rede
# --------------------------------------------------------------------------- #
def fetch_latest_power_gw() -> tuple[dt.date, float, str]:
    """
    Retorna (data, potencia_GW, origem).
    Se CBECI_DATA_URL estiver vazia, usa modo DEMO.
    """
    if not CBECI_DATA_URL:
        return _demo_power_gw()

    try:
        req = urllib.request.Request(
            CBECI_DATA_URL, headers={"User-Agent": "ceos-btc-production-cost/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Falha ao baixar CBECI ({exc}). Caindo para modo DEMO.", file=sys.stderr)
        return _demo_power_gw()

    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        print("[WARN] CSV do CBECI veio vazio. Modo DEMO.", file=sys.stderr)
        return _demo_power_gw()

    # pega a ultima linha valida
    for row in reversed(rows):
        date_raw = (row.get(CBECI_DATE_COL) or "").strip()
        power_raw = (row.get(CBECI_POWER_GW_COL) or "").strip()
        if not date_raw or not power_raw:
            continue
        try:
            date = _parse_date(date_raw)
            power = float(power_raw)
        except ValueError:
            continue
        return date, power, "cbeci"

    print(
        f"[WARN] Nao achei colunas '{CBECI_DATE_COL}' / '{CBECI_POWER_GW_COL}'. "
        "Confira o cabecalho real do CSV. Modo DEMO.",
        file=sys.stderr,
    )
    return _demo_power_gw()


def _parse_date(s: str) -> dt.date:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # epoch?
    try:
        return dt.datetime.utcfromtimestamp(int(float(s))).date()
    except (ValueError, OverflowError, OSError):
        raise ValueError(f"data nao reconhecida: {s!r}")


def _demo_power_gw() -> tuple[dt.date, float, str]:
    """Potencia sintetica plausivel (~17-22 GW) so para o pipeline rodar."""
    today = dt.date.today()
    base = 19.0
    wobble = 1.5 * math.sin(today.toordinal() / 9.0)
    return today, round(base + wobble, 3), "demo"


# --------------------------------------------------------------------------- #
# Escrita idempotente do CSV
# --------------------------------------------------------------------------- #
HEADER = [
    "date",
    "production_cost_usd",
    "power_gw",
    "annualized_twh",
    "energy_price_usd_kwh",
    "btc_issued_per_day",
    "source",
]


def upsert_row(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing: list[dict] = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            existing = list(csv.DictReader(fh))

    by_date = {r["date"]: r for r in existing}
    by_date[row["date"]] = row  # upsert (substitui se ja existe hoje)

    ordered = sorted(by_date.values(), key=lambda r: r["date"])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(ordered)


def main() -> int:
    date, power_gw, source = fetch_latest_power_gw()
    annualized_twh = power_gw * 24 * 365 / 1000.0  # GW*h/ano -> TWh (constante)
    cost = production_cost_usd(power_gw, ENERGY_PRICE_USD_KWH, date)

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
    tag = "  [DEMO — dados sinteticos]" if source == "demo" else ""
    print(
        f"{row['date']}: custo de producao = US$ {row['production_cost_usd']} "
        f"(power {row['power_gw']} GW, {row['annualized_twh']} TWh/ano, "
        f"energia US$ {row['energy_price_usd_kwh']}/kWh){tag}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
