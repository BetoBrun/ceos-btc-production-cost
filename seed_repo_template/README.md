# seed_USERNAME_btc — repositório Pine Seeds (Pine Script · TradingView)

Este diretório é um **template** para o repositório que alimenta a série
`BTC_PRODUCTION_COST` dentro da TradingView via `request.seed()`.

> ⚠️ **Leia antes de criar expectativas.** Isto **não** é "apontar o `request.seed()`
> para um raw do GitHub". O `request.seed()` só lê de repositórios que passaram
> pelo onboarding oficial **Pine Seeds**. Há regras rígidas e uma etapa de
> aprovação da TradingView. Resumo das restrições que importam:
>
> - O repositório **precisa ser PRIVADO**. (Por isso ele é separado do repo do
>   dashboard, que é público para o GitHub Pages funcionar de graça.)
> - Nome do repo no formato `seed_<seu_usuario_github>_<sufixo>` — ex.: `seed_fulano_btc`.
> - Dados são **EOD (fim de dia)** e aparecem no gráfico **no dia seguinte** ao envio.
> - É preciso solicitar a integração à TradingView (formulário/contato Pine Seeds)
>   e ter a action **Check data** validando o repositório.
> - Sem atualização por 3 meses, os dados saem do storage da TradingView.

## Estrutura exigida

```
seed_<usuario>_btc/
├── symbol_info/
│   └── seed_<usuario>_btc.json     # nome = nome do repo
└── data/
    └── BTC_PRODUCTION_COST.csv     # nome = nome do símbolo, MAIÚSCULO
```

Formato do CSV (sem cabeçalho, ordenado por data ascendente, sem duplicatas):

```
YYYYMMDDT,open,high,low,close,volume
20260617T,55488.00,55488.00,55488.00,55488.00,0
```

Como a série tem valor único, `open=high=low=close=custo` e `volume=0`.

## Passo a passo

1. Crie um repositório **privado** chamado `seed_<seu_usuario>_btc`.
2. Renomeie `symbol_info/seed_USERNAME_btc.json` para casar com o nome do repo.
3. Copie `data/` e `scripts/` para dentro dele.
4. Gere/atualize o CSV a partir do CSV do dashboard:
   ```bash
   python scripts/csv_to_seed.py /caminho/para/btc_production_cost.csv data/BTC_PRODUCTION_COST.csv
   ```
5. Solicite a integração Pine Seeds à TradingView e aguarde a aprovação.
6. Após aprovado, a action **Check data** roda no merge e carrega os dados.
7. No indicador (`pine/ceos_btc_production_cost.pine`), descomente o bloco
   `request.seed("seed_<usuario>_btc", "BTC_PRODUCTION_COST", close)`.

Docs oficiais: https://github.com/tradingview-pine-seeds/docs
