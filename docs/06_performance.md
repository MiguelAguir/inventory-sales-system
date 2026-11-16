# Rendimiento y planes de ejecucion

Generado: 2026-11-16 16:30 (America/Lima)

## Entorno

- PostgreSQL 16.16 (Debian 16.16-1.pgdg13+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit
- Volumen: 6,519 ventas, 13,023 lineas, 15,485 movimientos de stock.
- Entorno local en Docker, cache caliente despues de un calentamiento.
- Medicion: mediana de 7 ejecuciones de `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.

## Resultados

| Consulta | Con indice (ms) | Sin indice (ms) | Aceleracion | Plan con indice | Plan sin indice |
|---|---:|---:|---:|---|---|
| Movimientos de un producto/almacen (id 10/1, 30 dias) | 0.440 | 3.741 | x8.5 | Aggregate -> Index Scan | Aggregate -> Seq Scan |
| Ventas confirmadas del mes anterior | 2.338 | 4.714 | x2.02 | Aggregate -> Sort -> Hash Join -> Seq Scan -> Hash -> Index Scan | Aggregate -> Sort -> Hash Join -> Seq Scan -> Hash |
| Top 10 productos por ingreso (todo el periodo) | 9.152 | 10.342 | x1.13 | Limit -> Sort -> Aggregate -> Hash Join -> Seq Scan -> Hash | Limit -> Sort -> Aggregate -> Hash Join -> Seq Scan -> Hash |

## Lectura

- Consulta selectiva del libro mayor: El indice aporta: 8.50x mas rapido (0.440 ms vs 3.741 ms). Plan con indices: Aggregate -> Index Scan; sin indices: Aggregate -> Seq Scan.
- Ventas de un mes: El indice aporta: 2.02x mas rapido (2.338 ms vs 4.714 ms). Plan con indices: Aggregate -> Sort -> Hash Join -> Seq Scan -> Hash -> Index Scan; sin indices: Aggregate -> Sort -> Hash Join -> Seq Scan -> Hash.
- Top 10 productos por ingreso: Diferencia marginal (9.152 ms vs 10.342 ms, 1.13x): ambos planes cuestan practicamente lo mismo. Plan con indices: Limit -> Sort -> Aggregate -> Hash Join -> Seq Scan -> Hash; sin indices: Limit -> Sort -> Aggregate -> Hash Join -> Seq Scan -> Hash.

- En una agregacion global el costo dominante es leer y agrupar casi toda la tabla. Ahi un indice no reduce el trabajo y puede hasta estorbar si el planeador lo elige por error.
- Conclusion honesta: indexar no es automatico. Primero se mide; se indexa lo que filtra, y no se asume que un indice siempre acelera.

## Notas

- Los tiempos absolutos dependen de la maquina y de Docker; la comparacion relativa es la util.
- Para cada escenario se quitaron **todos** los indices que podian servir la consulta, no uno solo; despues se restauraron uno por uno.
- `DROP INDEX` y `CREATE INDEX` se ejecutaron en autocommit y se verifico su restauracion al final.
- Los indices se definen en `sql/00_schema/03_indexes.sql`.
