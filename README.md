# Healthy Pool

Integração customizada do Home Assistant para a piscina de casa: calcula o **volume de água** pela geometria, analisa as medições do kit de gotas (**alcalinidade, pH e cloro livre**) e sugere **qual produto adicionar e em que quantidade**. Os produtos Genco vêm prontos; outras marcas entram por fichas JSON.

Projeto pessoal, sem fins comerciais e sem ligação com a Genco (veja o [aviso](#aviso)). Requer Home Assistant 2024.12 ou mais novo. Interface em português.

## Instalação

### Pelo HACS (repositório personalizado)

1. No HACS, abra o menu (três pontos) → **Repositórios personalizados**.
2. Em **Repositório**, cole `https://github.com/andregoncalvespires/healthypool`; em **Categoria**, escolha **Integração**; toque em **Adicionar**.
3. Procure **Healthy Pool** no HACS, toque em **Baixar** e reinicie o Home Assistant.
4. Siga os passos de configuração abaixo.

### Manualmente

1. Baixe o repositório (**Code → Download ZIP**) e copie a pasta `custom_components/healthy_pool` para `/config/custom_components/`.
2. Reinicie o Home Assistant.

### Configuração

1. Em **Configurações → Dispositivos e serviços → Adicionar integração**, procure por **Healthy Pool**.
2. Escolha o **formato** da piscina e informe as medidas (não há valores padrão: informe as medidas da sua piscina; área rasa e escada são opcionais, deixe 0 se não tiver) e as faixas de qualidade.

Depois, em **Configurar** na integração, dá para mudar as medidas da piscina, o sensor de temperatura e as faixas a qualquer momento.

### Formato da piscina

| Formato | Campos usados | Como calcula |
|---|---|---|
| Retangular | comprimento, largura, profundidade funda; opcionais: área rasa (comprimento e profundidade) e escada (degraus, largura do degrau, largura da escada) | Parte funda + área rasa + escada. Para piscina simples de fundo plano, deixe área rasa e degraus em 0 e use a mesma profundidade nos dois campos |
| Retangular com fundo inclinado | comprimento, largura, profundidade rasa (início) e funda (fim) | Declive linear |
| Redonda | comprimento = diâmetro, profundidade funda = profundidade média | π × r² × (profundidade − altura livre) |
| Oval | comprimento, largura, profundidade média | π/4 × C × L × (profundidade − altura livre) |
| Informar o volume direto | só o volume em m³ | Usa o valor informado (a altura livre não altera). Serve para qualquer desenho, por exemplo o volume do manual da piscina |

Profundidades são medidas da borda até o fundo. Se o seu desenho não se encaixa em nenhum formato, use "Informar o volume direto".

Depois, em **Configurar** na integração, dá para mudar as medidas da piscina, o sensor de temperatura e as faixas a qualquer momento.

## Entidades (um dispositivo "Piscina")

| Tipo | Entidade | Para quê |
|---|---|---|
| number | Alcalinidade total, pH, Cloro livre | Você digita a medição do kit de gotas |
| number | Altura livre | Distância da água até a borda em cm (padrão 6,5). Ajuste conforme o nível; o volume e as doses são recalculados na hora |
| datetime | Data da medição | Atualiza sozinha ao informar uma medição (pode editar) |
| sensor | Volume de água | m³, com litros e detalhe por região nos atributos |
| sensor | Temperatura da água | Espelha o sensor do aquecedor (opcional, só informativo: a tabela da Genco não usa temperatura) |
| sensor | Qualidade da água | `Água OK`, `Tratar Água`, `Aguardando nova medição`... |
| sensor | Correção alcalinidade / pH / cloro | Texto, como os antigos `sensor.piscina_correcao_*` |
| sensor | Adicionar pH Certo / pH Mais / pH Menos / cloro | Quantidade numérica em g ou mL |
| sensor | Último tratamento | Quando você registrou a última aplicação (atributo `aplicado` com o que foi colocado) |
| binary_sensor | Precisa de tratamento | Ligado quando algo está fora da faixa |
| select | Produto aplicado | Produto que será registrado; já vem com o da etapa sugerida |
| number | Quantidade aplicada | Quantidade realmente colocada (g ou mL); já vem com a dose sugerida, ajuste se aplicou diferente |
| button | Registrar etapa | Registra o produto e a quantidade informados e passa para a próxima etapa |
| button | Pular etapa | Pula a etapa sugerida sem aplicar nada (ela sai da sugestão até a próxima medição) |
| sensor | Etapa atual | O que aplicar agora, o que aguardar (e até quando) ou "Medir de novo"; atributo `etapas_restantes` |
| sensor | Resultado do tratamento | Esperado x medido depois da nova medição (atributo `resultados`) |
| sensor | Histórico de tratamentos | Últimos 20 tratamentos concluídos, mais o que está em andamento (atributo `resumo` em Markdown) |
| select | Aspecto da água | Limpa, Turva, Verde (algas), Verde transparente (metais) ou Manchas coloridas (metais): define qual produto de manutenção entra em ação |
| number | Metais dissolvidos | Opcional: só útil se você tiver um teste de metais em ppm (0 = não medido). Sem ele, vale a dose de 50 mL/m³; com valor, a dose passa a ser 15 mL/m³ por ppm. Não está nos cards |
| sensor | Algicida / Clarificante | Situação, dose, última e próxima aplicação, observações |
| sensor | Adicionar algicida / clarificante | Quantidade em mL a aplicar agora (0 se em dia) |
| sensor | Instruções de aplicação | Ordem e modo de aplicação (Markdown no atributo `instrucoes`) |
| sensor | Remedir a partir de | Prazo do rótulo para medir de novo: 1 h após pH Mais; no dia seguinte (24 h) após pH Menos, pH Certo ou cloro |
| sensor | Removedor de metais / Adicionar removedor de metais | Situação e dose (mL) do Genquest |
| binary_sensor | Aplicar removedor de metais | Ligado quando o tratamento de metais está no prazo ou aguardando condições |
| binary_sensor | Aplicar algicida / Aplicar clarificante | Ligado quando está no prazo ou aguardando condições |

Serviços opcionais, úteis em atalhos e automações:

* `healthy_pool.registrar_medicao`: informa alcalinidade, pH e cloro de uma vez.
* `healthy_pool.registrar_etapa`: registra uma aplicação (`produto` e `quantidade`). O produto pode ser a função (`alk_up`, `acid`, `ph_up`, `chlorine`, `algaecide`, `clarifier`, `metals_remover`) ou o nome do produto. Sem produto ou quantidade, usa a etapa sugerida.

## Tratamento por etapas

Um tratamento tem várias etapas e esperas entre elas. A integração acompanha cada uma:

1. **Etapa atual** mostra o primeiro produto a aplicar, na ordem: alcalinidade, pH, cloro, removedor de metais, algicida e clarificante. Produto aplicado e Quantidade aplicada já vêm preenchidos com a sugestão.
2. Aplicou? Ajuste a quantidade, se foi diferente, e toque em **Registrar etapa**. Para registrar outro produto, troque o **Produto aplicado** e informe a quantidade. Não aplicou? **Pular etapa**.
3. Depois de registrar uma correção (pH Certo, pH Mais, pH Menos ou cloro), aquele parâmetro fica "Aguardando nova medição" e **Remedir a partir de** mostra o prazo do rótulo (1 h após pH Mais, 24 h nos demais). **Enquanto isso, nenhuma outra etapa é sugerida**: a etapa atual mostra "Aguardar até ... para medir de novo". Em correções divididas em vários dias (por exemplo pH Menos em 3 aplicações), a dose seguinte vem da nova medição. Algicida e cloro também se seguram: o cloro só a partir de 12 h depois de um algicida e o algicida só a partir de 12 h depois do cloro; a etapa atual mostra isso entre parênteses, e o atributo `aguardar_ate` traz a hora.
4. Informe a nova medição. A integração compara o **antes e o depois** com a variação esperada pelo rótulo para a quantidade realmente aplicada, por exemplo 17 g/m³ de pH Certo sobem 10 ppm de alcalinidade, e mostra em **Resultado do tratamento** algo como "esperado +20, medido +12; 60 %, abaixo do esperado". Entre 70 % e 130 % conta como dentro do esperado.
5. Na aplicação seguinte, o tratamento anterior vai para o **Histórico** (guarda os últimos 20).

Observações:

* Só registra e compara, não altera doses sozinha. Com poucas medições, ajustar automaticamente poderia errar; use o resultado para decidir se muda o **fator de ajuste da dose de pH Mais** nas opções.
* No pH, a variação esperada é proporcional à dose sugerida (que leva até a meta). Para alcalinidade e cloro, vem direto dos rótulos. O cloro é consumido pelo uso e pelo sol, então ficar abaixo do esperado é comum.
* Medir antes do prazo do rótulo é aceito, mas o resultado traz um aviso.
* Para algicida, clarificante e removedor de metais não há variação numérica: o histórico guarda o aspecto da água antes e depois, quando você mudar o seletor **Aspecto da água**.
* O removedor de metais registrado mantém, por 7 dias, o cloro limitado a 1 ppm e sem choque.
* Um tratamento fica aberto até todos os parâmetros tratados serem medidos de novo, ou até 48 h sem novas etapas.

## Produtos e outras marcas

Os produtos (dose, esperas, regras e instruções) ficam em fichas JSON, não no código. Os produtos Genco vêm embutidos. Em **Configurar → Produtos** você escolhe, para cada função, qual produto usa:

| Função | Genco (padrão) |
|---|---|
| Subir alcalinidade | pH Certo |
| Baixar alcalinidade e pH | pH Menos |
| Subir pH | pH Mais |
| Cloro | Cloro granulado (dicloro 56 %) |
| Algicida | Algicida de manutenção e de choque |
| Clarificante | Genfloc |
| Removedor de metais | Genquest |

Para usar outra marca, crie a pasta `healthy_pool_products` na configuração do Home Assistant e coloque nela a ficha do produto. O formato está em [`custom_components/healthy_pool/products/README.md`](custom_components/healthy_pool/products/README.md). Contribuições com fichas de outras marcas são bem-vindas (pull request, com a fonte dos dados).

Nomes de sensores e botões não mudam ao trocar o produto (por exemplo, `sensor.piscina_adicionar_ph_certo` passa a mostrar o produto escolhido para subir a alcalinidade), então os cards continuam valendo.

## Como as doses são calculadas

| Situação | Produto | Cálculo | Fonte |
|---|---|---|---|
| Alcalinidade baixa | pH Certo | 1,7 g/m³ por ppm até a meta (100 ppm) | Rótulo: 17 g/m³ sobem 10 ppm |
| Alcalinidade alta | pH Menos | 1 mL/m³ por ppm até a meta, em aplicações de no máximo 20 mL/m³ | Rótulo: 10 mL/m³ a cada 10 ppm |
| pH alto | pH Menos | 10 mL/m³ (7,8 a 8,0) ou 20 mL/m³ (acima de 8,0) | Rótulo |
| pH baixo | pH Mais (barrilha) | Tabela do rótulo (dose para chegar a pH 7,5 com alcalinidade 80 ou 120 ppm), interpolada entre os pontos | Rótulo Genco |
| Cloro baixo | Cloro granulado (dicloro 56 %) | (meta − atual) × volume ÷ 0,56 g | Estequiometria. O rótulo do Genclor indica 2 a 3 g/m³ por dia, ajustados pelo residual; a integração calcula quanto falta para a meta |

Ordem de correção: primeiro a alcalinidade, depois o pH. Enquanto a alcalinidade estiver fora da faixa, a correção de pH fica bloqueada com a mensagem "Ajuste a alcalinidade antes de corrigir o pH".

Observações:

* A tabela do pH Mais vale para a meta de pH 7,5. Se mudar o pH alvo nas opções, a dose é ajustada proporcionalmente por um cálculo químico. O **fator de ajuste da dose de pH Mais** corrige a dose se o pH subir pouco ou demais.
* A dose de pH Menos para baixar a alcalinidade (10 mL/m³ a cada 10 ppm) vem da tabela do rótulo. O limite de 20 mL/m³ por aplicação é uma precaução minha, não do fabricante: doses grandes são divididas em uma aplicação por dia, e o rótulo manda reanalisar no dia seguinte.
* Cada aplicação sempre pede nova medição. Depois de aplicar, toque em **Registrar etapa**; a recomendação daquele parâmetro fica como "Aguardando nova medição" até você informar a próxima medição.
* Dicloro acrescenta ácido cianúrico (estabilizador) à água a cada dose. A integração não mede isso; vale testar o ácido cianúrico de tempos em tempos.

## Algicida, clarificante, removedor de metais e intervalos

Dados dos rótulos Genco:

| Produto | Dose | Intervalo | Regras |
|---|---|---|---|
| Algicida de manutenção (água limpa) | 5 mL/m³ | 7 dias (configurável) | pH 7,4 a 7,6; cloro livre 2 a 4 ppm; aspirar o fundo 2x por semana |
| Algicida de choque (Verde com algas) | 7 mL/m³ | 7 dias (o rótulo do de manutenção cita uso semanal do choque); repita antes só se as algas persistirem após escovar e aspirar | À base de íons de cobre; escovar e aspirar quando as algas ficarem marrons |
| Clarificante preventivo (água limpa) | 1,5 mL/m³ | 7 dias (configurável) | Filtrar 1 a 2 h |
| Clarificante corretivo (Turva ou Verde com algas) | 4,5 mL/m³ (faixa do rótulo: 3 a 6) | dose única, repete após 1 dia | Filtrar 6 a 8 h e aspirar |
| Removedor de metais Genquest (aspectos de metais) | 50 mL/m³ para eliminar coloração ou manchas, ou 15 mL/m³ por ppm de metal se informar o teste | repete após 7 dias se a cor persistir | pH 7,4 a 7,6 e alcalinidade 80 a 120; cloro no máximo 1 ppm; aplicar à noite; sem choque por 7 dias; manchas: escovar 5 a 7 dias e retrolavar todo dia |

Regras de segurança aplicadas automaticamente:

* **Algicida e cloro nunca juntos**: 12 h entre eles, nos dois sentidos. Se faltar cloro e o algicida também estiver no prazo, o cloro vem primeiro e o algicida fica marcado como "12 h depois de adicionar o cloro".
* O algicida só é liberado com o pH entre 7,4 e 7,6. Com pH de 7,2 a 7,4 a integração mostra a dose de pH Mais (tabela do rótulo) para entrar nessa faixa. Acima de 7,6 não há dose no rótulo (a tabela do pH Menos começa em 7,8), então só aparece o aviso, sem número.
* O removedor de metais também exige pH 7,4 a 7,6, alcalinidade 80 a 120 e cloro até 1 ppm; fora disso aparece o que ajustar.
* **Cloro limitado a 1 ppm e sem choque**: enquanto o aspecto for de metais e por 7 dias depois de registrar o removedor de metais, a integração não pede cloro e avisa se o residual passar de 1 ppm. Isso reduz a desinfecção; o card avisa e vale limitar o uso da piscina.
* O algicida de choque (cobre) só aparece no aspecto "Verde (algas)", nunca nos aspectos de metais.
* Reanálise conforme o rótulo: 1 h após o pH Mais; no dia seguinte após pH Menos, pH Certo e cloro.
* Liberação da piscina: 30 min após pH Mais, pH Menos, algicida e clarificante; 1 h após o removedor de metais; com cloro, só com o residual abaixo de 10 ppm.
* Conflito entre rótulos: o algicida pede cloro de 2 a 4 ppm e o removedor de metais exige no máximo 1 ppm. Durante a janela de metais a integração não pede cloro e o aviso do algicida explica o conflito.

**Aspecto da água**

| Aspecto | Quando usar | O que a integração faz |
|---|---|---|
| Limpa | Água cristalina | Algicida e clarificante em modo de manutenção semanal |
| Turva | Água sem brilho, partículas em suspensão | Clarificante corretivo |
| Verde (algas) | Verde turva, paredes e escadas escorregadias | Algicida de choque e clarificante corretivo |
| Verde transparente (metais) | Cor esverdeada mas água transparente | Removedor de metais, cloro limitado a 1 ppm, sem algicida de choque |
| Manchas coloridas (metais) | Manchas nas paredes e no piso | Removedor de metais com escovação e retrolavagem diária |

Água esverdeada e transparente sugere metais (cobre, ferro), mas é só um indício pela aparência: o resultado do tratamento é que confirma, por isso a integração manda reavaliar a cor após 7 dias. Fontes possíveis de metais: água de poço (o Genquest é indicado para piscinas abastecidas assim) e o algicida de choque, que contém íons de cobre.

Como usar: mude o **Aspecto da água**, aplique, e registre a etapa (produto e quantidade). Registrar o clarificante com a água "Turva" volta o aspecto para "Limpa". A dose do removedor de metais é a de eliminação do rótulo (50 mL/m³) e a integração mostra quantos frascos de 1 L ela equivale.

## Cards

Três arquivos em `lovelace/`, um por grupo. Cada um é um único card (`vertical-stack` com um cabeçalho de seção no topo), pronto para colar em um card **Manual** dentro de uma seção do dashboard. Requerem o Mushroom (`mushroom-template-card`, `mushroom-select-card` e `mushroom-entity-card`) e, no grupo 3, o `browser_mod` para o pop-up "Como aplicar".

| Seção | Arquivo | Conteúdo |
|---|---|---|
| 1. Entrada e medições | `card_piscina_1_entradas.yaml` | Alcalinidade, pH, cloro livre, data da medição, altura livre e o seletor de aspecto da água e o registro das etapas (produto aplicado, quantidade aplicada, registrar e pular etapa) |
| 2. Indicadores | `card_piscina_2_indicadores.yaml` | Situação geral (volume, temperatura), correção de alcalinidade, pH e cloro, e situação de algicida, clarificante e removedor de metais. Só leitura. As correções vêm dos atributos do sensor de qualidade da água, então não colidem com sensores antigos `sensor.piscina_correcao_*` |
| 3. Ações e orientações | `card_piscina_3_acoes.yaml` | Etapa atual, botão "Como aplicar" (abre a orientação em um pop-up do browser_mod: ordem, modo e quando medir de novo), resultado do tratamento e histórico |

## Notificações: lembrar da próxima ação

O sensor **Etapa atual** tem dois atributos para isso:

| Atributo | Conteúdo |
|---|---|
| `proxima_acao_em` | Quando algo libera: medir de novo (prazo do rótulo) ou o fim da espera de 12 h entre algicida e cloro. Vazio se não há espera |
| `proxima_acao_descricao` | O que fazer nesse momento, por exemplo "Medir de novo" ou "Aplicar 120 g de Cloro granulado" |

O horário continua disponível por 10 minutos depois de passar, para a automação não perder o instante. Atributo não serve para o gatilho de horário comum (`trigger: time`), então use um gatilho de **template**, que o Home Assistant reavalia a cada minuto:

```yaml
automation:
  - alias: Piscina - próxima ação liberada
    mode: single
    triggers:
      - trigger: template
        value_template: >-
          {% set t = state_attr('sensor.piscina_etapa_atual', 'proxima_acao_em') %}
          {{ t is not none and now() >= as_datetime(t) }}
    conditions:
      - condition: time
        after: "07:00:00"
        before: "21:00:00"
    actions:
      - action: notify.mobile_app_SEU_CELULAR
        data:
          title: Piscina
          message: "{{ state_attr('sensor.piscina_etapa_atual', 'proxima_acao_descricao') }}"
          data:
            tag: piscina-proxima-acao

  # Lembrete diário para o que ficou liberado fora do horário acima
  - alias: Piscina - lembrete diário
    triggers:
      - trigger: time
        at: "08:00:00"
    conditions:
      - condition: template
        value_template: >-
          {{ states('sensor.piscina_etapa_atual').startswith(('Aplicar', 'Medir', 'Chegou')) }}
    actions:
      - action: notify.mobile_app_SEU_CELULAR
        data:
          title: Piscina
          message: "{{ states('sensor.piscina_etapa_atual') }}"
```

Troque `notify.mobile_app_SEU_CELULAR` pelo serviço de notificação do seu celular (em **Ferramentas do desenvolvedor → Ações**, procure por `notify.`). A primeira automação avisa no momento certo; a segunda cobre o que liberou à noite ou de madrugada. Para avisar também sem horário limite, remova a condição de horário.

## Alerta de aplicação (exemplo de automação)

```yaml
alias: Piscina - algicida no prazo
triggers:
  - trigger: state
    entity_id: sensor.piscina_algicida
    attribute: situacao
    to: due
actions:
  - action: notify.notify
    data:
      title: Piscina
      message: "{{ states('sensor.piscina_algicida') }}"
```

Troque `sensor.piscina_algicida` por `sensor.piscina_clarificante` para o clarificante, ou use `binary_sensor.piscina_precisa_de_tratamento` para correções de alcalinidade, pH e cloro.

## Volume

Calculado com a entidade **Altura livre** (padrão 6,5 cm; de 5 a 8 cm o volume muda cerca de ±0,4 m³):

* parte funda: 395 × 500 cm, profundidade da água = 155 − altura livre
* área rasa: 395 × 200 cm, piso a 45 cm da borda, menos a escada
* escada: 3 degraus de 37 cm de pisada e 90 cm de largura (estimada pelo desenho), 4 degraus de altura entre o piso raso e o fundo

Resultado com 6,5 cm de altura livre: cerca de 32,9 m³.

## Exemplo de badge (Mushroom)

```yaml
type: custom:mushroom-template-badge
content: "{{ states('sensor.piscina_qualidade_da_agua') }}"
icon: >-
  {{ state_attr('sensor.piscina_qualidade_da_agua', 'icon') or 'mdi:pool' }}
color: >-
  {{ 'green' if is_state('sensor.piscina_qualidade_da_agua', 'Água OK') else 'red' }}
tap_action:
  action: fire-dom-event
  browser_mod:
    service: browser_mod.popup
    data:
      deviceID: this
      title: Qualidade da Água
      content:
        type: entities
        entities:
          - number.piscina_alcalinidade_total
          - sensor.piscina_correcao_alcalinidade
          - number.piscina_ph
          - sensor.piscina_correcao_ph
          - number.piscina_cloro_livre
          - sensor.piscina_correcao_cloro
          - datetime.piscina_data_da_medicao
          - select.piscina_produto_aplicado
          - number.piscina_quantidade_aplicada
          - button.piscina_registrar_etapa
```

Os `entity_id` seguem o nome dado na instalação; confira em **Configurações → Entidades**.

## Testes

```
python3 -m pytest tests -q
```

## Aviso

* Projeto pessoal, **sem fins comerciais**, sem afiliação, patrocínio ou endosso da Genco. Os nomes de produtos e marcas pertencem aos seus fabricantes e são citados apenas como referência de dosagem.
* As doses, intervalos e regras vêm das fichas dos produtos. As fichas embutidas reproduzem os rótulos e tabelas dos produtos Genco usados pelo autor. Alguns limites são precaução do autor (por exemplo, no máximo 20 mL/m³ de pH Menos por aplicação).
* A integração é uma **ajuda de cálculo e acompanhamento**, não substitui o rótulo nem orientação profissional. **Confira sempre a embalagem antes de aplicar.** Uso por sua conta e risco.
* Produtos químicos de piscina são perigosos: nunca misture produtos, use proteção e siga as instruções do fabricante.

## Versões

Ao subir o campo `version` do `manifest.json` na `main`, o workflow **Release** cria sozinho a tag `vX.Y.Z` e a release no GitHub, com as notas geradas pelos commits. O HACS passa a oferecer essa versão.

## Licença

[MIT](LICENSE).
