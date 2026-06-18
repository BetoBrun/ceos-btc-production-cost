# CEOS · BTC Production Cost

Dashboard + pipeline para acompanhar o **custo de produção do Bitcoin (piso de
energia)** e compará-lo ao preço. Modelo de consumo: Cambridge **CBECI**.

- **Dashboard** (GitHub Pages): gráfico TradingView do BTC, série própria de custo
  de produção (CSV) e cards (último custo, TWh anualizado, preço de energia usado,
  emissão diária).
- **Pipeline** (Python + GitHub Actions): recalcula o custo diariamente e commita o CSV.
- **Indicador Pine** (`pine/`): linha de custo + banda Cambridge×Capriole + alertas.
- **Template Pine Seeds** (`seed_repo_template/`): para automatizar a série dentro
  da TradingView (processo separado — veja abaixo).

---

## ⚠️ Leia primeiro — o que mudou em relação ao plano inicial

Três pontos do plano original estavam tecnicamente errados ou imprecisos e foram
corrigidos aqui:

1. **GitHub Pages não tem a opção `/dashboard`.** O "Deploy from branch" só oferece
   `/ (root)` ou `/docs`. Por isso o site fica em **`/docs`**.
2. **`request.seed()` não lê um raw do GitHub qualquer.** Exige um repositório
   **privado** no padrão Pine Seeds, com onboarding e aprovação da TradingView, e os
   dados são **EOD com 1 dia de atraso**. Por isso o Pine roda em **modo manual** por
   padrão, e o Pine Seeds é um **repositório separado** (`seed_repo_template/`).
3. **O "custo de produção" é só energia.** É um *piso*, não o custo real de mineração
   (não inclui ASIC/capex, cooling, fees, mão de obra). O card e os textos deixam isso
   explícito para você não se enganar com o próprio indicador.

### Sobre os dados e licença
- A Cambridge **já publica** um "BTC production cost index" próprio. Você pode calcular
  com o seu preço de energia (controle via `ENERGY_PRICE_USD_KWH`) **ou** ingerir o CSV
  pronto deles (aí o preço é fixo, historicamente US$ 0,05/kWh).
- O default de **US$ 0,05/kWh** é frágil: há análise mostrando que esse pressuposto
  fixo faz o CBECI superestimar a demanda em alguns períodos. Trate como ponto de
  partida, não verdade.
- Dados do CBECI são **CC BY-NC-SA 4.0 (não comercial)**. Se "CEOS" for comercial,
  redistribuir a série publicamente pode violar a licença. Avalie antes.

### ❗ Você precisa conectar a fonte real
O script vem em **modo DEMO** (dados sintéticos) para o pipeline e o dashboard
funcionarem de imediato. Os números **não são reais** até você definir `CBECI_DATA_URL`
e conferir o mapeamento de colunas. Veja `scripts/update_production_cost.py`.

---

## Estrutura

```
ceos-btc-production-cost/
├── docs/                         # GitHub Pages (selecione /docs)
│   ├── index.html · styles.css · app.js
│   └── data/btc_production_cost.csv
├── scripts/update_production_cost.py
├── pine/ceos_btc_production_cost.pine
├── seed_repo_template/           # copie para um repo PRIVADO seed_<usuario>_btc
├── .github/workflows/update.yml
├── requirements.txt · config.example.env
```

## Setup (5 passos)

1. **Suba este repositório** (veja comandos abaixo).
2. **Ative o Pages:** Settings → Pages → *Deploy from a branch* → `main` → **`/docs`**.
3. **(Opcional) Configure as variáveis** em Settings → Secrets and variables → Actions
   → *Variables*: `ENERGY_PRICE_USD_KWH`, `CBECI_DATA_URL`, `CBECI_DATE_COL`,
   `CBECI_POWER_GW_COL`.
4. **Rode a Action** uma vez: aba Actions → *Update BTC Production Cost* → *Run workflow*.
5. **Indicador:** cole `pine/ceos_btc_production_cost.pine` no Pine Editor da TradingView.

A Action roda sozinha todo dia (06:10 UTC) e commita o CSV atualizado.

## Rodar localmente

```bash
# modo DEMO
python scripts/update_production_cost.py

# com fonte real
export CBECI_DATA_URL="https://.../sua-serie.csv"
export ENERGY_PRICE_USD_KWH=0.05
python scripts/update_production_cost.py
```

Sem dependências externas (só stdlib).

## Aviso
Projeto informativo. **Não é recomendação de investimento.** O custo de produção é um
modelo de piso energético, não o custo real de mineração nem um alvo de preço.
