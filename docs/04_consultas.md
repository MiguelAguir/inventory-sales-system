# Consultas de negocio

Las 11 consultas viven en `sql/30_queries/` y se ejecutan con:

```bash
python -m src.pipeline queries --limit 20
```

El CLI recorre los archivos en orden, imprime un encabezado por consulta y corta
la salida a `--limit` filas. Los resultados de abajo corresponden al dataset
sintético descrito en el README.

## Resumen

| # | Archivo | Pregunta | Técnica principal |
|---|---|---|---|
| 1 | `01_top_productos_mes.sql` | ¿Qué productos lideran cada mes? | `rank()` y suma acumulada por mes |
| 2 | `02_ventas_categoria_mes.sql` | ¿Cómo evolucionan las categorías? | `lag()` para variación mensual e interanual |
| 3 | `03_rotacion_inventario.sql` | ¿Cuántas veces rota el inventario? | COGS 12 m / inventario promedio |
| 4 | `04_proveedores_mas_compras.sql` | ¿Qué proveedores concentran las compras? | Ranking y Pareto |
| 5 | `05_alertas_stock.sql` | ¿Qué reponer y con qué urgencia? | Stock vs. mínimo, cobertura y lead time |
| 6 | `06_abc_resumen.sql` | ¿Cómo se reparte el ingreso por clase? | Agregación de la clasificación ABC |
| 7 | `07_abc_detalle.sql` | ¿Qué productos sostienen el negocio? | Detalle del Pareto |
| 8 | `08_estacionalidad.sql` | ¿Hay estacionalidad? | Promedio por mes calendario e índice |
| 9 | `09_dia_semana.sql` | ¿Qué días se vende más? | Agregación por `dow` |
| 10 | `10_top_clientes.sql` | ¿Quiénes son los mejores clientes? | Ranking y días sin comprar |
| 11 | `11_stock_muerto.sql` | ¿Cuánto capital está inmovilizado? | Stock sin venta en 90 días |

## 1. Top productos por mes

Toma `reporting.v_ranking_productos` (que ya calcula `rank()` y la participación
acumulada por mes) y se queda con los últimos 12 meses y el top 10 de cada uno.

**Resultado de ejemplo (noviembre 2026):**

| Ranking | Producto | Ingresos | % del mes | % acumulado |
|---:|---|---:|---:|---:|
| 1 | Laptop 15" Ryzen 7 | S/ 142,478.70 | 27.25% | 27.25% |
| 2 | Desktop Core i5 | S/ 92,615.06 | 17.71% | 44.96% |
| 3 | Mini PC 16 GB | S/ 79,905.64 | 15.28% | 60.25% |

**Lectura:** la concentración no es solo anual. En un mes cualquiera, dos o tres
productos explican más de la mitad de la venta. Eso vuelve crítico el stock de
esos SKU y explica por qué las alertas de reposición se priorizan por déficit.

## 2. Ventas por categoría y mes

Calcula la variación mes a mes con `lag(revenue)` y la interanual con
`lag(revenue, 12)`. La participación se calcula dentro de la vista, con
`sum(revenue) OVER (PARTITION BY month)`.

**Resultado global del periodo:**

| Categoría | Ingresos | Participación |
|---|---:|---:|
| Computadoras | S/ 13,047,895.86 | 74.83% |
| Impresión | S/ 1,477,481.79 | 8.47% |
| Mobiliario | S/ 718,716.53 | 4.12% |
| Periféricos | S/ 653,798.24 | 3.75% |
| Redes | S/ 484,495.64 | 2.78% |

**Lectura:** el negocio es, en la práctica, un distribuidor de computadoras. Las
demás categorías existen y rotan, pero no mueven la aguja del ingreso. La
variación mensual se usa para detectar caídas antes de que terminen el mes.

## 3. Rotación de inventario

Reconstruye el inventario al inicio y al final del periodo con
`reporting.fn_inventory_value_at()`, que suma el libro mayor hasta una fecha y
valoriza cada saldo al último costo conocido. Luego divide el COGS de 12 meses
entre el inventario promedio.

**Resultado:**

| Categoría | Rotación anual | Días de inventario |
|---|---:|---:|
| Protección personal | 27.93 | 13.1 |
| Computadoras | 20.99 | 17.4 |
| Consumibles | 11.71 | 31.2 |
| Herramientas | 6.41 | 56.9 |
| Mobiliario | 5.63 | 64.8 |

