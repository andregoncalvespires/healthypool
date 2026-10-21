# Fichas de produtos

Cada produto é um arquivo `.json` com a ficha de dados do fabricante: dose, esperas, regras de segurança e instruções de uso. A integração usa, **para cada função**, o produto escolhido em **Configurar → Produtos**. Os produtos Genco vêm embutidos nesta pasta.

## Adicionar outra marca ou produto

1. Crie uma pasta `healthy_pool_products` dentro da pasta de configuração do Home Assistant (a mesma de `configuration.yaml`).
2. Coloque nela um arquivo `.json` por produto, no formato abaixo. Um arquivo com o mesmo `id` de um embutido substitui o embutido.
3. Reinicie o Home Assistant (ou recarregue a integração) e escolha o produto em **Configurar → Produtos**.

Fichas inválidas (JSON quebrado, campo faltando, função desconhecida) são ignoradas, e o motivo aparece no log do Home Assistant (`custom_components.healthy_pool.catalog`).

**Copie os números do rótulo ou da ficha técnica do fabricante, e informe a fonte.** Para publicar uma ficha neste repositório, abra um pull request com o arquivo em `custom_components/healthy_pool/products/` e o campo `source` preenchido.

## Campos comuns

| Campo | Obrigatório | Descrição |
|---|---|---|
| `id` | sim | Identificador único, em minúsculas (`marca_produto`) |
| `brand` | sim | Marca |
| `name` | sim | Nome do produto, como aparece nas telas |
| `role` | sim | Função: `alk_up`, `acid`, `ph_up`, `chlorine`, `algaecide`, `clarifier` ou `metals_remover` |
| `unit` | sim | `g` ou `mL` |
| `dosing` | sim | Doses da função (veja abaixo) |
| `remeasure_hours` | não | Espera antes de medir de novo (corretivos). 0 = sem espera |
| `rules` | não | Regras de segurança (veja abaixo) |
| `instructions` | não | Lista de passos de aplicação (corretivos). Aceita `{alk_up}`, `{acid}`, `{ph_up}`... para citar os produtos escolhidos |
| `notes` | não | Observações extras (algicida, clarificante e removedor de metais) |
| `source` | recomendado | De onde vêm os números (rótulo, ficha técnica, link) |
| `message_name` | não | Nome dentro de frases ("Adicionar 100 g de ..."); padrão = `name` |
| `short_name` | não | Nome curto do item nas mensagens (removedor de metais); padrão = `name` |

## Funções e campos de `dosing`

| Função | Para quê | Campos em `dosing` |
|---|---|---|
| `alk_up` | Subir a alcalinidade | `g_per_m3_per_ppm`: gramas por m³ para cada 1 ppm |
| `acid` | Baixar alcalinidade e pH | `alkalinity_ml_per_m3_per_ppm`; `ph_steps`: lista de `{"up_to_ph": 8.0, "ml_per_m3": 10}` em ordem, o último sem `up_to_ph`; `max_ml_per_m3_per_application`: limite por aplicação (acima disso a dose é dividida em dias); opcional `label_min_ph`: menor pH com dose no rótulo |
| `ph_up` | Subir o pH | `table_target_ph`: pH que a tabela atinge; `table_alkalinity`: as duas alcalinidades das colunas, por exemplo `[80, 120]`; `table`: linhas `[pH, g/m³ na 1ª alcalinidade, g/m³ na 2ª]`; opcional `chemistry`: `"sodium_carbonate"` para ajustar a dose quando a meta de pH muda (sem isso é proporcional) |
| `chlorine` | Cloro | `available_chlorine`: fração de cloro disponível (dicloro 56 % = 0.56) |
| `algaecide` | Algicida | `maintenance_ml_per_m3`, `shock_ml_per_m3`; opcionais `shock_interval_days`, `maintenance_name`, `shock_name` |
| `clarifier` | Clarificante | `preventive_ml_per_m3`, `corrective_ml_per_m3`; opcionais `corrective_interval_days`, `preventive_filter_hours`, `corrective_filter_hours` |
| `metals_remover` | Removedor de metais | `ml_per_m3_per_ppm`, `removal_ml_per_m3`; opcionais `repeat_days`, `window_days`, `bottle_ml` |

## Campos de `rules`

| Campo | Em quais funções | Descrição |
|---|---|---|
| `ph_window` | `algaecide`, `metals_remover` | `[mín, máx]` de pH exigido para aplicar |
| `chlorine_range` | `algaecide` | `[mín, máx]` de cloro livre durante o uso |
| `min_hours_between_chlorine` | `algaecide` | Horas entre algicida e cloro, nos dois sentidos |
| `shock_contains_copper` | `algaecide` | `true` avisa para não usar quando a cor verde for de metais |
| `max_chlorine` | `metals_remover` | Cloro máximo (ppm) durante o tratamento |
| `release_minutes` | corretivos, `algaecide`, `clarifier`, `metals_remover` | Minutos até liberar a piscina (padrão 30) |
| `release_max_chlorine` | `chlorine` | Residual máximo (ppm) para liberar a piscina |

## Exemplo

```json
{
  "id": "acme_alk_plus",
  "brand": "Acme",
  "name": "Alcalino Plus",
  "role": "alk_up",
  "unit": "g",
  "remeasure_hours": 24,
  "dosing": { "g_per_m3_per_ppm": 2.0 },
  "instructions": [
    "Dissolva em água antes de aplicar.",
    "No dia seguinte, corrija o pH com {ph_up} ou {acid}."
  ],
  "source": "Rótulo Acme Alcalino Plus, versão 2025"
}
```

## Aviso

As fichas reproduzem dados publicados pelos fabricantes, apenas como referência de dosagem. Conferir o rótulo da embalagem antes de aplicar é sempre responsabilidade de quem usa. Marcas e nomes pertencem aos seus donos.
