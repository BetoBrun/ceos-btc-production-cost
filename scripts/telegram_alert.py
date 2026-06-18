#!/usr/bin/env python3
"""
CEOS BTC Production Cost — Alertas Telegram.

Dispara mensagem com notificacao sonora quando:
  1. Fear & Greed Index cai abaixo de FNG_THRESHOLD (padrao: 9)
  2. Preco BTC fica abaixo do custo de producao (multiplo < 1)

Cooldown: 20h entre alertas do mesmo tipo (evita spam).
Estado salvo em docs/data/alert_state.json (commitado pelo workflow).

Secrets necessarios no repositorio GitHub:
  TELEGRAM_BOT_TOKEN  — token do bot (@BotFather)
  TELEGRAM_CHAT_ID    — seu chat ID pessoal
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
import urllib.request

FNG_THRESHOLD  = int(os.getenv("FNG_THRESHOLD",   "9"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS",  "20"))
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN",  "")
CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID",    "")

_BASE = os.path.join(os.path.dirname(__file__), "..")
STATE_FILE = os.path.join(_BASE, "docs", "data", "alert_state.json")
CSV_FILE   = os.path.join(_BASE, "docs", "data", "btc_production_cost.csv")


# --------------------------------------------------------------------------- #
# Fetchers
# --------------------------------------------------------------------------- #
def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ceos-btc-alert/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def fetch_fng() -> tuple[int | None, str]:
    try:
        data = json.loads(_get("https://api.alternative.me/fng/?limit=1"))
        e = data["data"][0]
        return int(e["value"]), e["value_classification"]
    except Exception as exc:
        print(f"[WARN] F&G fetch: {exc}", file=sys.stderr)
        return None, "—"


def fetch_spot() -> float | None:
    try:
        data = json.loads(_get("https://api.coinbase.com/v2/prices/BTC-USD/spot"))
        return float(data["data"]["amount"])
    except Exception as exc:
        print(f"[WARN] Spot fetch: {exc}", file=sys.stderr)
        return None


def read_latest_cost() -> tuple[float | None, str]:
    try:
        with open(CSV_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None, "—"
        last = rows[-1]
        return float(last["production_cost_usd"]), last["date"]
    except Exception as exc:
        print(f"[WARN] CSV read: {exc}", file=sys.stderr)
        return None, "—"


# --------------------------------------------------------------------------- #
# State / cooldown
# --------------------------------------------------------------------------- #
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def in_cooldown(state: dict, key: str) -> bool:
    last = state.get(key)
    if not last:
        return False
    elapsed = (dt.datetime.utcnow() - dt.datetime.fromisoformat(last)).total_seconds()
    return elapsed < COOLDOWN_HOURS * 3600


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def send(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID nao definidos.", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_notification": False,   # garante som no dispositivo
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        ok = resp.get("ok", False)
        print(f"[{'OK' if ok else 'ERR'}] Telegram: {resp.get('description','enviado')}")
        return ok
    except Exception as exc:
        print(f"[ERROR] Telegram send: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    if not BOT_TOKEN or not CHAT_ID:
        print("[ERRO] Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID como secrets no GitHub.",
              file=sys.stderr)
        return 1

    fng_val, fng_cls = fetch_fng()
    spot              = fetch_spot()
    cost, cost_date   = read_latest_cost()

    now  = dt.datetime.utcnow()
    now_s = now.strftime("%d/%m/%Y %H:%M")
    state = load_state()
    dirty = False

    spot_s = f"US$ {spot:,.0f}"   if spot  else "indisponível"
    cost_s = f"US$ {cost:,.0f}"   if cost  else "indisponível"
    fng_s  = f"{fng_val} ({fng_cls})" if fng_val is not None else "indisponível"
    mult_s = f"{spot/cost:.2f}x"  if spot and cost else "—"

    print(f"F&G: {fng_s}  |  Spot: {spot_s}  |  Custo: {cost_s} ({cost_date})  |  Multiplo: {mult_s}")

    # ------------------------------------------------------------------ #
    # Alerta 1 — Fear & Greed abaixo do limiar
    # ------------------------------------------------------------------ #
    if fng_val is not None and fng_val <= FNG_THRESHOLD:
        if not in_cooldown(state, "fng"):
            msg = (
                "🚨 <b>SINAL DE COMPRA — Fear &amp; Greed</b>\n\n"
                f"😱 F&amp;G Index: <b>{fng_val}</b> ({fng_cls})\n"
                f"⚠️ Abaixo do limiar de <b>{FNG_THRESHOLD}</b> — medo extremo histórico\n\n"
                f"💰 BTC Spot: <b>{spot_s}</b>\n"
                f"⚡ Custo de Produção: <b>{cost_s}</b> ({cost_date})\n"
                f"📐 Múltiplo preço/custo: <b>{mult_s}</b>\n\n"
                f"🕐 {now_s} UTC\n"
                "📊 <a href=\"https://betobrun.github.io/ceos-btc-production-cost/\">CEOS Dashboard</a>"
            )
            if send(msg):
                state["fng"] = now.isoformat()
                dirty = True
        else:
            print(f"[INFO] F&G={fng_val} <= {FNG_THRESHOLD} mas cooldown ativo.")

    # ------------------------------------------------------------------ #
    # Alerta 2 — Preco abaixo do custo de producao
    # ------------------------------------------------------------------ #
    if spot is not None and cost is not None and spot < cost:
        if not in_cooldown(state, "below_cost"):
            mult = spot / cost
            msg = (
                "🚨 <b>SINAL DE COMPRA — Preço abaixo do Custo</b>\n\n"
                f"💰 BTC Spot: <b>{spot_s}</b>\n"
                f"⚡ Custo de Produção (energia): <b>{cost_s}</b> ({cost_date})\n"
                f"📐 Múltiplo: <b>{mult:.2f}×</b> — <b>ABAIXO DO PISO ENERGÉTICO</b>\n\n"
                f"😱 Fear &amp; Greed: {fng_s}\n\n"
                f"🕐 {now_s} UTC\n"
                "📊 <a href=\"https://betobrun.github.io/ceos-btc-production-cost/\">CEOS Dashboard</a>"
            )
            if send(msg):
                state["below_cost"] = now.isoformat()
                dirty = True
        else:
            print(f"[INFO] Spot < Custo mas cooldown ativo.")

    if dirty:
        save_state(state)
        print("[OK] alert_state.json atualizado.")
    else:
        print("[INFO] Nenhum alerta disparado.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