Rango: **5.63 a 27.93 vueltas** (13 a 65 días); promedio simple: **12.30**.

**Lectura:** las categorías de mayor valor rotan rápido, lo que es deseable. Las
de menor rotación no llegan a ser un problema de capital: su inventario es
pequeño. La consulta sirve para decidir dónde bajar el stock mínimo y dónde
conviene negociar compras más frecuentes.

> El tablero usa `reporting.v_rotacion_actual`, que anualiza el COGS de 90 días.
> Es una aproximación más reactiva que la consulta de 12 meses; por eso los
> valores pueden diferir. Ambas están documentadas y usan la misma lógica.

## 4. Proveedores con más compras

`reporting.v_proveedores_compras` agrupa compras confirmadas por proveedor y
calcula monto, ticket promedio y participación. La consulta agrega el acumulado
con una ventana ordenada por monto.

**Resultado:**

| Ranking | Proveedor | Compras | Monto | % total | % acumulado |
|---:|---|---:|---:|---:|---:|
| 1 | Importaciones del Pacífico 03 | 99 | S/ 2,885,076.73 | 23.66% | 23.66% |
| 2 | Distribuidora Piura 18 | 131 | S/ 2,719,717.36 | 22.31% | 45.97% |
| 3 | Papelera Nacional 08 | 186 | S/ 1,757,571.39 | 14.42% | 60.39% |
| 4 | Redes y Servicios 07 | 75 | S/ 1,244,085.94 | 10.20% | 70.59% |
| 5 | Comercial Arequipa 12 | 100 | S/ 1,061,098.56 | 8.70% | 79.29% |

**Lectura:** cinco proveedores concentran 79.29% de la compra. Es un riesgo de
abastecimiento, no solo un dato comercial: si el proveedor 1 se retrasa, el
stock de computadoras se resiente. El lead time de cada proveedor ya se usa en
las alertas de reposición.

## 5. Alertas de reposición

Cruza el saldo (`reporting.v_stock_actual`) con el mínimo configurado, la venta
diaria de los últimos 30 días y el lead time del proveedor preferido. Devuelve
prioridad, motivo y una cantidad sugerida:

```text
max(ceil(venta_diaria * 30 + stock_minimo - stock_actual), 0)
```

**Resultado:** 41 alertas.

| Prioridad | Filas | Criterio |
|---|---:|---|
| CRÍTICA | 3 | stock = 0 |
| ALTA | 25 | stock ≤ mínimo |
| MEDIA | 13 | cobertura ≤ lead time |

**Lectura:** la cantidad sugerida cubre 30 días de venta más el mínimo. No es una
orden de compra automática: es una propuesta para que el jefe de almacén la
revise.

## 6 y 7. Clasificación ABC

La clase se asigna por participación acumulada antes del producto: A hasta 80%,
B hasta 95%, C el resto. Se calcula en `reporting.v_abc_productos`.

**Resumen:**

| Clase | Productos | Unidades | Ingresos | % ingresos | Margen |
|---|---:|---:|---:|---:|---:|
| A | 7 | 5,519 | S/ 14,017,615.81 | 80.39% | 29.66% |
| B | 15 | 10,049 | S/ 2,638,743.88 | 15.13% | 32.25% |
| C | 36 | 14,561 | S/ 781,039.39 | 4.48% | 31.27% |

**Detalle del top 5:**

| Producto | Ingresos | % | % acumulado |
|---|---:|---:|---:|
| Laptop 15" Ryzen 7 | S/ 4,025,080.27 | 23.08% | 23.08% |
| Desktop Core i5 | S/ 3,815,080.05 | 21.88% | 44.96% |
| Laptop 14" Core i5 | S/ 1,937,206.58 | 11.11% | 56.07% |
| All in One 23.8" | S/ 1,768,859.42 | 10.14% | 66.22% |
| Mini PC 16 GB | S/ 1,501,669.54 | 8.61% | 74.83% |

**Lectura:** 7 de 60 productos generan 80% del ingreso. La clase C son 36
productos que aportan 4.48%: candidatos a descontinuar o a comprar solo bajo
pedido. El margen es parecido entre clases, así que la diferencia no está en el
precio sino en el volumen.

## 8. Estacionalidad

Promedia el ingreso de cada mes calendario y lo expresa como índice contra el
promedio general (100 = mes promedio).

**Resultado:**

