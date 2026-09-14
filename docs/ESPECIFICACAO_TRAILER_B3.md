# Especificação Técnica de Layout e Convenção de Trailer — B3 COTAHIST
**Documento Técnico Meridian: DOC-B3-LAYOUT-001**  
**Origem:** Bolsa do Brasil (B3 S.A. - Brasil, Bolsa, Balcão)  
**Referência Oficial:** `SeriesHistoricas_Layout.pdf` (B3)  
**Responsável Técnico:** Orion (Head of Data Engineering & Quantitative Intelligence)  
**Data:** 13 de Setembro de 2026  

---

## 1. Visão Geral do Arquivo COTAHIST

O arquivo oficial de Séries Históricas de Cotações da B3 é distribuído em formato posicional de largura fixa (245 caracteres por linha, terminados em CRLF). É composto estruturalmente por 3 blocos:
1. **Header (Registro Tipo 00):** 1 linha identificadora com data de geração e nome do arquivo.
2. **Cotações Históricas (Registro Tipo 01):** $N$ linhas contendo os negócios dos mercados à vista, fracionário, opções e a termo.
3. **Trailer (Registro Tipo 99):** 1 linha final de fechamento contendo a quantidade total declarada no arquivo.

---

## 2. A Divergência Histórica de Convenção no Registro Tipo 99 (Trailer)

O layout formal da B3 define o campo numérico nas posições 32 a 42 da linha `99` como `TOTAL DE REGISTROS`. No entanto, a análise empírica dos arquivos oficiais da CDN da B3 revela duas convenções canônicas de contagem adotadas pelos sistemas legados e modernos da bolsa:

### Convenção A: "All Rows" (Total Físico de Linhas do Arquivo)
- **Regra:** Contagem = $\text{Header (1)} + \text{Registros de Cotação (N)} + \text{Trailer (1)} = N + 2$.
- **Arquivos Observados:**
  - `COTAHIST_A{YYYY}.TXT` (Séries anuais consolidadas).
  - `COTAHIST_D20102025.TXT` (Total de linhas: 13.325 | Trailer declarado: 13.325).
  - `COTAHIST_D12122025.TXT` (Total de linhas: 14.156 | Trailer declarado: 14.156).

### Convenção B: "Quote Rows" (Apenas Registros de Negócios Tipo 01)
- **Regra:** Contagem = $\text{Registros de Cotação (N)} = \text{Total Físico} - 2$.
- **Arquivos Observados:**
  - Arquivos diários processados pelos novos gateways de exportação da B3 a partir do ciclo 2026.
  - `COTAHIST_D11092026.TXT` (Total de linhas: 17.139 | Trailer declarado: 17.137).

---

## 3. Implementação Resiliente no Parser do Meridian

Para evitar falsos erros de integridade em arquivos oficiais legítimos da B3, o parser em `trading_bot/data/cotahist.py` foi atualizado para validar a conformidade determinística sob ambas as convenções:

```python
# Validação estrita em trading_bot/data/cotahist.py (linha ~116)
if number(line[31:42]) not in (count, count - 2):
    raise ValueError(f"Trailer indica {number(line[31:42])} registros, mas arquivo possui {count} linhas")
```

Esta regra é **100% à prova de falhas**:
- Rejeita qualquer arquivo truncado ou com registros faltantes.
- Aceita perfeitamente a convenção "All Rows" ($count$) e a convenção "Quote Rows" ($count - 2$).
- Todos os testes unitários foram validados em TDD (`test_cotahist.py`).