| Mes | Ingreso promedio | Índice |
|---|---:|---:|
| Enero | S/ 381,106.15 | 52.45 |
| Febrero | S/ 438,938.29 | 60.41 |
| Marzo | S/ 792,813.67 | 109.12 |
| Noviembre | S/ 826,621.10 | 113.77 |
| Diciembre | S/ 985,856.47 | 135.69 |

Promedio mensual: S/ 726,558.30; mínimo S/ 372,208.20; máximo S/ 1,130,380.08.
El mejor mes del periodo es 2025-11.

**Lectura:** diciembre vende 35.69% más que el promedio; enero, 47.55% menos. La
caída de enero y febrero es la más marcada. Para el negocio implica planificar
compras y capital de trabajo con ese ciclo, no con un promedio plano.

## 9. Ventas por día de la semana

Agrega las ventas confirmadas por `extract(dow)` y calcula ticket promedio.

| Día | Transacciones | Ingresos | Ticket promedio |
|---|---:|---:|---:|
| Domingo | 321 | S/ 913,065.08 | S/ 2,844.44 |
| Lunes | 1,057 | S/ 2,443,990.51 | S/ 2,312.20 |
| Jueves | 1,002 | S/ 3,169,264.16 | S/ 3,162.94 |
| Viernes | 1,121 | S/ 3,188,484.28 | S/ 2,844.32 |
| Sábado | 784 | S/ 2,099,291.38 | S/ 2,677.67 |

**Lectura:** el domingo es el día más flojo en volumen y en ingreso. Jueves y
viernes concentran la mayor facturación; el ticket más alto es el del jueves.
Es un patrón del generador sintético, útil para probar reportes por día.

## 10. Top clientes

Ranking por ingreso con participación, acumulado y días desde la última compra.

| Ranking | Cliente | Pedidos | Ingresos | % total | % acumulado | Días sin comprar |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Cliente Sintético 121 | 608 | S/ 1,767,402.17 | 10.14% | 10.14% | 2 |
| 2 | Empresa Sintética 003 | 527 | S/ 1,566,677.33 | 8.98% | 19.12% | 3 |
| 3 | Empresa Sintética 020 | 182 | S/ 450,436.33 | 2.58% | 21.70% | 5 |
| 4 | Empresa Sintética 038 | 104 | S/ 409,706.46 | 2.35% | 24.05% | 6 |
| 5 | Cliente Sintético 200 | 163 | S/ 378,420.60 | 2.17% | 26.22% | 5 |

**Lectura:** el top 5 explica 26.22% del ingreso. Los dos primeros son clientes
recurrentes de volumen alto. La columna de días sin comprar permite separar un
cliente activo de uno que se está enfriando.

## 11. Stock muerto

Lista el stock con existencia y sin movimiento `SALE` en los últimos 90 días,
valorizado a costo estándar.

**Resultado:** 8 filas, S/ 2,483.31 inmovilizados.

| Almacén | Producto | Stock | Valor | Última venta |
|---|---|---:|---:|---|
| WH-SUR | Guantes anticorte 03 | 13 | S/ 508.95 | nunca |
| WH-SUR | Chaleco reflectivo 02 | 14 | S/ 349.58 | nunca |
| WH-SUR | Casco de seguridad 01 | 12 | S/ 348.60 | nunca |
| WH-CENTRAL | Chaleco reflectivo 02 | 13 | S/ 324.61 | nunca |
| WH-CENTRAL | Casco de seguridad 01 | 9 | S/ 261.45 | nunca |

Las 8 filas son EPP; 4 están en el almacén Sur.

**Lectura:** el monto es bajo respecto al inventario total (S/ 424,380.36), pero
el patrón es claro: EPP se compró y no se vendió en el periodo reciente. La
consulta no decide qué hacer; muestra dónde mirar antes de volver a comprar.

## Notas de implementación

- Todas las consultas son de solo lectura y se apoyan en vistas de `reporting`,
  no en tablas copiadas.
- Los importes usan `line_subtotal` (sin IGV) para que la comparación con COGS
  sea consistente. El tablero muestra ingresos con IGV en el escalar.
- Las ventanas (`rank`, `lag`, `sum ... over`) están en las vistas cuando se
  reutilizan en más de una consulta; así el SQL de negocio queda corto.
- Los resultados cambian si se regenera el dataset en otra fecha, porque el
  periodo son 24 meses móviles que terminan ayer.
